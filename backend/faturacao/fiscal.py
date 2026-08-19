"""A emissão da Fatura Simplificada, com idempotência (Plano 2B, Task 3) —
o coração do módulo inteiro: é este ficheiro que liga a conta do balcão
(`venda.py`) ao Vendus (`vendus/emissao.py`) e emite o documento fiscal real.

**Onde os erros custam dinheiro.** A partir do dia em que isto entra em
produção, é este código que emite os documentos fiscais das 5 lojas do
dono. Uma fatura emitida duas vezes é uma cobrança a dobrar à Autoridade
Tributária, que só se corrige emitindo uma nota de crédito — e no fecho do
dia aparece como dinheiro a menos na gaveta, que a funcionária tem de
justificar ou pagar do bolso. Já aconteceu um bug destes num projecto
anterior do mesmo dono (`~/dev/pizzaria`); as defesas abaixo nasceram dele.

## A sequência (spec §6.1)

1. **Referência determinística** — `ext_ref_determinista`: depende só da
   identidade da venda (loja + sessão + id), NUNCA de um relógio. Duas
   tentativas da mesma venda produzem sempre a mesma referência.
2. **Reserva atómica, ANTES de tocar no Vendus** — insere em
   `fat_refs_fiscais` com índice único em `ext_ref` (declarado em `db.py`).
   Quem perde a corrida (`DuplicateKeyError`) NUNCA emite: ou o documento do
   vencedor já existe (devolve-o), ou está a ser escrito agora mesmo
   (espera por ele, com um orçamento limitado de tentativas).
3. **Emitir** e gravar em `fat_documentos` (índices únicos em
   `vendus_document_id` e em `atcud` — a quarta defesa, ver
   `ConflitoDocumentoFiscal`).
4. **Se a emissão falhar por indisponibilidade** (timeout, ligação, ou um
   5xx persistente — tudo o que `vendus.emissao` tipifica como
   `VendusIndisponivel`, porque em qualquer um destes casos não sabemos se o
   Vendus chegou a processar o pedido): UMA chamada exacta por
   `external_reference`, nunca um varrimento dos documentos do dia — essa é
   a armadilha documentada em `~/dev/pizzaria/backend/server.py`
   (`per_page=200` sem paginar: numa loja com 240 talões a fatura original
   nem entra na lista lida, e sai uma segunda fatura real). Se a verificação
   não encontrar nada, ou ela própria rebentar, o erro original propaga-se
   — nunca se "emite à mesma" só porque a verificação falhou.

`finalizar_venda` é o núcleo puro desta sequência: recebe `emitir` e
`verificar` já como duas funções assíncronas de UM argumento (a `ext_ref`),
para os testes poderem substituir o Vendus por duplos triviais sem threads
nem rede. É a rota `POST /pos/venda/{venda_id}/finalizar`, mais abaixo, que
liga esses dois parâmetros ao `ClienteEmissaoVendus` real, através de
`asyncio.to_thread` (o `httpx.Client` é síncrono — chamá-lo directamente
bloquearia o event loop do portal inteiro, RH e Financeiro incluídos).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from .auth import gestor_atual
from .db import COLECOES, indice_idempotencia_confirmado, obter_db
from .importacao import _nif_configurado
from .pos_auth import operador_atual
from .precos import _tem_mais_de_2_casas_decimais
from .venda import (
    _bruto_da_linha,
    _desconto_da_linha,
    _desconto_global_eur,
    _garante_aberta,
    _linha_vendus,
    _obter_venda_da_loja,
    _totais,
    _venda_publica,
)
from .vendus.cliente import VendusErro, VendusIndisponivel, obter_conta
from .vendus.emissao import ClienteEmissaoVendus, _register_id_configurado

logger = logging.getLogger(__name__)

router = APIRouter()

_LISBOA = ZoneInfo("Europe/Lisbon")

# Orçamento de espera de quem perde a reserva: a reserva já existe mas o
# documento ainda não foi gravado (o vencedor está a meio da chamada ao
# Vendus). 50 tentativas × 50ms = 2,5s no pior caso em produção — uma venda
# ao balcão não pode ficar pendurada minutos a fio, mas 2,5s cobre folgado
# uma chamada HTTP normal ao Vendus.
_TENTATIVAS_ESPERA_VENCEDOR = 50
_ESPERA_ENTRE_TENTATIVAS_S = 0.05

_MSG_LINHAS_VAZIAS = "A venda não tem nenhuma linha — nada para faturar."
_MSG_TOTAL_NAO_POSITIVO = (
    "O total da venda tem de ser positivo para emitir uma fatura — "
    "confirme os descontos aplicados."
)
_MSG_TIPO_PAGAMENTO_INEXISTENTE = "Tipo de pagamento não encontrado ou inactivo."
_MSG_TIPO_PAGAMENTO_SEM_VENDUS = (
    "Este tipo de pagamento não tem um método do Vendus associado — "
    "não pode ser usado para emitir uma fatura real."
)
_MSG_SESSAO_NAO_ABERTA = (
    "A sessão de caixa desta venda já não está aberta — não é possível "
    "emitir fatura para uma venda de um turno já fechado."
)
_MSG_VENDA_CANCELADA_ENTRETANTO = (
    "Esta conta foi cancelada enquanto a fatura estava a ser preparada — NÃO "
    "saiu nenhuma Fatura Simplificada e nada foi enviado ao Vendus. Se o "
    "cliente ainda quer levar, abra uma conta nova."
)
_MSG_SESSAO_FECHADA_ENTRETANTO = (
    "A caixa desta venda foi FECHADA enquanto a fatura estava a ser "
    "preparada — NÃO saiu nenhuma Fatura Simplificada e nada foi enviado ao "
    "Vendus. Esta conta pertence a um turno já fechado e não pode ser "
    "faturada: o Z desse turno já foi assinado sem ela. Pique a conta de "
    "novo na sessão de caixa nova."
)
_MSG_INDICE_IDEMPOTENCIA_EM_FALTA = (
    "O índice de idempotência (fat_refs_fiscais.ext_ref) não está "
    "confirmado no arranque — o POS recusa emitir faturas até isto ser "
    "corrigido, para nunca arriscar duas Faturas Simplificadas reais da "
    "mesma venda."
)


class FiscalErro(Exception):
    """Erro base deste módulo (distinto de VendusErro — este é sobre a
    NOSSA orquestração da idempotência, não sobre a comunicação HTTP em
    si)."""


class EmissaoEmCurso(FiscalErro):
    """A reserva desta venda já existe e o documento ainda não ficou
    disponível dentro do orçamento de espera — a emissão pode estar mesmo a
    decorrer noutro pedido, ou ter ficado presa a meio. Quem chama devolve
    isto ao POS como "tente novamente dentro de momentos", nunca inventa um
    documento."""


class ConflitoDocumentoFiscal(FiscalErro):
    """O Vendus devolveu um documento cujo `vendus_document_id` ou `atcud`
    colide com um já gravado para uma referência externa DIFERENTE — não
    devia poder acontecer com um Vendus saudável, mas se acontecer a reserva
    NÃO se liberta (o Vendus emitiu mesmo um documento fiscal real; libertar
    a reserva convidaria a emitir um segundo) e o erro é alto e claro, para
    investigação manual."""


class VendaJaNaoAberta(FiscalErro):
    """Entre o momento em que a rota `finalizar` viu a venda `aberta` e o
    momento em que esta tentativa GANHOU a reserva, a venda deixou de estar
    aberta — na prática, foi cancelada. NADA foi ao Vendus: a reserva
    liberta-se e não se emite (ver `_garante_venda_ainda_aberta`)."""


class SessaoJaNaoAberta(FiscalErro):
    """A SESSÃO DE CAIXA desta venda deixou de estar aberta entre a
    validação da rota `finalizar` e o momento em que esta tentativa ganhou a
    reserva — outro PC fechou a caixa nessa janela.

    É o defeito I1 (`_garante_sessao_da_venda_aberta`: "o dinheiro entrava
    na gaveta sem pertencer a fecho nenhum") a repetir-se pela CORRIDA, e
    não pelo esquecimento: a pergunta era feita uma vez, sobre um retrato
    tirado antes da validação toda, e nunca mais se repetia. Dois PCs na
    mesma caixa (a configuração que `venda.venda_aberta` documenta como
    estado estável) chegam lá: às 23:58 a Rafaela carrega em FINALIZAR e o
    Vendus demora; a Ana, no outro PC, conta a gaveta e fecha a caixa. Sem
    esta releitura saía uma FS REAL depois do Z — o Z assinado sem essa
    venda, o dinheiro dela na gaveta como sobra por justificar, e a venda
    `emitida` numa sessão fechada, que não entra em Z nenhum (nem neste, nem
    no seguinte, que filtra pelo `sessao_id` da sessão nova).

    Como em `VendaJaNaoAberta`: nada foi ao Vendus, a reserva liberta-se, e
    não se emite. A outra metade desta defesa está em
    `caixa.py::fechar_caixa`, que recusa fechar enquanto houver uma reserva
    fiscal viva numa venda daquela sessão."""


class VerificacaoFiscalIncerta(FiscalErro):
    """Depois de um timeout na emissão, a PRÓPRIA verificação por
    `external_reference` também falhou — a falha CORRELACIONADA e mais
    provável (a mesma rede que derrubou o POST derruba o GET a seguir).
    Sem essa verificação não há forma de saber se o Vendus chegou a criar o
    documento: nem se pode assumir que não (e emitir outra vez, arriscando
    uma segunda Fatura Simplificada real da mesma venda), nem se pode
    inventar que sim.

    A reserva NÃO se liberta — fica marcada `incerta` (ver
    `_marcar_reserva_incerta`), para a tentativa seguinte ser OBRIGADA a
    verificar antes de poder fazer seja o que for (ver
    `_retomar_reserva_incerta`). Quem chama (a rota `finalizar`) devolve
    isto ao POS como "não foi possível confirmar, veja o Vendus" — nunca
    como um "tente outra vez" genérico que convidaria a operadora a repetir
    às cegas."""


def _distribuir_centimos(total_eur: float, pesos: List[float]) -> List[float]:
    """Distribui `total_eur` (positivo, arredondado a cêntimos) pelos
    `pesos` (uma lista de valores >= 0 — tipicamente o líquido de cada linha
    depois do seu desconto próprio), proporcionalmente e em CÊNTIMOS
    EXACTOS — nunca uma fracção de cêntimo por linha.

    Método do maior resto (Hamilton): cada linha recebe primeiro os
    cêntimos inteiros da sua quota proporcional (arredondada por baixo); o
    resto se ficarem cêntimos por atribuir (sempre < nº de linhas) vai, um a
    um, para as linhas com a maior parte fraccionária perdida — em caso de
    empate, a de índice mais baixo, para o resultado ser sempre o MESMO
    para os mesmos dados, nunca dependente de instabilidade de ordenação.

    Garante, por construção, que a soma dos valores devolvidos bate
    EXACTAMENTE com `total_eur` (arredondado a cêntimos) — é esta garantia,
    e não uma percentagem recomposta que o Vendus tinha de arredondar outra
    vez do lado dele, que fecha o defeito C3 (a revisão do núcleo fiscal):
    o Vendus arredonda cada linha ao cêntimo; nós arredondávamos o desconto
    GLOBAL uma única vez sobre o total, e as duas somas podiam divergir até
    ±0,02–0,03€ numa venda com várias linhas."""
    total_centimos = round(total_eur * 100)
    soma_pesos = sum(pesos)
    if total_centimos <= 0 or soma_pesos <= 0:
        return [0.0] * len(pesos)

    quotas = [total_centimos * peso / soma_pesos for peso in pesos]
    base = [int(q) for q in quotas]  # trunca — a parte inteira da quota
    restantes = total_centimos - sum(base)
    ordem = sorted(range(len(pesos)), key=lambda i: (-(quotas[i] - base[i]), i))
    for indice in ordem[:restantes]:
        base[indice] += 1
    return [centimos / 100.0 for centimos in base]


def _percentagem_que_reproduz(bruto: float, alvo_liquido: float) -> float:
    """B2 (a re-revisão do núcleo fiscal): converte um ALVO em euros — o
    líquido exacto que esta linha tem de mostrar, já calculado ao cêntimo
    (ver `_distribuir_centimos`) — na `discount_percentage` que, aplicada
    pelo Vendus (assumindo `gross*(1-pct/100)`, arredondado ao cêntimo — a
    MESMA fórmula de `combine_global` em
    `~/dev/pizzaria/backend/pos/pricing.py`, já provada em produção nesta
    API), REPRODUZ esse alvo. 4 casas decimais, a mesma precisão da
    Pizzaria: resolução de 0,00005 pontos percentuais, um erro absoluto na
    ordem de `bruto × 0,0000005` — para uma linha de açaí (poucas dezenas de
    euros) isso é uma fracção de milésimo de cêntimo, sempre reabsorvido
    pelo arredondamento final a 2 casas. Só em casos EXTREMOS (uma linha de
    valor muito fora do realista, ou um alvo mesmo em cima de uma fronteira
    de arredondamento) é que `round(bruto*(1-pct/100), 2)` pode acabar um
    cêntimo ao lado do alvo — ver o relatório da tarefa: sem uma fatura de
    teste real contra o Vendus (modo `tests`), isto fica por confirmar em
    definitivo."""
    if bruto <= 0:
        return 0.0
    pct = round(100.0 * (1 - alvo_liquido / bruto), 4)
    return max(0.0, min(100.0, pct))


def _itens_vendus(venda: Dict) -> List[Dict]:
    """As linhas da venda no formato Vendus, com o desconto — próprio da
    linha mais a fatia do desconto GLOBAL que lhe calhar — sempre como
    `discount_percentage`, NUNCA `discount_amount`.

    B2 (a re-revisão do núcleo fiscal, revertendo C3): `discount_amount`
    NUNCA saiu deste código antes de C3, e a sua semântica exacta (desconto
    da linha INTEIRA, como aqui se assumia, ou desconto POR UNIDADE,
    multiplicado por `qty`?) nunca foi confirmada contra o Vendus real — o
    único outro sistema do dono a emitir Faturas Simplificadas reais pela
    MESMA API, `~/dev/pizzaria/backend/pos/pricing.py::combine_global`,
    recusa-se explicitamente a enviá-lo, com um comentário a dizer que "a
    semântica (por unidade vs por linha) não é fiável". Onde as duas
    leituras divergem, o erro é grande: 3 unidades a 8,99€ com desconto —
    enviar `discount_amount=5,13` numa linha `qty=3` dá um líquido de
    21,84€ se o Vendus aplicar por linha, ou 11,58€ se for por unidade —
    10,26€ de erro numa só linha (com `qty=1` as duas leituras são
    indistinguíveis, e é por isso que os testes anteriores não apanhavam
    nada). A decisão está tomada: não se usa um campo cuja semântica não se
    conhece. `discount_percentage`, ao contrário, é o campo que o código do
    dono já usa em produção (`combine_global`) — a sua semântica está
    confirmada.

    O problema que C3 resolvia (o Vendus arredonda CADA linha ao cêntimo
    antes de somar; uma `discount_percentage` recomposta e arredondada UMA
    VEZ sobre o total podia divergir ±0,02–0,03€ — medido: 7 linhas a
    1,15€ com 5€ de desconto global, nós 3,05€, o Vendus 3,08€) continua
    resolvido, mas de outra forma: a aritmética exacta ao cêntimo do C3
    (`_distribuir_centimos`, método do maior resto) MANTÉM-SE tal e qual —
    é o ALVO em euros de cada linha, não os números que se enviam. Só o
    ÚLTIMO passo muda: em vez de enviar esse alvo directamente como
    `discount_amount`, converte-se numa `discount_percentage` que, quando o
    Vendus a aplicar linha a linha e arredondar ao cêntimo (a MESMA
    fórmula, não uma recomposição sobre o total agregado), REPRODUZ esse
    alvo (`_percentagem_que_reproduz`). O nosso total (`venda._totais`, que
    já é a soma destes alvos exactos, por construção do maior resto) e o
    que o Vendus vai calcular batem sempre certo — usando só o campo cuja
    semântica se conhece."""
    linhas_vendus = [_linha_vendus(li) for li in venda.get("linhas", [])]
    if not linhas_vendus:
        return []

    brutos = [_bruto_da_linha(li) for li in linhas_vendus]
    descontos_proprios = [_desconto_da_linha(li) for li in linhas_vendus]
    liquidos_apos_linha = [round(b - d, 2) for b, d in zip(brutos, descontos_proprios)]
    liquido_linhas = round(sum(liquidos_apos_linha), 2)
    desconto_global = _desconto_global_eur(venda, liquido_linhas)

    partes_globais = (
        _distribuir_centimos(desconto_global, liquidos_apos_linha)
        if desconto_global > 0
        else [0.0] * len(linhas_vendus)
    )

    saida = []
    for li, bruto, liquido_apos_propria, parte_global in zip(
        linhas_vendus, brutos, liquidos_apos_linha, partes_globais
    ):
        item = {chave: li[chave] for chave in ("title", "qty", "gross_price", "tax_id") if chave in li}
        alvo_liquido = round(liquido_apos_propria - parte_global, 2)
        pct = _percentagem_que_reproduz(bruto, alvo_liquido)
        if pct > 0:
            item["discount_percentage"] = pct
        saida.append(item)
    return saida


def ext_ref_determinista(loja_id: str, sessao_id: str, venda_id: str) -> str:
    """`pos-{loja}-{sessao}-{venda}` — depende só da IDENTIDADE da venda,
    nunca de um relógio nem do conteúdo das linhas. Duas tentativas da
    mesma venda (duplo-toque, retry) produzem sempre a mesma referência —
    é isso que faz a reserva atómica funcionar como idempotência. O prefixo
    `pos-` é o que separa os nossos documentos dos da app L'Açaí na mesma
    caixa API partilhada (spec §5.2)."""
    return "pos-%s-%s-%s" % (loja_id, sessao_id, venda_id)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _reservar(db, ext_ref: str, venda_id: str) -> bool:
    """A reserva atómica (passo 2). `True` se esta chamada ganhou a corrida;
    `False` se perdeu (já existe uma reserva para esta `ext_ref`) — é o
    índice único em `ext_ref` (db.py) que decide, não uma leitura antes de
    inserir."""
    try:
        await db[COLECOES["refs_fiscais"]].insert_one({
            "id": str(uuid.uuid4()),
            "ext_ref": ext_ref,
            "venda_id": venda_id,
            "criado_em": _agora(),
        })
        return True
    except DuplicateKeyError:
        return False


async def _libertar_reserva(db, ext_ref: str) -> None:
    """Remove a reserva desta `ext_ref` — chamado quando algo falha DEPOIS
    de reservar (nunca depois de o Vendus confirmar que emitiu, ver
    ConflitoDocumentoFiscal), para a próxima tentativa poder reservar de
    novo em vez de ficar presa atrás de uma reserva órfã."""
    await db[COLECOES["refs_fiscais"]].delete_one({"ext_ref": ext_ref})


async def _marcar_reserva_incerta(db, ext_ref: str) -> None:
    """Marca a reserva como incerta em vez de a libertar — ver
    VerificacaoFiscalIncerta. A diferença para `_libertar_reserva` é
    exactamente o ponto desta defesa: libertar convidava a tentativa
    seguinte a reservar de novo e emitir sem mais nenhuma pergunta; marcar
    incerta obriga-a a verificar primeiro (`_retomar_reserva_incerta`)."""
    await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref}, {"$set": {"incerta": True}}
    )


async def _reclamar_retoma(db, ext_ref: str) -> bool:
    """B1 (a re-revisão do núcleo fiscal): `_retomar_reserva_incerta` nunca
    RECLAMAVA a retoma — como a reserva já existe (não é um `insert_one`
    novo), `_reservar` deixava de decidir qualquer corrida. Duas ou mais
    tentativas concorrentes que encontrassem a MESMA reserva incerta
    verificavam TODAS, viam vazio, e EMITIAM todas — a rede oscila, a 1ª
    tentativa dá 503 e deixa a reserva incerta; a operadora, já com a rede
    boa, carrega duas vezes em FINALIZAR: sem esta reclamação, saem duas
    Faturas Simplificadas reais, cada uma com o seu ATCUD.

    A correcção é a MESMA técnica que I2 usa nos fechos de caixa
    (`caixa.py::fechar_caixa`/`registar_movimento`): uma escrita
    CONDICIONADA ao estado anterior (`em_retoma` ainda por ninguém — campo
    ausente OU `None`, o Mongo trata os dois da mesma forma num filtro de
    igualdade) e a confirmação de que foi mesmo ESTA chamada que a mudou —
    `matched_count == 1` decide a corrida, nunca uma leitura antes de
    escrever (essa leitura-depois-escreve era exactamente a falha: chegar a
    encontrar a reserva incerta já dava, em silêncio, o direito de agir
    sobre ela). Quem NÃO reclama (matched_count == 0, porque outra
    tentativa já lá chegou primeiro) cai no caminho de sempre de quem perde
    uma reserva — espera pelo documento do vencedor.

    **`em_retoma_desde` é o relógio DESTA reclamação, e não é decoração.**
    A reserva original pode ter horas (uma `incerta` das 20h retomada à
    meia-noite) e o `criado_em` dela continua a ser o de então — quem
    perguntar "há quanto tempo é que isto está a emitir?" pelo `criado_em`
    de uma reserva em retoma recebe 4 horas quando a resposta certa é "há
    12 segundos, e está a falar com o Vendus neste instante". Foi
    exactamente esse relógio trocado que deixou a rota de libertar apagar a
    reserva de uma emissão em voo e sair uma SEGUNDA Fatura Simplificada
    real da mesma venda (reproduzido em processo, sobre as rotas reais:
    `FS 2026/901` e `FS 2026/902`, o cliente com o talão de uma e a venda a
    apontar para a outra)."""
    resultado = await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref, "incerta": True, "em_retoma": None},
        {"$set": {"em_retoma": True, "em_retoma_desde": _agora()}},
    )
    return resultado.matched_count == 1


async def _limpar_incerta_resolvida(db, ext_ref: str) -> None:
    """'Um problema associado' da mesma revisão: hoje a marca `incerta`
    fica PARA SEMPRE, mesmo depois de a venda ficar emitida — a reserva
    nunca deixa de aparecer como 'presa' na listagem de gestão (ver a rota
    `/fiscal/reservas-presas`), muito depois de estar resolvida. Chamada
    só quando `_retomar_reserva_incerta` termina com um documento em mãos
    (encontrado pela verificação, ou emitido agora) — limpa `incerta` E
    `em_retoma` na mesma escrita, para o estado voltar a "sem ninguém a
    trabalhar nisto, e já não incerta".

    O carimbo `em_retoma_desde` limpa-se JUNTO com a marca que ele data: uma
    reserva sem `em_retoma` mas com o relógio de uma retoma antiga é um dado
    que só pode induzir em erro quem o leia a seguir (`_retoma_em_curso`)."""
    await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref},
        {"$set": {"incerta": False, "em_retoma": None, "em_retoma_desde": None}},
    )


async def _garante_venda_ainda_aberta(db, ext_ref: str, venda_id: str) -> None:
    """Depois de GANHAR a reserva e ANTES de chamar `emitir`: relê a venda E
    a sessão de caixa dela e, se alguma das duas já não estiver `aberta`,
    liberta a reserva e aborta — sem emitir.

    **As DUAS, e não só a venda.** A rota `finalizar` faz duas perguntas
    sobre o mesmo retrato velho — `_garante_aberta` (a venda) e
    `_garante_sessao_da_venda_aberta` (a sessão, o defeito I1) — e durante
    uma ronda inteira só a primeira era refeita aqui. A segunda tinha
    exactamente a mesma forma de defeito e a mesma janela (a validação toda
    corre entre o retrato e a reserva), com um estrago diferente: a caixa
    fechava no outro PC a meio da emissão e saía uma FS REAL depois do Z —
    ver `SessaoJaNaoAberta`, onde o cenário está por extenso.

    **A janela que isto fecha.** A verificação da reserva no
    `venda.py::cancelar_venda` estreitou a corrida entre CANCELAR e EMITIR,
    mas não a fechou: entre o `_garante_aberta` da rota `finalizar` e o
    `_reservar` corre a validação toda (sessão da venda, um `find_one` por
    cada tipo de pagamento, a conta e o register_id) — tudo `await`s. Um
    cancelamento que caísse INTEIRO nessa janela passava as DUAS perguntas
    pela reserva (ainda não existia nenhuma), respondia 200 "cancelada", e a
    seguir o `$set` incondicional do `_gravar_documento` escrevia `emitida`
    por cima. A operadora ouvia "conta cancelada", saía uma FS real com
    ATCUD, ela picava tudo outra vez e o cliente levava DUAS faturas.
    Reproduzido em processo, sobre as rotas reais, antes desta correcção.

    **A invariante que passa a valer:** um `200 cancelada` e uma Fatura
    Simplificada da mesma venda não podem coexistir. O cancelar só responde
    200 se a segunda pergunta (a que é feita DEPOIS da sua escrita) não
    encontrar reserva; e uma emissão bem sucedida nunca liberta a reserva —
    só a libertam os caminhos que NÃO emitiram (`_emitir_e_gravar` quando
    sabe que o Vendus não criou nada, e esta função). Logo, um 200 do
    cancelar significa ou que a reserva ainda não existia (e quem a criar a
    seguir cai nesta releitura), ou que já tinha sido libertada por quem não
    emitiu.

    **As ordens possíveis, por extenso** (verificadas uma a uma, não
    assumidas — e cada uma delas tem um teste):

    1. *O cancelamento escreve `cancelada` ANTES de esta tentativa
       reservar.* É o cenário reproduzido. A releitura vê `cancelada`,
       liberta a reserva e aborta: zero chamadas ao Vendus. A conta fica
       mesmo cancelada, como a operadora ouviu, e o `finalizar` devolve-lhe
       409 a dizer que a conta foi cancelada — nunca uma fatura silenciosa.

    2. *Esta tentativa reserva ANTES de o cancelamento perguntar.* A PRIMEIRA
       pergunta do `cancelar_venda` encontra a reserva e devolve 409 sem
       escrever nada. A venda continua `aberta`, esta emissão segue o seu
       caminho normal. A releitura vê `aberta` e deixa passar — correcto: a
       operadora foi informada de que o cancelamento NÃO aconteceu.

    3. *A reserva nasce ENTRE as duas perguntas do cancelamento* (depois da
       primeira, antes ou depois do `$set`). O cancelar escreve `cancelada`,
       a segunda pergunta encontra a reserva, a compensação repõe `aberta`
       (condicionada a `{"estado": "cancelada"}`) e devolve 409. Aqui a
       ordem entre a compensação e esta releitura decide, e as duas saídas
       são coerentes:
         - releitura DEPOIS da compensação → vê `aberta`, emite. A operadora
           ouviu 409 ("não foi cancelada"), e não foi.
         - releitura ANTES da compensação → vê `cancelada`, liberta a reserva
           e aborta sem emitir; a compensação a seguir repõe `aberta` e a
           conta fica utilizável outra vez (por cancelar ou por finalizar),
           sem FS nenhuma pelo meio.

    Não se lê aqui o estado que veio no `venda` recebido: esse é o retrato de
    antes da validação toda, e é precisamente ele que está velho — e a sessão
    lê-se pelo `sessao_id` DA RELEITURA, pela mesma razão."""
    actual = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if actual is None or actual.get("estado") != "aberta":
        # Ainda não se falou com o Vendus, por isso libertar é seguro E
        # necessário: sem isto ficava uma reserva órfã a trancar para sempre
        # uma conta que já ninguém pode emitir nem cancelar.
        await _libertar_reserva(db, ext_ref)
        raise VendaJaNaoAberta(
            "A venda %s já não está aberta (estado=%r) — o cancelamento entrou "
            "entre a validação e a reserva. A reserva %s foi libertada e NADA foi "
            "enviado ao Vendus." % (
                venda_id, (actual or {}).get("estado"), ext_ref,
            )
        )

    # A sessão DESTA venda (`actual["sessao_id"]`), nunca "há alguma sessão
    # aberta nesta caixa" — a caixa pode ter reaberto com uma sessão NOVA
    # entretanto, e essa não tem nada a ver com esta venda (o mesmo
    # raciocínio, e a mesma pergunta, de `_garante_sessao_da_venda_aberta`).
    # `.get(...)`, não `[...]`: uma venda sem `sessao_id` cai no mesmo
    # aborto, nunca num KeyError.
    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": actual.get("sessao_id")})
    if sessao is None or sessao.get("estado") != "aberta":
        await _libertar_reserva(db, ext_ref)
        raise SessaoJaNaoAberta(
            "A sessão de caixa %r da venda %s já não está aberta (estado=%r) — "
            "o fecho entrou entre a validação e a reserva. A reserva %s foi "
            "libertada e NADA foi enviado ao Vendus." % (
                actual.get("sessao_id"), venda_id,
                (sessao or {}).get("estado"), ext_ref,
            )
        )


async def _desfecho_de_quem_esperou_em_vao(db, ext_ref: str, venda_id: str) -> FiscalErro:
    """O erro a devolver a quem esperou pelo vencedor e ficou a saber que ele
    ABORTOU (a reserva desapareceu sem documento nenhum) — escolhido pelo
    estado da venda LIDO AGORA, não pelo que ela era quando esta tentativa
    começou.

    B2 (achado desta ronda): a mensagem descrevia sempre um estado que a
    conta já não tinha. O vencedor abortava por a venda ter sido cancelada
    (`VendaJaNaoAberta`), e o perdedor, que estava à espera do documento
    dele, esgotava o orçamento e respondia "tente novamente dentro de
    momentos" sobre uma venda já `cancelada` e sem reserva nenhuma — um
    conselho impossível de seguir. O módulo tem por regra não mandar tentar
    outra vez onde não se deve tentar; o simétrico também vale."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    estado = (venda or {}).get("estado")
    if estado == "cancelada":
        # Quem chama (a rota) traduz isto para o 409 de "a conta foi
        # cancelada e NÃO saiu fatura nenhuma" — que é exactamente o que
        # aconteceu, e o que a operadora precisa de ouvir.
        return VendaJaNaoAberta(
            "A venda %s foi cancelada enquanto esta tentativa esperava pelo "
            "documento (ext_ref=%s); a tentativa que tinha a reserva abortou "
            "sem emitir e libertou-a." % (venda_id, ext_ref)
        )
    if estado == "aberta":
        return EmissaoEmCurso(
            "A emissão que estava em curso nesta conta terminou sem emitir "
            "nada e libertou a reserva — NÃO saiu nenhuma Fatura "
            "Simplificada. A conta continua aberta: carregue outra vez em "
            "FINALIZAR."
        )
    return EmissaoEmCurso(
        "A emissão que estava em curso nesta conta libertou a reserva sem "
        "gravar documento nenhum, e a conta está agora no estado %r — não "
        "repita a operação às cegas: chame o gestor e confirme no Vendus o "
        "que saiu desta venda (ext_ref=%s)." % (estado, ext_ref)
    )


async def _esperar_documento_do_vencedor(
    db,
    ext_ref: str,
    esperar: Callable[[float], Awaitable[None]],
    tentativas: int,
    venda_id: str,
) -> Dict:
    """Quem perde a reserva chega aqui: OU o documento do vencedor já existe
    (devolve-o de imediato), OU ainda está a ser escrito (espera, com um
    orçamento limitado — nunca para sempre), OU o vencedor ABORTOU sem
    emitir, e aí não há nada por que esperar."""
    for _ in range(tentativas):
        # A RESERVA lê-se PRIMEIRO e o documento a seguir, nunca ao
        # contrário: entre as duas leituras o vencedor pode gravar o
        # documento, e nesta ordem quem espera vê-o na leitura seguinte.
        # Pela ordem inversa, uma reserva lida DEPOIS do documento podia
        # dar a conclusão errada — "ninguém emitiu" — sobre um documento
        # escrito entre as duas leituras.
        reserva = await db[COLECOES["refs_fiscais"]].find_one({"ext_ref": ext_ref})
        documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
        if documento is not None:
            return documento
        if reserva is None:
            # A reserva já não existia e continua a não haver documento:
            # quem a libertou não emitiu (uma emissão bem sucedida NUNCA
            # liberta a reserva — ver `_gravar_documento`). Esperar mais era
            # esperar por um documento que ninguém vai escrever.
            raise await _desfecho_de_quem_esperou_em_vao(db, ext_ref, venda_id)
        await esperar(_ESPERA_ENTRE_TENTATIVAS_S)
    raise EmissaoEmCurso(
        "Já existe uma reserva de emissão para esta venda (ext_ref=%s) mas "
        "o documento ainda não ficou disponível — tente novamente dentro de "
        "momentos. Se voltar a acontecer, a emissão ficou presa: o gestor "
        "vê-a (e resolve-a) na lista de reservas fiscais presas." % ext_ref
    )


async def _gravar_documento(db, ext_ref: str, venda: Dict, bruto: Dict) -> Dict:
    """Grava `bruto` (o que o Vendus devolveu — criado agora OU encontrado
    por uma verificação) em `fat_documentos` e marca a venda emitida —
    passo 3 da sequência (ver a docstring do módulo). Partilhado por todos
    os caminhos que chegam a um documento real: quem acabou de emitir, e
    quem retoma uma reserva incerta e encontra o documento já lá (ver
    `_retomar_reserva_incerta`).

    **O `$set` de `emitida` é INCONDICIONAL, e é para continuar a ser.**
    Percorridos os dois caminhos que chegam aqui:

    - *Caminho feliz* (reserva ganha agora): `_garante_venda_ainda_aberta`
      passou a reler a venda depois de ganhar a reserva, por isso um
      cancelamento anterior já não pode chegar até aqui. Resta a ordem em
      que o cancelamento escreve `cancelada` DEPOIS dessa releitura — e aí o
      incondicional é o que salva: quando chegamos a esta linha temos um
      documento fiscal REAL em mãos, e `emitida` é o estado verdadeiro desta
      venda, escreva o que escrever quem quer que lá tenha passado. Um `$set`
      condicionado a `{"estado": "aberta"}` deixava a venda `cancelada` com
      uma FS real e ATCUD entregues à AT — invisível no Z
      (`caixa_math.soma_vendas_dinheiro` só soma as `emitida`), que é o
      estrago exactamente ao contrário. E a operadora não fica enganada: a
      segunda pergunta do `cancelar_venda` encontra a reserva (uma emissão
      bem sucedida nunca a liberta) e devolve-lhe 409.
    - *Caminho da retoma* (reserva `incerta` retomada): enquanto existir
      reserva, TODAS as rotas de escrita da venda recusam (venda.py::
      `_garante_sem_emissao`) — o cancelamento incluído, e logo à primeira
      pergunta, sem escrever nada. Não há por isso nenhuma escrita
      concorrente que este `$set` possa pisar; e se houvesse, valia o mesmo
      argumento de cima: com o documento fiscal em mãos, `emitida` é a
      verdade.

    Conclusão: nenhum dos dois caminhos precisa de condição, e pô-la seria
    trocar um estrago improvável por outro pior."""
    documento = {
        "id": str(uuid.uuid4()),
        "vendus_document_id": bruto.get("id"),
        "atcud": bruto.get("atcud"),
        "numero": bruto.get("numero"),
        "total": bruto.get("total"),
        "modo": bruto.get("modo"),
        "ext_ref": ext_ref,
        "venda_id": venda["id"],
        "loja_id": venda["loja_id"],
        "emitido_em": _agora(),
    }
    try:
        await db[COLECOES["documentos"]].insert_one(dict(documento))
    except DuplicateKeyError:
        existente = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
        if existente is not None:
            # Uma tentativa anterior desta MESMA venda já gravou o
            # documento (ex.: um retry depois de a resposta se ter
            # perdido) — reutiliza-o, sem inventar um segundo.
            documento = existente
        else:
            # O Vendus DEVOLVEU um documento (`bruto`) mas gravá-lo colide
            # com outro já gravado para uma ext_ref DIFERENTE (mesmo
            # vendus_document_id ou atcud) — ver ConflitoDocumentoFiscal: a
            # reserva NÃO se liberta, porque o documento fiscal existe
            # mesmo.
            raise ConflitoDocumentoFiscal(
                "O Vendus devolveu um documento (id=%r, atcud=%r) que colide "
                "com outro já gravado localmente para uma referência "
                "DIFERENTE — a reserva de %s foi mantida (o documento fiscal "
                "existe) e isto precisa de investigação manual." % (
                    bruto.get("id"), bruto.get("atcud"), ext_ref,
                )
            )

    await _ligar_venda_ao_documento(db, ext_ref, venda["id"], documento)
    return documento


async def _ligar_venda_ao_documento(
    db, ext_ref: str, venda_id: str, documento: Dict
) -> None:
    """A segunda metade de `_gravar_documento`: marca a venda `emitida` e
    ligada a este documento, e carimba a reserva com ele.

    À parte porque tem um SEGUNDO chamador desde esta ronda — a rota de
    RECONCILIAR (`reconciliar_reserva_presa`), para o caso em que o
    documento já está gravado em `fat_documentos` mas a venda ficou para
    trás em `aberta` (o processo morreu entre as duas escritas). Ter uma só
    função em vez de duas é o que garante que a marca da reserva e a ordem
    das escritas continuam a ser as mesmas nos dois caminhos."""
    await db[COLECOES["vendas"]].update_one(
        {"id": venda_id},
        {"$set": {"estado": "emitida", "documento_id": documento["id"]}},
    )

    # A reserva fica marcada com o documento que dela saiu. Não é uma defesa
    # fiscal — é o que torna POSSÍVEL perguntar pelas reservas PRESAS sem
    # varrer tudo: `listar_reservas_presas` filtra por `{"documento_id":
    # None}` (no Mongo, o campo ausente OU a `null`). Sem esta marca, a
    # listagem tinha de ler a colecção inteira e cruzar cada reserva com a
    # sua venda; e como a colecção nunca encolhe (~365 mil documentos por
    # ano — a reserva de uma venda emitida fica lá para sempre, é ela que
    # sustenta a idempotência), um `.to_list(1000)` devolvia as 1000 MAIS
    # ANTIGAS, todas resolvidas, e a reserva presa desta noite não aparecia
    # a ninguém.
    #
    # DEPOIS da venda já estar `emitida`, nunca antes: se o processo morrer
    # entre as duas escritas, o pior que fica é uma reserva por marcar cuja
    # venda já está emitida — e essa a listagem descarta na junção pelo
    # estado da venda, que é a fonte de verdade. Pela ordem contrária ficava
    # o inverso, muito pior: uma reserva marcada como resolvida a esconder
    # uma venda presa em `aberta` com um documento fiscal real.
    #
    # E envolvida em try/except de propósito: uma emissão que JÁ correu bem
    # (documento gravado, venda emitida) não pode virar um 500 no ecrã do
    # balcão — que mandava a operadora repetir — por causa de um soluço do
    # Mongo numa marca de conveniência. As reservas de antes deste campo
    # existir, e as que este `except` deixar por marcar, continuam a aparecer
    # na listagem e a ser filtradas pela junção: não é preciso migração
    # nenhuma.
    try:
        await db[COLECOES["refs_fiscais"]].update_one(
            {"ext_ref": ext_ref}, {"$set": {"documento_id": documento["id"]}}
        )
    except Exception as e:  # noqa: BLE001 — marca de conveniência, nunca uma garantia
        logger.warning(
            "[faturacao] não foi possível marcar a reserva %s com o documento %s: %s",
            ext_ref, documento["id"], e,
        )


async def _emitir_e_gravar(
    db,
    ext_ref: str,
    venda: Dict,
    emitir: Callable[[str], Awaitable[Dict]],
    verificar: Callable[[str], Awaitable[Optional[Dict]]],
    dados_pagamento: Optional[Dict] = None,
) -> Dict:
    """Chama `emitir`, com o único fallback permitido (ver a docstring do
    módulo): um timeout/indisponibilidade tenta UMA verificação exacta.

    Há três desfechos possíveis depois de um timeout na emissão, cada um
    com uma consequência DIFERENTE sobre a reserva — é aqui que vivia o
    defeito C1 (a revisão do núcleo fiscal): um `except Exception` genérico
    à volta de tudo libertava a reserva mesmo quando a PRÓPRIA verificação
    rebentava, que é precisamente o caso em que nada se sabe sobre se o
    Vendus chegou a emitir.

    1. A verificação encontra o documento → usa-o, nunca uma segunda emissão.
    2. A verificação corre bem e não encontra nada → o Vendus não chegou a
       processar o pedido original; liberta-se a reserva, propaga-se o erro
       original (o POS mostra "tente outra vez").
    3. A PRÓPRIA verificação falha → não se sabe nada; a reserva NÃO se
       liberta, fica marcada incerta (ver VerificacaoFiscalIncerta).

    `dados_pagamento` (C2, achado na mesma revisão): `pagamentos`/
    `cliente_nif`, se vierem, só se gravam AQUI — depois de esta chamada já
    ter GANHO a reserva e estar mesmo prestes a tentar emitir. É essa a
    correcção: a rota `finalizar` costumava gravar isto incondicionalmente
    ANTES de tocar na reserva, e uma tentativa que perdesse a corrida
    gravava à mesma o que a operadora tinha escolhido, mesmo sem ter sido
    ela a emitir (a idempotência escondia o erro: as duas respostas eram
    200, mas o tipo de pagamento gravado podia ser o da tentativa errada —
    o Z não bate e ninguém percebe porquê)."""
    if dados_pagamento is not None:
        await db[COLECOES["vendas"]].update_one(
            {"id": venda["id"]}, {"$set": dados_pagamento}
        )
    try:
        bruto = await emitir(ext_ref)
    except VendusIndisponivel as erro_emissao:
        try:
            encontrado = await verificar(ext_ref)
        except Exception as erro_verificacao:
            await _marcar_reserva_incerta(db, ext_ref)
            raise VerificacaoFiscalIncerta(
                "Timeout na emissão (ext_ref=%s) e a própria verificação por "
                "referência externa também falhou (%s) — não é seguro "
                "concluir nada sobre se o Vendus criou o documento. A "
                "reserva foi mantida, marcada incerta; confirme no Vendus "
                "antes de repetir." % (ext_ref, erro_verificacao)
            ) from erro_emissao
        if encontrado is None:
            await _libertar_reserva(db, ext_ref)
            raise erro_emissao
        bruto = encontrado
    except Exception:
        # Qualquer outra falha (4xx, validação nossa, RegisterIdInvalido,
        # VendusModoInvalido, VendusRateLimitado...) significa que sabemos
        # que o Vendus NÃO criou nada — a reserva liberta-se, para a
        # próxima tentativa (correcção de dados, nova tentativa manual)
        # poder reservar de novo.
        await _libertar_reserva(db, ext_ref)
        raise

    return await _gravar_documento(db, ext_ref, venda, bruto)


async def _retomar_reserva_incerta(
    db,
    ext_ref: str,
    venda: Dict,
    emitir: Callable[[str], Awaitable[Dict]],
    verificar: Callable[[str], Awaitable[Optional[Dict]]],
    dados_pagamento: Optional[Dict] = None,
    esperar: Optional[Callable[[float], Awaitable[None]]] = None,
    tentativas_espera: int = _TENTATIVAS_ESPERA_VENCEDOR,
) -> Dict:
    """Quem encontra uma reserva marcada `incerta` (a tentativa anterior
    teve um timeout na emissão E a verificação também falhou — nunca se
    soube se o Vendus criou o documento) é OBRIGADO a verificar antes de
    poder fazer seja o que for: nunca herda o direito de emitir só por ter
    encontrado a reserva, porque essa reserva pode já corresponder a um
    documento fiscal real do outro lado.

    B1 (a re-revisão do núcleo fiscal): encontrar a reserva incerta NÃO dá,
    por si só, o direito de agir sobre ela — isso é exactamente o defeito
    que esta versão corrige. `_reclamar_retoma` decide a corrida com uma
    escrita condicional (ver a sua docstring); só quem reclama chega a
    verificar/emitir. Quem perde a reclamação cai no MESMO caminho de
    sempre de quem perde uma reserva nova — espera pelo documento do
    vencedor, nunca verifica/emite em paralelo com quem já reclamou.

    Se a verificação ENCONTRAR o documento, é da tentativa ANTERIOR (a que
    ganhou a reserva) que ele saiu — os `dados_pagamento` DESTA tentativa
    nunca se gravam nesse caso (ver C2 na docstring de `_emitir_e_gravar`).

    Resolvida (documento encontrado ou emitido), `incerta` limpa-se — nunca
    fica marcada para sempre numa venda já emitida (ver
    `_limpar_incerta_resolvida`). Continuando incerta (novo timeout e nova
    falha da verificação), só a marca de RETOMA se limpa — `incerta`
    mantém-se True, tal como já estava, para a tentativa seguinte também
    ser obrigada a verificar primeiro."""
    esperar_efectivo = esperar if esperar is not None else asyncio.sleep
    if not await _reclamar_retoma(db, ext_ref):
        return await _esperar_documento_do_vencedor(
            db, ext_ref, esperar_efectivo, tentativas_espera, venda["id"]
        )

    resolvida = False
    try:
        try:
            encontrado = await verificar(ext_ref)
        except Exception as erro_verificacao:
            raise VerificacaoFiscalIncerta(
                "A reserva desta venda (ext_ref=%s) continua incerta — a "
                "verificação por referência externa voltou a falhar (%s). Não "
                "se emite às cegas; confirme no Vendus." % (ext_ref, erro_verificacao)
            ) from erro_verificacao
        if encontrado is not None:
            documento = await _gravar_documento(db, ext_ref, venda, encontrado)
        else:
            # A verificação correu bem e não encontrou nada: só agora é
            # seguro tentar emitir — com a MESMA rede de segurança de
            # sempre (se este timeout também falhar, a reserva volta a
            # ficar incerta, ver _emitir_e_gravar/_marcar_reserva_incerta),
            # e É esta tentativa que vai emitir de facto, por isso É o seu
            # dados_pagamento que deve gravar-se.
            documento = await _emitir_e_gravar(db, ext_ref, venda, emitir, verificar, dados_pagamento)
        resolvida = True
        return documento
    finally:
        # SEMPRE limpa a marca de retoma, em QUALQUER desfecho (resolvida,
        # continua incerta, ou até um erro que a própria _emitir_e_gravar
        # já tenha tratado à sua maneira) — sem isto, esta reclamação
        # ficava presa para sempre e nenhuma tentativa futura conseguia
        # voltar a reclamar: um impasse pior do que o defeito original.
        if resolvida:
            await _limpar_incerta_resolvida(db, ext_ref)
        else:
            await db[COLECOES["refs_fiscais"]].update_one(
                {"ext_ref": ext_ref},
                {"$set": {"em_retoma": None, "em_retoma_desde": None}},
            )


async def finalizar_venda(
    db,
    venda: Dict,
    emitir: Callable[[str], Awaitable[Dict]],
    verificar: Callable[[str], Awaitable[Optional[Dict]]],
    esperar: Optional[Callable[[float], Awaitable[None]]] = None,
    tentativas_espera: int = _TENTATIVAS_ESPERA_VENCEDOR,
    dados_pagamento: Optional[Dict] = None,
) -> Dict:
    """O núcleo da Task 3 — a sequência das quatro defesas (ver a docstring
    do módulo). `emitir(ext_ref)` e `verificar(ext_ref)` já vêm resolvidos
    para ESTA venda (linhas, pagamentos, cliente, register_id — tudo isso é
    responsabilidade de quem chama, normalmente a rota `finalizar` mais
    abaixo); este núcleo só sabe de reserva, emissão-ou-verificação, e
    gravação — é o que o torna testável sem tocar em rede nem em threads.

    `dados_pagamento` (opcional: `{"pagamentos": [...], "cliente_nif": ...}`)
    só se grava na venda no ramo que realmente tenta emitir (ver C2) — nunca
    em quem só espera pelo vencedor."""
    esperar = esperar if esperar is not None else asyncio.sleep
    ext_ref = ext_ref_determinista(venda["loja_id"], venda["sessao_id"], venda["id"])

    ganhou = await _reservar(db, ext_ref, venda["id"])
    if ganhou:
        # Ganhar a reserva não chega: o estado da venda que temos em mãos é o
        # de ANTES da validação toda (ver `_garante_venda_ainda_aberta`, que
        # percorre as ordens possíveis uma a uma).
        await _garante_venda_ainda_aberta(db, ext_ref, venda["id"])
        return await _emitir_e_gravar(db, ext_ref, venda, emitir, verificar, dados_pagamento)

    # Perdeu a reserva: OU alguém está mesmo a meio da emissão (espera pelo
    # documento, comportamento de sempre — NUNCA grava dados_pagamento,
    # porque não foi esta tentativa que emitiu), OU a reserva existente
    # ficou `incerta` numa tentativa anterior (C1) — nesse caso é OBRIGADA a
    # verificar antes de poder fazer seja o que for.
    reserva = await db[COLECOES["refs_fiscais"]].find_one({"ext_ref": ext_ref})
    if reserva is not None and reserva.get("incerta"):
        return await _retomar_reserva_incerta(
            db, ext_ref, venda, emitir, verificar, dados_pagamento,
            esperar=esperar, tentativas_espera=tentativas_espera,
        )
    return await _esperar_documento_do_vencedor(
        db, ext_ref, esperar, tentativas_espera, venda["id"]
    )


# --- Verificação de leitura contra o Vendus (Task 4, prometida no Plano 2A) ---
#
# O esperado do fecho (faturacao/caixa.py) calcula-se SEMPRE das nossas
# vendas (regra 1 do dono) — isto é só uma segunda opinião de leitura, nunca
# a fonte de verdade. Bate certo → não diz nada. Não bate → avisa, mas
# NUNCA bloqueia o fecho (regra 3). Não conseguiu ler tudo → diz que não
# conseguiu verificar, e nunca inventa um número que a operadora vá usar
# para justificar dinheiro.


def _datas_da_janela(sessao: Dict) -> List[str]:
    """Os dias (Europe/Lisbon, formato YYYY-MM-DD) a consultar — da abertura
    da sessão até agora, inclusive. Midnight-safe: uma sessão que atravessa
    a meia-noite não perde a parte de ontem (mesmo raciocínio da Pizzaria,
    `server.py::close_table`, `dedup_dates`) — sem isto, fechar às 00:10
    depois de abrir às 23h só consultaria hoje, e as vendas de ontem à noite
    nunca apareceriam na verificação."""
    agora = datetime.now(_LISBOA).date()
    try:
        inicio = datetime.fromisoformat(sessao["aberta_em"]).astimezone(_LISBOA).date()
    except (KeyError, TypeError, ValueError):
        inicio = agora
    datas = []
    dia = inicio
    while dia <= agora:
        datas.append(dia.isoformat())
        dia += timedelta(days=1)
    return datas


def _reconciliar_vendas_dinheiro(
    vendas_dinheiro_local: float,
    documentos_vendus: List[Dict],
    prefixo_ext_ref: str,
    ids_pagamento_dinheiro: Set[str],
) -> Optional[Dict]:
    """Núcleo PURO da reconciliação (sem I/O, testável sem MockTransport):
    soma, dos documentos lidos, só os que são NOSSOS desta sessão
    (`external_reference` com o prefixo `pos-{loja}-{sessao}-`) e não estão
    ANULADOS, e dentro deles só os pagamentos cujo `id` (no Vendus) é de um
    tipo local marcado `tipo_fiscal == 'NU'`. Devolve `None` se bater certo
    com `vendas_dinheiro_local`; um aviso claro se não bater."""
    relevantes = [
        d for d in documentos_vendus
        if str(d.get("external_reference") or "").startswith(prefixo_ext_ref)
        and d.get("status") != "A"
    ]
    soma_vendus = 0.0
    for documento in relevantes:
        for pagamento in documento.get("payments") or []:
            if str(pagamento.get("id")) in ids_pagamento_dinheiro:
                soma_vendus += float(pagamento.get("amount") or 0)
    soma_vendus = round(soma_vendus, 2)

    if soma_vendus == round(vendas_dinheiro_local, 2):
        return None
    return {
        "aviso": (
            "O Vendus regista %.2f € em dinheiro nesta sessão; as nossas "
            "vendas somam %.2f €." % (soma_vendus, vendas_dinheiro_local)
        )
    }


async def verificar_vendas_dinheiro_no_vendus(
    db, sessao: Dict, vendas_dinheiro_local: float
) -> Optional[Dict]:
    """A leitura de reconciliação em si (I/O): configuração, janela de dias,
    paginação completa (nunca a armadilha per_page sem paginar) e a
    comparação pura acima. QUALQUER falha — configuração em falta, rede,
    paginação truncada — devolve `{"nao_verificado": ...}` em vez de deixar
    rebentar ou de inventar um número (regra 3 do dono: o fecho nunca pode
    ficar bloqueado, nem mentir, por causa disto)."""
    try:
        register_id = _register_id_configurado()
        if register_id is None:
            return {"nao_verificado": "VENDUS_REGISTER_ID não está configurado."}
        conta = obter_conta(_nif_configurado())
        if conta is None:
            return {"nao_verificado": "Conta Vendus não configurada."}

        tipos_dinheiro = await db[COLECOES["tipos_pagamento"]].find(
            {"tipo_fiscal": "NU"}
        ).to_list(200)
        ids_dinheiro = {
            str(t["vendus_payment_method_id"])
            for t in tipos_dinheiro if t.get("vendus_payment_method_id")
        }

        documentos: List[Dict] = []
        with ClienteEmissaoVendus(conta.chave) as cliente:
            for data in _datas_da_janela(sessao):
                documentos.extend(
                    await asyncio.to_thread(cliente.listar_documentos_por_dia, data, register_id)
                )

        prefixo = "pos-%s-%s-" % (sessao["loja_id"], sessao["id"])
        return _reconciliar_vendas_dinheiro(vendas_dinheiro_local, documentos, prefixo, ids_dinheiro)
    except Exception as e:  # noqa: BLE001 — nunca pode propagar e bloquear o fecho
        logger.warning("[faturacao] verificação de fecho contra o Vendus falhou: %s", e)
        return {"nao_verificado": "Não foi possível confirmar contra o Vendus: %s" % e}


# --- A rota: liga o núcleo acima ao Vendus real e à conta do balcão --------


class PagamentoEntrada(BaseModel):
    tipo_pagamento_id: str = Field(min_length=1)
    valor: float = Field(gt=0, allow_inf_nan=False)

    @field_validator("valor")
    @classmethod
    def _valida_valor(cls, v):
        if _tem_mais_de_2_casas_decimais(v):
            raise ValueError(
                "O valor %s tem mais de 2 casas decimais — a fatura recusa-o "
                "para não perder um cêntimo no arredondamento." % v
            )
        return v


class PedidoFinalizarVenda(BaseModel):
    pagamentos: List[PagamentoEntrada] = Field(min_length=1)
    # Opcional: sem NIF, o Vendus assume Consumidor Final (ver
    # vendus/emissao.py). Normalizado só a dígitos — "123 456 789" e
    # "123456789" têm de ser a mesma coisa para o Vendus.
    nif: Optional[str] = None

    @field_validator("nif")
    @classmethod
    def _valida_nif(cls, v):
        if v is None or not v.strip():
            return None
        digitos = "".join(c for c in v if c.isdigit())
        if len(digitos) != 9:
            raise ValueError("O NIF tem de ter 9 dígitos.")
        return digitos


def _resposta_documento(documento: Dict) -> Dict:
    return {
        "id": documento.get("id"),
        "vendus_document_id": documento.get("vendus_document_id"),
        "numero": documento.get("numero"),
        "atcud": documento.get("atcud"),
        "total": documento.get("total"),
        # O ecrã tem de poder avisar se saiu em modo 'tests' (sem valor
        # fiscal) — ver a docstring de VendusModoInvalido em vendus/emissao.py.
        "modo": documento.get("modo"),
    }


async def _garante_sessao_da_venda_aberta(db, venda: Dict) -> None:
    """I1 (a revisão do núcleo fiscal): `finalizar` verificava o estado da
    VENDA (`_garante_aberta`) mas nunca o da SESSÃO de caixa a que ela
    pertence. Uma venda aberta antes do fecho mas só finalizada depois (o
    ecrã ficou aberto, a operadora esqueceu-se) emitia à mesma — o dinheiro
    entrava na gaveta sem pertencer a fecho nenhum, nem ao de hoje (já
    fechado) nem ao de amanhã (só vai contar as vendas da PRÓXIMA sessão).

    Confirma especificamente a sessão DESTA venda (`venda["sessao_id"]`) —
    nunca "há alguma sessão aberta nesta caixa", que seria a pergunta
    errada: uma caixa pode ter reaberto com uma sessão NOVA entretanto, e
    essa sessão não tem nada a ver com esta venda antiga.

    Pequena correcção da re-revisão do núcleo fiscal: `venda.get(...)`, não
    `venda[...]` — uma venda sem `sessao_id` (dados corrompidos, uma
    migração incompleta) tem de cair no MESMO 409 de "sessão não aberta",
    nunca num KeyError/500: `find_one({"id": None})` simplesmente não
    encontra nenhuma sessão, e o `if not sessao` já trata isso."""
    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": venda.get("sessao_id")})
    if not sessao or sessao.get("estado") != "aberta":
        raise HTTPException(status_code=409, detail=_MSG_SESSAO_NAO_ABERTA)


@router.post("/pos/venda/{venda_id}/finalizar")
async def finalizar(
    venda_id: str, dados: PedidoFinalizarVenda, operador: Dict = Depends(operador_atual)
) -> dict:
    """Emite a Fatura Simplificada real desta venda (spec §7.4 "Finalizar").

    A validação de configuração (conta Vendus, register_id) e de dados
    (linhas presentes, total positivo, pagamentos a bater com o total, tipos
    de pagamento válidos e mapeados no Vendus) corre TODA antes de tocar na
    reserva atómica — um erro de configuração ou de dados não pode gastar
    uma tentativa de emissão nem confundir o operador com um 502 do Vendus
    quando o problema é, por exemplo, um pagamento mal somado.

    I3 (a revisão do núcleo fiscal): sem o índice único de
    `fat_refs_fiscais.ext_ref` confirmado no arranque (`faturacao.
    arrancar`), a reserva atómica (passo 2 da sequência) não tem NENHUMA
    garantia real por trás — o duplo-toque deixava de ter defesa nenhuma,
    em silêncio. Por isso esta é a PRIMEIRA verificação da rota, antes de
    tocar em qualquer venda."""
    if not indice_idempotencia_confirmado():
        raise HTTPException(status_code=503, detail=_MSG_INDICE_IDEMPOTENCIA_EM_FALTA)
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sessao_da_venda_aberta(db, venda)
    if not venda.get("linhas"):
        raise HTTPException(status_code=422, detail=_MSG_LINHAS_VAZIAS)

    totais = _totais(venda)
    if totais["total"] <= 0:
        raise HTTPException(status_code=422, detail=_MSG_TOTAL_NAO_POSITIVO)

    soma_pagamentos = round(sum(p.valor for p in dados.pagamentos), 2)
    if soma_pagamentos != totais["total"]:
        raise HTTPException(
            status_code=422,
            detail=(
                "A soma dos pagamentos (%.2f €) não bate com o total da "
                "venda (%.2f €)." % (soma_pagamentos, totais["total"])
            ),
        )

    pagamentos_venda: List[Dict] = []
    pagamentos_vendus: List[Dict] = []
    for p in dados.pagamentos:
        tipo = await db[COLECOES["tipos_pagamento"]].find_one({"id": p.tipo_pagamento_id})
        if not tipo or not tipo.get("ativo", True):
            raise HTTPException(status_code=422, detail=_MSG_TIPO_PAGAMENTO_INEXISTENTE)
        if not tipo.get("vendus_payment_method_id"):
            raise HTTPException(status_code=422, detail=_MSG_TIPO_PAGAMENTO_SEM_VENDUS)
        # Snapshot do tipo (nome, tipo_fiscal) — o mesmo raciocínio de
        # venda.py::_produto_snapshot: o fecho de caixa (Task 4) lê
        # `tipo_fiscal` directamente daqui para separar dinheiro de
        # multibanco, sem precisar de reconsultar fat_tipos_pagamento (que
        # podia entretanto ter mudado) para reconstruir o Z de um dia antigo.
        pagamentos_venda.append({
            "tipo_pagamento_id": tipo["id"],
            "nome": tipo.get("nome"),
            "tipo_fiscal": tipo.get("tipo_fiscal"),
            "valor": p.valor,
        })
        pagamentos_vendus.append({"id": tipo["vendus_payment_method_id"], "amount": p.valor})

    conta = obter_conta(_nif_configurado())
    if conta is None:
        raise HTTPException(
            status_code=502,
            detail=(
                "Conta Vendus não configurada para o NIF %s. Defina "
                "VENDUS_ACCOUNTS no .env — sem isto não há como emitir." % _nif_configurado()
            ),
        )
    register_id = _register_id_configurado()
    if register_id is None:
        raise HTTPException(
            status_code=502,
            detail="VENDUS_REGISTER_ID não está configurado — sem isto não há como emitir.",
        )

    # O que a operadora escolheu (pagamentos e NIF) só se grava depois de
    # GANHAR a reserva — nunca aqui, incondicionalmente, ANTES de a tentar
    # (defeito C2 da revisão: uma tentativa que perdesse a corrida gravava à
    # mesma o que tinha escolhido, mesmo sem ter sido ela a emitir, e a
    # idempotência escondia o erro — as duas respostas eram 200, mas o Z não
    # batia com o que saiu no papel). `finalizar_venda` só grava isto no
    # ramo que realmente emite.
    dados_pagamento = {"pagamentos": pagamentos_venda, "cliente_nif": dados.nif}

    itens = _itens_vendus(venda)
    cliente_payload = {"fiscal_id": dados.nif} if dados.nif else None

    with ClienteEmissaoVendus(conta.chave) as cliente_vendus:

        async def emitir(ref: str) -> Dict:
            return await asyncio.to_thread(
                cliente_vendus.criar_fatura_simplificada,
                linhas=itens,
                pagamentos=pagamentos_vendus,
                cliente=cliente_payload,
                external_reference=ref,
                register_id=register_id,
            )

        async def verificar(ref: str) -> Optional[Dict]:
            return await asyncio.to_thread(
                cliente_vendus.procurar_por_referencia_externa, ref, register_id
            )

        try:
            documento = await finalizar_venda(
                db, venda, emitir, verificar, dados_pagamento=dados_pagamento
            )
        except VendaJaNaoAberta:
            # A conta foi cancelada dentro da janela de validação (ver
            # `_garante_venda_ainda_aberta`). O 409 é para a operadora, com
            # a única coisa que ela precisa de saber: não saiu fatura
            # nenhuma. O detalhe técnico (ext_ref, estado) fica no log, não
            # no ecrã do balcão.
            logger.warning("[faturacao] finalizar abortado: venda %s já não está aberta", venda_id)
            raise HTTPException(status_code=409, detail=_MSG_VENDA_CANCELADA_ENTRETANTO)
        except SessaoJaNaoAberta:
            # A caixa foi fechada dentro da janela de validação, no outro PC
            # (ver `SessaoJaNaoAberta`). Também aqui o que a operadora precisa
            # de saber é só isto: não saiu fatura nenhuma, e esta conta já não
            # pode ser faturada neste turno.
            logger.warning(
                "[faturacao] finalizar abortado: a sessão de caixa da venda %s "
                "foi fechada durante a emissão", venda_id,
            )
            raise HTTPException(status_code=409, detail=_MSG_SESSAO_FECHADA_ENTRETANTO)
        except EmissaoEmCurso as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ConflitoDocumentoFiscal as e:
            raise HTTPException(status_code=500, detail=str(e))
        except VerificacaoFiscalIncerta as e:
            # Não se sabe se o Vendus emitiu (timeout + verificação também
            # falhou) — nunca um "tente outra vez" genérico, que convidaria
            # a operadora a repetir às cegas (ver a docstring da excepção).
            raise HTTPException(status_code=503, detail=str(e))
        except VendusErro as e:
            raise HTTPException(status_code=502, detail="Vendus indisponível: %s" % e)

    venda_actualizada = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    resposta = _venda_publica(venda_actualizada)
    resposta["pagamentos"] = venda_actualizada.get("pagamentos", [])
    resposta["cliente_nif"] = venda_actualizada.get("cliente_nif")
    resposta["documento"] = _resposta_documento(documento)
    return resposta




# --- Gestão das reservas PRESAS -----------------------------------------------
#
# Uma reserva sobrevivente não tem NENHUMA saída pelo POS, e nem todas são
# `incerta`:
#
# - **incerta** — a emissão deu timeout E a verificação por referência externa
#   também falhou (`VerificacaoFiscalIncerta`). É a única que estava marcada.
# - **em retoma** — alguém reclamou a retoma dessa reserva incerta
#   (`_reclamar_retoma`) e está a verificar/emitir agora; se o processo morrer
#   a meio, a marca fica lá presa.
# - **órfã** — o processo morreu entre o `_reservar` e o `_gravar_documento`
#   (restart, deploy, OOM), ou o caminho `ConflitoDocumentoFiscal` manteve a
#   reserva DE PROPÓSITO. Nunca ninguém chegou ao `_marcar_reserva_incerta`,
#   por isso não tem marca nenhuma.
#
# Nas duas últimas a conta ficava SEM SAÍDA: cancelar → 409 para sempre (a
# venda tem reserva); finalizar → `_reservar` perde por DuplicateKeyError, a
# reserva não é `incerta`, cai no `_esperar_documento_do_vencedor`, não há
# documento nenhum → `EmissaoEmCurso` → 409 para sempre. E a mensagem mandava
# chamar o gestor para uma listagem que filtrava `{"incerta": True}` e não a
# mostrava. Antes destas defesas a operadora pelo menos desbloqueava o balcão
# a cancelar (mal, mas desbloqueava); agora o balcão ficava preso numa sexta à
# noite. Daí as duas rotas abaixo: uma que mostra TODAS as presas e diz porquê
# e há quanto tempo, e uma que as LIBERTA, com o gestor a confirmar primeiro
# no Vendus que não saiu documento nenhum.


# Quanto tempo pode uma emissão normal demorar, no pior caso, antes de se
# poder sequer suspeitar que a reserva ficou órfã: o cliente do Vendus faz
# até 3 tentativas com 30 s de timeout cada e esperas até 30 s entre elas
# (vendus/emissao.py: `_MAX_TENTATIVAS`, `_ESPERA_MAXIMA_S`) — e o mesmo
# orçamento outra vez para o GET de verificação que se segue a um timeout.
# 300 s cobre esse pior caso com folga. Serve para duas coisas, e para mais
# nenhuma: rotular na listagem uma reserva recente como emissão A DECORRER
# (não como órfã), e RECUSAR libertá-la — libertar a reserva de uma emissão
# que está mesmo a acontecer é autorizar uma segunda fatura da mesma venda.
_SEGUNDOS_DE_EMISSAO_NORMAL = 300.0

# O MESMO raciocínio para uma RETOMA, que é mais comprida por natureza: uma
# retoma faz até três chamadas ao Vendus em sequência — a verificação
# obrigatória (`_retomar_reserva_incerta` nunca emite sem verificar
# primeiro), a emissão, e a verificação que se segue a um timeout dessa
# emissão. Cada uma delas custa, no pior caso, 3 tentativas × 30 s de
# timeout + 2 esperas de 30 s (vendus/emissao.py: `_MAX_TENTATIVAS`,
# `_ESPERA_MAXIMA_S`) = 150 s. Três × 150 s = 450 s.
#
# E o critério de saída, que é o que faltava: uma retoma VIVA nunca dura
# mais do que isto, e uma que termine limpa SEMPRE a marca (o `finally` de
# `_retomar_reserva_incerta`, em qualquer desfecho). Logo, uma reclamação
# mais velha do que 450 s só pode ser de um processo que morreu a meio
# (restart, deploy, OOM) — essa não tranca nada: volta a poder ser
# libertada, e é para isso que a marca leva relógio (`em_retoma_desde`).
_SEGUNDOS_DE_RETOMA_NORMAL = 450.0

# As presas são sempre um punhado (é o filtro `documento_id: None` que as
# separa das ~365 mil resolvidas de um ano). O limite existe só para uma
# listagem de gestão nunca poder puxar a colecção inteira para memória se
# alguma coisa correr muito mal.
_LIMITE_RESERVAS_PRESAS = 500

_MSG_LIBERTAR_SEM_RESERVA = (
    "Não existe nenhuma reserva de emissão para esta venda — não há nada "
    "para libertar."
)
_MSG_LIBERTAR_SEM_EXT_REF = (
    "Esta reserva não tem referência externa (`ext_ref`) — está estragada, e "
    "sem ela não há sequer o que procurar no Vendus. Não se liberta por aqui: "
    "chame quem trata do sistema."
)
_MSG_LIBERTAR_SEM_CONFIRMACAO = (
    "Antes de libertar esta reserva tem de abrir o Vendus, procurar a "
    "referência externa %s e confirmar que NÃO existe lá nenhum documento "
    "para esta venda. Libertar a reserva de uma fatura que SAIU é autorizar "
    "uma SEGUNDA Fatura Simplificada da mesma venda — duas faturas do mesmo "
    "açaí entregues à AT, que só se corrigem com uma nota de crédito. Repita "
    "o pedido com confirmado_no_vendus=true só depois de o ter visto com os "
    "próprios olhos."
)
_MSG_LIBERTAR_COM_DOCUMENTO = (
    "Esta venda JÁ tem um documento fiscal gravado (nº %s, ATCUD %s) — a "
    "reserva NÃO se liberta. É ela que impede uma segunda emissão da mesma "
    "venda; o que estiver errado nesta conta corrige-se com uma nota de "
    "crédito, nunca libertando a reserva."
)
_MSG_LIBERTAR_VENDA_EMITIDA = (
    "Esta venda já está marcada como emitida — a reserva não está presa, "
    "está a fazer o trabalho dela (impedir uma segunda emissão da mesma "
    "venda) e não se liberta."
)
_MSG_LIBERTAR_RESERVA_RECENTE = (
    "Esta reserva foi criada há %.0f segundos — é quase de certeza uma "
    "emissão a decorrer neste momento (o POS ainda está à espera da resposta "
    "do Vendus). Espere até aos %d segundos e volte a ver a lista: libertar "
    "a reserva de uma emissão em curso é autorizar uma segunda fatura da "
    "mesma venda."
)
_MSG_LIBERTAR_EM_RETOMA = (
    "Esta reserva está RECLAMADA por uma retoma da emissão, começada há %.0f "
    "segundos: neste instante o POS pode estar mesmo a falar com o Vendus "
    "(alguém carregou em FINALIZAR nesta conta). Não encontrar o documento "
    "no Vendus AGORA não prova nada — ele ainda vai a caminho, e uma emissão "
    "demora até %d segundos no pior caso. Espere e volte a ver a lista: "
    "libertar a reserva de uma emissão em voo é autorizar uma SEGUNDA Fatura "
    "Simplificada da mesma venda."
)
_MSG_LIBERTAR_O_QUE_CONFIRMOU = (
    "Ao libertar esta reserva declarou ter aberto o Vendus, procurado a "
    "referência externa %s e visto que NÃO existe lá nenhum documento desta "
    "venda. Se existir, a próxima emissão desta conta cria uma SEGUNDA "
    "Fatura Simplificada da mesma venda, que só se corrige com uma nota de "
    "crédito."
)
_MSG_LIBERTAR_A_SEGUIR = (
    "A conta voltou a poder ser alterada, cancelada ou finalizada no POS. Se "
    "afinal aparecer um documento no Vendus para esta venda, NÃO a finalize: "
    "use a reconciliação (Reconciliar), que grava o documento que já existe "
    "e põe a venda como emitida."
)
# A MESMA situação com a caixa já fechada — e aqui `finalizar` é FALSO: a
# rota começa por `_garante_sessao_da_venda_aberta` e devolve 409 antes de
# chegar sequer à reserva. Era o caso mais comum de todos (a reserva presa
# de ontem à noite, vista na manhã seguinte) e a mensagem prometia
# exactamente a saída que não existe.
_MSG_LIBERTAR_A_SEGUIR_SESSAO_FECHADA = (
    "A caixa desta venda já NÃO está aberta, por isso a conta pode ser "
    "alterada ou cancelada no POS mas NÃO pode ser finalizada: uma venda de "
    "um turno já fechado não emite fatura. Se afinal aparecer um documento "
    "no Vendus para esta venda, NÃO a cancele: use a reconciliação "
    "(Reconciliar) — é a única forma de essa receita voltar ao sistema, e "
    "funciona com a caixa fechada de propósito, porque não emite nada, só "
    "regista o que já existe do lado da AT."
)
_MSG_SAIDAS_SESSAO_ABERTA = (
    "A caixa desta venda ainda está aberta: a operadora pode voltar a "
    "carregar em FINALIZAR (é isso que retoma uma emissão incerta). Se a "
    "Fatura Simplificada já saiu no Vendus, use Reconciliar; se confirmou "
    "que não saiu, Libertar destranca a conta."
)
_MSG_SAIDAS_SESSAO_FECHADA = (
    "A caixa desta venda já não está aberta: FINALIZAR no POS já não é uma "
    "saída (uma venda de um turno fechado não emite fatura). Se a Fatura "
    "Simplificada existe no Vendus, use Reconciliar — é a única forma de a "
    "receita voltar ao sistema. Se não existe, Libertar só destranca a "
    "conta, que fica por faturar."
)

_MSG_RECONCILIAR_SEM_VENDA = (
    "Não existe nenhuma venda com este id — não há nada para reconciliar."
)
_MSG_RECONCILIAR_SEM_REFERENCIA = (
    "Esta venda não tem como formar a referência externa (falta-lhe a loja "
    "ou a sessão de caixa) e a reserva também não a tem gravada — sem ela "
    "não há o que procurar no Vendus. Chame quem trata do sistema."
)
_MSG_RECONCILIAR_EM_RETOMA = (
    "Esta reserva está RECLAMADA por uma retoma da emissão, começada há %.0f "
    "segundos — o POS pode estar a emitir esta venda neste instante. Espere "
    "até aos %d segundos e volte a tentar: se a fatura sair, a própria "
    "emissão grava o documento e não é preciso reconciliar nada."
)
_MSG_RECONCILIAR_SEM_DOCUMENTO_NO_VENDUS = (
    "O Vendus não tem nenhum documento para a referência externa %s — não "
    "há nenhuma fatura para trazer para o sistema. Se a conta está trancada "
    "por uma reserva presa e confirmou no Vendus que não saiu nada, o que "
    "esta conta precisa é de Libertar, não de Reconciliar."
)
_MSG_RECONCILIAR_O_QUE_ACONTECEU = (
    "O documento que o Vendus já tinha para a referência externa %s foi "
    "gravado no sistema e a venda passou a `emitida`, ligada a ele. NÃO se "
    "emitiu nada de novo: isto regista uma fatura que já existia do lado da "
    "AT. A reserva desta venda fica onde está — é ela que impede uma segunda "
    "emissão da mesma conta."
)
_MSG_RECONCILIAR_Z_POR_ACERTAR = (
    "ATENÇÃO ÀS CONTAS DO TURNO: esta venda pertence à sessão de caixa %s, "
    "que já está fechada — o relatório Z desse turno foi calculado e "
    "assinado SEM ela, e esta operação não o recalcula (um Z fechado não se "
    "reescreve por trás de quem o assinou). Os %s desta fatura têm de ser "
    "acertados à mão nas contas desse turno; se foram recebidos em dinheiro, "
    "é esse o valor que estava a mais na gaveta desse fecho."
)


def _segundos_desde(criado_em: Optional[str], agora: datetime) -> Optional[float]:
    """Quanto tempo (segundos) uma reserva está neste estado — None se
    `criado_em` estiver ausente ou for ilegível, nunca um número inventado
    (mesma regra de ouro do resto do módulo: sem o dado certo, não se
    mostra um valor que a gestão possa usar para decidir algo errado)."""
    if not criado_em:
        return None
    try:
        momento = datetime.fromisoformat(criado_em)
    except (TypeError, ValueError):
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return round((agora - momento).total_seconds(), 1)


def _retoma_reclamada_ha(reserva: Dict, agora: datetime) -> Optional[float]:
    """Há quantos segundos é que a retoma DESTA reserva foi reclamada — não
    a idade da reserva, que é outra coisa e pode ter horas (ver
    `_reclamar_retoma`). `None` se ninguém a reclamou, ou se a marca não
    trouxer relógio legível."""
    if not reserva.get("em_retoma"):
        return None
    return _segundos_desde(reserva.get("em_retoma_desde"), agora)


def _retoma_em_curso(reserva: Dict, agora: datetime) -> bool:
    """`True` enquanto a retoma reclamada nesta reserva ainda puder estar a
    falar com o Vendus NESTE INSTANTE — a única pergunta que impede a
    libertação (ou a reconciliação) de apagar a reserva de uma fatura a
    nascer. Ver `_SEGUNDOS_DE_RETOMA_NORMAL` para o critério de saída.

    Uma marca `em_retoma` SEM relógio legível conta como abandonada, e não
    como viva: qualquer retoma reclamada por este código carimba sempre
    `em_retoma_desde` (`_reclamar_retoma`), por isso uma marca sem ele só
    pode ser anterior a esta versão — e o processo que a pôs já não existe
    (um restart não deixa retomas em voo). Tratá-la como viva trancava para
    sempre a única saída que estas contas têm, que é precisamente o
    contrário do que estas rotas existem para fazer. É a mesma regra que já
    valia para um `criado_em` ilegível."""
    if not reserva.get("em_retoma"):
        return False
    reclamada_ha = _retoma_reclamada_ha(reserva, agora)
    if reclamada_ha is None:
        return False
    return reclamada_ha < _SEGUNDOS_DE_RETOMA_NORMAL


def _porque_esta_presa(
    reserva: Dict, presa_ha_segundos: Optional[float], agora: datetime
) -> Dict:
    """Porque é que esta reserva ainda lá está — em código (`motivo`) e em
    português (`descricao`), porque quem lê isto é o gestor da loja, não um
    programador.

    A ordem das perguntas não é indiferente: `em_retoma` primeiro, porque uma
    reserva incerta JÁ retomada por alguém está a ser trabalhada neste
    instante e não é para lhe tocar; `incerta` a seguir; e só depois a idade
    separa a emissão que está simplesmente A DECORRER (segundos, o caso
    normal e esmagadoramente mais frequente numa listagem aberta a meio do
    serviço) da que ficou mesmo órfã. Sem essa última distinção, a listagem
    mostrava toda a emissão normal em curso como "órfã" e convidava o gestor
    a libertar a reserva de uma fatura a nascer.

    Dentro do `em_retoma` a descrição separa agora dois estados que a
    listagem dava como um só ("está a decorrer agora OU o processo morreu a
    meio") — e são opostos: no primeiro não se toca em nada, no segundo é
    preciso mesmo alguém tratar dela. O que os separa é o relógio da
    RECLAMAÇÃO (`em_retoma_desde`), nunca o da reserva."""
    if reserva.get("em_retoma"):
        reclamada_ha = _retoma_reclamada_ha(reserva, agora)
        if _retoma_em_curso(reserva, agora):
            return {
                "motivo": "em_retoma",
                "descricao": (
                    "Uma retoma desta emissão foi reclamada há %.0f segundos "
                    "e pode estar a falar com o Vendus NESTE MOMENTO. Não é "
                    "para mexer — nem libertar, nem reconciliar; volte a ver "
                    "dentro de minutos." % reclamada_ha
                ),
            }
        return {
            "motivo": "em_retoma",
            "descricao": (
                "Uma retoma desta emissão foi reclamada e nunca terminou — o "
                "processo que a reclamou morreu a meio (restart, deploy). Não "
                "se sabe se a Fatura Simplificada saiu: confirme no Vendus. "
                "Se lá existir documento, Reconciliar; se não existir, "
                "Libertar."
            ),
        }
    if reserva.get("incerta"):
        return {
            "motivo": "incerta",
            "descricao": (
                "A emissão deu timeout e a verificação por referência externa "
                "também falhou: não se sabe se a Fatura Simplificada chegou a "
                "sair. Confirme no Vendus."
            ),
        }
    if presa_ha_segundos is not None and presa_ha_segundos < _SEGUNDOS_DE_EMISSAO_NORMAL:
        return {
            "motivo": "em_emissao",
            "descricao": (
                "Reserva recente, sem marca nenhuma — provavelmente uma "
                "emissão normal a decorrer neste momento. Não é para mexer; "
                "volte a ver dentro de minutos."
            ),
        }
    return {
        "motivo": "orfa",
        "descricao": (
            "Reserva sem marca nenhuma e antiga: o processo morreu entre "
            "reservar e gravar o documento (restart, deploy), ou a emissão "
            "parou num conflito de documento fiscal. A conta está trancada."
        ),
    }


def _total_da_venda(venda: Optional[Dict]) -> Optional[float]:
    """O total da conta, para o gestor o poder procurar no Vendus. Qualquer
    falha a calculá-lo devolve None em vez de rebentar: `_totais` chama
    `_linha_vendus`, que levanta um HTTPException 422 numa linha com dados
    impossíveis (um produto que ficou sem preço, por exemplo) — e uma
    listagem de emergência não pode ficar inacessível por causa de UMA venda
    estragada, que é justamente a que mais precisa de ser vista."""
    if not venda:
        return None
    try:
        return _totais(venda)["total"]
    except Exception:  # noqa: BLE001 — ver a docstring
        return None


@router.get("/fiscal/reservas-presas")
@router.get("/fiscal/reservas-incertas")
async def listar_reservas_presas(_: dict = Depends(gestor_atual)) -> List[Dict]:
    """Todas as reservas fiscais PRESAS — não só as marcadas `incerta`: também
    as que estão em retoma e as ÓRFÃS (sem marca nenhuma, deixadas para trás
    por um processo que morreu ou por um `ConflitoDocumentoFiscal`). Cada uma
    diz porque está presa (`motivo`/`descricao`) e há quanto tempo
    (`presa_ha_segundos`), e traz o total da conta para o gestor o procurar
    no Vendus.

    O nome antigo do caminho (`/fiscal/reservas-incertas`) continua a
    responder, porque já anda escrito em mensagens de erro e na documentação
    do ecrã de finalizar — o caminho novo (`/fiscal/reservas-presas`) é que
    descreve o que ela faz hoje.

    **Presa = a reserva existe e a venda dela ainda não está `emitida`.** É
    a junção com a venda que decide, e não a marca `documento_id` da reserva:
    essa é só o filtro barato que evita ler a colecção inteira (ver
    `_gravar_documento`), e as reservas anteriores a esse campo — ou aquelas
    em que a marca falhou — entram na mesma por aqui e são descartadas na
    junção. Uma venda `emitida` NUNCA aparece: a reserva dela fica lá para
    sempre de propósito, é ela que sustenta a idempotência."""
    db = obter_db()
    agora = datetime.now(timezone.utc)
    reservas = await db[COLECOES["refs_fiscais"]].find(
        {"documento_id": None}
    ).to_list(_LIMITE_RESERVAS_PRESAS)

    saida = []
    for r in reservas:
        venda = await db[COLECOES["vendas"]].find_one({"id": r.get("venda_id")})
        if venda is not None and venda.get("estado") == "emitida":
            continue
        presa_ha_segundos = _segundos_desde(r.get("criado_em"), agora)
        # O ESTADO DA CAIXA desta venda muda quais são as saídas possíveis, e
        # é por isso que ele aparece aqui: com a sessão fechada, `finalizar`
        # no POS já não é uma delas (`_garante_sessao_da_venda_aberta`
        # devolve 409 antes de chegar à reserva) — e era isso mesmo que a
        # listagem e a libertação deixavam o gestor acreditar.
        sessao = await _sessao_da_venda(db, venda)
        entrada = {
            "ext_ref": r.get("ext_ref"),
            "venda_id": r.get("venda_id"),
            "loja_id": venda.get("loja_id") if venda else None,
            "estado_da_venda": venda.get("estado") if venda else None,
            "total_da_venda": _total_da_venda(venda),
            "criado_em": r.get("criado_em"),
            "presa_ha_segundos": presa_ha_segundos,
            "incerta": bool(r.get("incerta")),
            "em_retoma": bool(r.get("em_retoma")),
            "retoma_reclamada_ha_segundos": _retoma_reclamada_ha(r, agora),
            "sessao_id": venda.get("sessao_id") if venda else None,
            "sessao_estado": sessao.get("estado") if sessao else None,
            "saidas": (
                _MSG_SAIDAS_SESSAO_ABERTA
                if sessao is not None and sessao.get("estado") == "aberta"
                else _MSG_SAIDAS_SESSAO_FECHADA
            ),
        }
        entrada.update(_porque_esta_presa(r, presa_ha_segundos, agora))
        saida.append(entrada)
    return saida


async def _sessao_da_venda(db, venda: Optional[Dict]) -> Optional[Dict]:
    """A sessão de caixa DESTA venda (`venda["sessao_id"]`), ou `None` se a
    venda não existe, não tem sessão, ou a sessão desapareceu. Nunca "a
    sessão aberta desta caixa": uma caixa pode ter reaberto entretanto com
    uma sessão nova, que não tem nada a ver com esta venda (a mesma pergunta
    de `_garante_sessao_da_venda_aberta`)."""
    if not venda:
        return None
    return await db[COLECOES["sessoes_caixa"]].find_one({"id": venda.get("sessao_id")})


# O nome antigo da função, mantido a apontar para a mesma: já era importado
# de fora (guiões de reprodução, testes) e não há razão nenhuma para o partir.
listar_reservas_incertas = listar_reservas_presas


class PedidoLibertarReserva(BaseModel):
    """A confirmação do gestor, exigida com todas as letras (ver
    `libertar_reserva_presa`). `confirmado_no_vendus` não tem valor por
    omissão útil de propósito: quem não o enviar explicitamente a `true`
    apanha a recusa com o texto do que tem de ir ver primeiro."""

    confirmado_no_vendus: bool = False
    # Opcional, só para o registo (log): o que o gestor viu, ou o número do
    # documento que confirmou não existir. Nunca muda nenhuma decisão.
    nota: Optional[str] = None


@router.post("/fiscal/reservas/{venda_id}/libertar")
async def libertar_reserva_presa(
    venda_id: str, dados: PedidoLibertarReserva, gestor: Dict = Depends(gestor_atual)
) -> Dict:
    """Liberta uma reserva fiscal presa e DESTRANCA a conta — a única saída
    que existe para uma reserva órfã ou para uma incerta já resolvida à mão.

    **O QUE O GESTOR TEM DE CONFIRMAR ANTES DE USAR ISTO:** abrir o Vendus,
    procurar a `ext_ref` desta venda (a referência externa, `pos-{loja}-
    {sessão}-{venda}`) e ver que NÃO existe lá nenhum documento para ela.
    Libertar a reserva de uma fatura que SAIU é autorizar uma segunda Fatura
    Simplificada da mesma venda — duas faturas do mesmo açaí entregues à AT,
    que só se corrigem com uma nota de crédito e que ao fim do dia aparecem
    como dinheiro a menos na gaveta. É por isso que o pedido exige
    `confirmado_no_vendus=true`: um clique distraído não pode chegar aqui.

    De gestão, nunca do balcão (`gestor_atual`, o token do backoffice — não o
    PIN da operadora). E recusa-se em quatro casos, porque a confirmação
    humana pode estar errada e há coisas que a máquina sabe melhor:

    1. Já existe um documento gravado em `fat_documentos` para esta `ext_ref`
       (ou a venda já está `emitida`) — a fatura saiu mesmo, e é esta reserva
       que impede a segunda.
    2. **A reserva está EM RETOMA reclamada há pouco tempo** — alguém
       carregou em FINALIZAR nesta conta e a emissão pode estar a falar com o
       Vendus neste instante. Esta é a recusa que faltava, e faltava por o
       relógio ser o errado: a guarda 3 media o `criado_em` da reserva
       ORIGINAL, que numa incerta das 20h retomada à meia-noite tem 4 horas —
       passava folgadamente. Reproduzido em processo: a retoma a emitir, o
       gestor a procurar a ext_ref no Vendus (ainda lá não está — vai a
       caminho), a libertar, a operadora a carregar outra vez em FINALIZAR, e
       DUAS Faturas Simplificadas reais da mesma venda (`FS 2026/901` e
       `FS 2026/902`), com o cliente a levar o talão de uma e a venda a
       apontar para a outra. Ver `_retoma_em_curso`.
    3. A reserva é RECENTE (< `_SEGUNDOS_DE_EMISSAO_NORMAL`) — é quase de
       certeza uma emissão a decorrer neste instante, e nenhum gestor
       consegue ter confirmado o Vendus dentro dessa janela.
    4. Não existe reserva nenhuma para esta venda (404) — nada para libertar.

    A venda NÃO se toca: fica como estava (`aberta`), que é precisamente o que
    devolve o balcão ao serviço. O que se apaga é só a reserva — e o que a
    resposta promete a seguir depende da CAIXA desta venda: com a sessão
    fechada, `finalizar` não é uma das saídas (ver
    `_MSG_LIBERTAR_A_SEGUIR_SESSAO_FECHADA` e a rota de reconciliar)."""
    db = obter_db()
    reserva = await db[COLECOES["refs_fiscais"]].find_one({"venda_id": venda_id})
    if reserva is None:
        raise HTTPException(status_code=404, detail=_MSG_LIBERTAR_SEM_RESERVA)
    ext_ref = reserva.get("ext_ref")
    # Sem `ext_ref` não se apaga nada: `_libertar_reserva` apaga POR ext_ref, e
    # um `delete_one({"ext_ref": None})` casaria com QUALQUER outra reserva
    # estragada — libertava a reserva de outra venda, que é precisamente o
    # estrago que esta rota inteira existe para não cometer.
    if not ext_ref:
        raise HTTPException(status_code=409, detail=_MSG_LIBERTAR_SEM_EXT_REF)

    if not dados.confirmado_no_vendus:
        raise HTTPException(
            status_code=422, detail=_MSG_LIBERTAR_SEM_CONFIRMACAO % ext_ref
        )

    documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
    if documento is not None:
        raise HTTPException(
            status_code=409,
            detail=_MSG_LIBERTAR_COM_DOCUMENTO % (
                documento.get("numero"), documento.get("atcud"),
            ),
        )

    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    # Cinto e suspensórios: o `documento_id` da venda e o estado `emitida`
    # dizem a mesma coisa que a procura acima, mas por outro caminho — e uma
    # segunda emissão da mesma venda é caro de mais para se confiar numa só
    # leitura.
    if venda is not None and (venda.get("estado") == "emitida" or venda.get("documento_id")):
        raise HTTPException(status_code=409, detail=_MSG_LIBERTAR_VENDA_EMITIDA)

    agora = datetime.now(timezone.utc)
    presa_ha_segundos = _segundos_desde(reserva.get("criado_em"), agora)

    # A RETOMA em voo, medida pelo relógio DELA (`em_retoma_desde`) e não
    # pelo da reserva — a pergunta que faltava, e a razão por que faltava.
    # A informação já estava toda no Mongo: a própria rota calculava
    # `motivo='em_retoma'` e escrevia-o no log ao libertar, e a listagem já
    # avisava o gestor de que não devia mexer. Só esta linha é que não a
    # lia. TEM de vir antes da guarda da idade: é precisamente o caso em que
    # a reserva é velhíssima (uma incerta de há horas) e a emissão é de
    # AGORA.
    if _retoma_em_curso(reserva, agora):
        raise HTTPException(
            status_code=409,
            detail=_MSG_LIBERTAR_EM_RETOMA % (
                _retoma_reclamada_ha(reserva, agora),
                int(_SEGUNDOS_DE_RETOMA_NORMAL),
            ),
        )

    # `None` (criado_em ausente ou ilegível) não trava: uma emissão a decorrer
    # tem SEMPRE um `criado_em` legível, escrito por `_agora()` no próprio
    # `_reservar` — uma reserva sem ele é, por construção, dados estragados de
    # há muito, exactamente o caso que esta rota existe para desentalar.
    if presa_ha_segundos is not None and presa_ha_segundos < _SEGUNDOS_DE_EMISSAO_NORMAL:
        raise HTTPException(
            status_code=409,
            detail=_MSG_LIBERTAR_RESERVA_RECENTE % (
                presa_ha_segundos, int(_SEGUNDOS_DE_EMISSAO_NORMAL),
            ),
        )

    porque = _porque_esta_presa(reserva, presa_ha_segundos, agora)
    # A caixa desta venda decide o que se pode prometer a seguir — lida ANTES
    # de apagar a reserva, que é quando a venda ainda está toda no sítio.
    sessao = await _sessao_da_venda(db, venda)
    sessao_aberta = sessao is not None and sessao.get("estado") == "aberta"
    await _libertar_reserva(db, ext_ref)

    # Apagar uma reserva fiscal à mão é um acto sério e a reserva desaparece
    # com ele — sem este registo não ficava rasto nenhum de quem a libertou
    # nem do que disse ter confirmado.
    logger.warning(
        "[faturacao] reserva fiscal libertada à mão: ext_ref=%s venda=%s motivo=%s "
        "presa_ha_segundos=%s sessao_aberta=%s por=%s nota=%r",
        ext_ref, venda_id, porque["motivo"], presa_ha_segundos, sessao_aberta,
        gestor.get("email") or gestor.get("user_id"), dados.nota,
    )

    return {
        "libertada": True,
        "venda_id": venda_id,
        "ext_ref": ext_ref,
        "motivo": porque["motivo"],
        "presa_ha_segundos": presa_ha_segundos,
        "sessao_estado": sessao.get("estado") if sessao else None,
        "o_que_confirmou": _MSG_LIBERTAR_O_QUE_CONFIRMOU % ext_ref,
        "a_seguir": (
            _MSG_LIBERTAR_A_SEGUIR if sessao_aberta
            else _MSG_LIBERTAR_A_SEGUIR_SESSAO_FECHADA
        ),
    }


# --- Gestão: RECONCILIAR uma venda com a fatura que já existe no Vendus -------
#
# A saída que faltava, e a única que salva o dinheiro.
#
# A retoma de uma reserva incerta só existe através da rota `finalizar`, e essa
# começa por `_garante_sessao_da_venda_aberta`: com a caixa fechada dá 409
# antes de chegar sequer à reserva. Ou seja, a reserva presa de ontem à noite,
# vista na manhã seguinte (medido: `presa_ha_segundos=85731.2`), não tinha
# NENHUMA forma de acabar bem — e se a Fatura Simplificada chegou mesmo a sair
# no Vendus, o documento nunca entrava em `fat_documentos`: a venda ficava
# `aberta` para sempre ou era cancelada, e a receita real desaparecia do Z e do
# dashboard, sem nada que o assinalasse. Só se resolvia com Mongo à mão.
#
# Esta rota pergunta ao Vendus pela `external_reference` determinística desta
# venda — a MESMA verificação que o `finalizar` já faz — e, se lá existir
# documento, grava-o e liga-lhe a venda. **Funciona com a caixa fechada de
# propósito:** não emite nada, REGISTA um facto que já aconteceu do lado da AT.
# O número e o ATCUD vêm do Vendus ou não vêm de lado nenhum — o pedido não
# tem (nem pode ter) campo nenhum onde o gestor os escreva à mão.
#
# O que ela NÃO faz, e diz alto: recalcular o Z de uma sessão já fechada. Esse
# talão foi assinado por uma funcionária com a gaveta contada à frente dela;
# reescrevê-lo por trás era mentir sobre o que foi contado. A resposta traz o
# aviso do que ficou por acertar à mão nesse turno.


class PedidoReconciliarReserva(BaseModel):
    """O pedido de reconciliação — deliberadamente SEM campo nenhum para o
    número, o ATCUD ou o total do documento.

    Não é esquecimento nem economia: um número de documento fiscal escrito à
    mão é um número inventado à espera de acontecer (um dígito trocado liga a
    venda a uma fatura de outro cliente, e o ATCUD é o código que a AT usa
    para identificar o documento). O documento vem do Vendus, pela referência
    externa determinística desta venda, ou não vem de lado nenhum. Mesmo
    padrão do `sessao_id` em `caixa.PedidoMovimento`: o campo perigoso não se
    valida — não se declara."""

    # Só para o registo (log), como em `PedidoLibertarReserva`: o que o gestor
    # viu no Vendus. Nunca muda nenhuma decisão.
    nota: Optional[str] = None


def _euros(valor) -> str:
    """O valor para uma mensagem ao gestor — "8,99 €" ou, sem valor legível,
    uma frase que não finge um número (mesma regra do resto do módulo)."""
    try:
        return "%.2f €" % float(valor)
    except (TypeError, ValueError):
        return "o valor desta fatura"


@router.post("/fiscal/reservas/{venda_id}/reconciliar")
async def reconciliar_reserva_presa(
    venda_id: str,
    dados: Optional[PedidoReconciliarReserva] = None,
    gestor: Dict = Depends(gestor_atual),
) -> Dict:
    """Traz para o sistema a Fatura Simplificada que JÁ existe no Vendus para
    esta venda: grava o documento em `fat_documentos` e passa a venda a
    `emitida`, ligada a ele.

    Não emite nada. Não aceita números escritos à mão. Pergunta ao Vendus pela
    `external_reference` desta venda (`ext_ref_determinista`, a mesma da
    reserva) e só age se lá existir mesmo documento — reutilizando a
    maquinaria de sempre (`procurar_por_referencia_externa`,
    `_gravar_documento`), nunca uma segunda escrita paralela.

    **É a única saída de uma reserva presa numa caixa já FECHADA**, e é por
    isso que não exige a sessão aberta: registar um documento que a AT já tem
    não é emitir. Sem isto, a receita dessa venda desaparecia do Z e do
    dashboard para sempre.

    Recusa-se:
    - se a venda não existir (404);
    - se não houver como formar a referência externa (409);
    - se a reserva estiver EM RETOMA reclamada há pouco (409) — o POS pode
      estar a emitir esta venda neste instante, e essa emissão grava o
      documento sozinha (a mesma pergunta de `libertar_reserva_presa`);
    - se o Vendus não tiver documento nenhum para a referência (409) — não há
      nada para reconciliar, e o que essa conta precisa é de Libertar;
    - se a configuração do Vendus faltar (502) ou o Vendus estiver
      indisponível (502) — nunca se conclui "não existe" a partir de uma
      leitura que falhou (a mesma regra de `VerificacaoFiscalIncerta`)."""
    db = obter_db()
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if venda is None:
        raise HTTPException(status_code=404, detail=_MSG_RECONCILIAR_SEM_VENDA)

    reserva = await db[COLECOES["refs_fiscais"]].find_one({"venda_id": venda_id})
    # A `ext_ref` da reserva é a que foi MESMO usada na emissão; a fórmula
    # determinística só entra quando não há reserva nenhuma (o gestor libertou
    # a reserva e só depois descobriu o documento no Vendus — o caso que a
    # mensagem de `libertar` manda tratar como fatura já emitida). Nunca uma
    # terceira fonte: é sempre `ext_ref_determinista`, a mesma função.
    ext_ref = (reserva or {}).get("ext_ref")
    # `loja_id` e `sessao_id` exigem-se SEMPRE, não só quando é preciso
    # formar a referência: `_gravar_documento` grava a loja no documento
    # fiscal, e uma venda sem eles é dados estragados que não se reconciliam
    # às cegas — 409 claro, nunca um KeyError/500 no meio de uma escrita
    # fiscal.
    if not (venda.get("loja_id") and venda.get("sessao_id")):
        raise HTTPException(status_code=409, detail=_MSG_RECONCILIAR_SEM_REFERENCIA)
    if not ext_ref:
        ext_ref = ext_ref_determinista(
            venda["loja_id"], venda["sessao_id"], venda["id"]
        )

    agora = datetime.now(timezone.utc)
    if reserva is not None and _retoma_em_curso(reserva, agora):
        raise HTTPException(
            status_code=409,
            detail=_MSG_RECONCILIAR_EM_RETOMA % (
                _retoma_reclamada_ha(reserva, agora),
                int(_SEGUNDOS_DE_RETOMA_NORMAL),
            ),
        )

    documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
    if documento is not None:
        # O documento já cá estava. Duas hipóteses, e as duas acabam bem sem
        # incomodar o Vendus: ou a venda também já está `emitida` (isto é um
        # pedido repetido — responde-se o mesmo, sem escrever nada de novo),
        # ou o processo morreu entre as duas escritas de `_gravar_documento`
        # e a venda ficou para trás em `aberta` com uma FS real gravada — e
        # aí a religação é exactamente o que falta.
        if venda.get("estado") != "emitida" or venda.get("documento_id") != documento["id"]:
            await _ligar_venda_ao_documento(db, ext_ref, venda_id, documento)
        veio_do_vendus_agora = False
    else:
        conta = obter_conta(_nif_configurado())
        if conta is None:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Conta Vendus não configurada para o NIF %s — sem isto não "
                    "há como perguntar ao Vendus o que existe para esta venda."
                    % _nif_configurado()
                ),
            )
        register_id = _register_id_configurado()
        if register_id is None:
            raise HTTPException(
                status_code=502,
                detail=(
                    "VENDUS_REGISTER_ID não está configurado — sem isto não há "
                    "como procurar o documento desta venda no Vendus."
                ),
            )

        with ClienteEmissaoVendus(conta.chave) as cliente_vendus:
            try:
                encontrado = await asyncio.to_thread(
                    cliente_vendus.procurar_por_referencia_externa, ext_ref, register_id
                )
            except VendusErro as e:
                # Uma leitura que falhou não é um "não existe": propaga-se
                # como indisponibilidade, para o gestor voltar a tentar — a
                # mesma regra que impede o núcleo de emitir às cegas depois
                # de uma verificação falhada.
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Não foi possível perguntar ao Vendus pelo documento "
                        "desta venda: %s. Não se conclui nada de uma leitura "
                        "que falhou — volte a tentar." % e
                    ),
                )

        if encontrado is None:
            raise HTTPException(
                status_code=409,
                detail=_MSG_RECONCILIAR_SEM_DOCUMENTO_NO_VENDUS % ext_ref,
            )

        try:
            documento = await _gravar_documento(db, ext_ref, venda, encontrado)
        except ConflitoDocumentoFiscal as e:
            raise HTTPException(status_code=500, detail=str(e))
        veio_do_vendus_agora = True

    # A reserva (se existir) deixa de estar `incerta`: já se sabe o que
    # aconteceu — saiu mesmo, e o documento está gravado. `_gravar_documento`
    # já lhe pôs o `documento_id`, que é o que a tira da listagem de presas.
    if reserva is not None:
        await _limpar_incerta_resolvida(db, ext_ref)

    sessao = await _sessao_da_venda(db, venda)
    sessao_estado = sessao.get("estado") if sessao else None
    # O Z de uma sessão já fechada NÃO se recalcula aqui — e não se finge que
    # ficou tudo bem: diz-se ao gestor o que tem de acertar à mão nesse turno.
    z_por_acertar = sessao_estado != "aberta"

    logger.warning(
        "[faturacao] venda reconciliada com o documento do Vendus: ext_ref=%s "
        "venda=%s documento=%s numero=%r atcud=%r do_vendus_agora=%s "
        "sessao=%r sessao_estado=%r por=%s nota=%r",
        ext_ref, venda_id, documento.get("id"), documento.get("numero"),
        documento.get("atcud"), veio_do_vendus_agora, venda.get("sessao_id"),
        sessao_estado, gestor.get("email") or gestor.get("user_id"),
        (dados.nota if dados else None),
    )

    return {
        "reconciliada": True,
        "venda_id": venda_id,
        "ext_ref": ext_ref,
        "estado_da_venda": "emitida",
        "documento": _resposta_documento(documento),
        # `False` quando o documento já estava gravado localmente (pedido
        # repetido, ou venda que ficou para trás em `aberta`) — o gestor tem
        # de conseguir distinguir "trouxe agora do Vendus" de "já cá estava".
        "veio_do_vendus_agora": veio_do_vendus_agora,
        "sessao_id": venda.get("sessao_id"),
        "sessao_estado": sessao_estado,
        "z_por_acertar": z_por_acertar,
        "aviso_do_z": (
            _MSG_RECONCILIAR_Z_POR_ACERTAR % (
                venda.get("sessao_id"), _euros(documento.get("total")),
            )
            if z_por_acertar else None
        ),
        "o_que_aconteceu": _MSG_RECONCILIAR_O_QUE_ACONTECEU % ext_ref,
    }
