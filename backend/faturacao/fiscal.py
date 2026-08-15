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
    uma reserva — espera pelo documento do vencedor."""
    resultado = await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref, "incerta": True, "em_retoma": None},
        {"$set": {"em_retoma": True}},
    )
    return resultado.matched_count == 1


async def _limpar_incerta_resolvida(db, ext_ref: str) -> None:
    """'Um problema associado' da mesma revisão: hoje a marca `incerta`
    fica PARA SEMPRE, mesmo depois de a venda ficar emitida — a reserva
    nunca deixa de aparecer como 'presa' na listagem de gestão (ver a rota
    `/fiscal/reservas-incertas`), muito depois de estar resolvida. Chamada
    só quando `_retomar_reserva_incerta` termina com um documento em mãos
    (encontrado pela verificação, ou emitido agora) — limpa `incerta` E
    `em_retoma` na mesma escrita, para o estado voltar a "sem ninguém a
    trabalhar nisto, e já não incerta"."""
    await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref}, {"$set": {"incerta": False, "em_retoma": None}}
    )


async def _esperar_documento_do_vencedor(
    db,
    ext_ref: str,
    esperar: Callable[[float], Awaitable[None]],
    tentativas: int,
) -> Dict:
    """Quem perde a reserva chega aqui: OU o documento do vencedor já existe
    (devolve-o de imediato), OU ainda está a ser escrito (espera, com um
    orçamento limitado — nunca para sempre)."""
    for _ in range(tentativas):
        documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
        if documento is not None:
            return documento
        await esperar(_ESPERA_ENTRE_TENTATIVAS_S)
    raise EmissaoEmCurso(
        "Já existe uma reserva de emissão para esta venda (ext_ref=%s) mas "
        "o documento ainda não ficou disponível — tente novamente dentro de "
        "momentos." % ext_ref
    )


async def _gravar_documento(db, ext_ref: str, venda: Dict, bruto: Dict) -> Dict:
    """Grava `bruto` (o que o Vendus devolveu — criado agora OU encontrado
    por uma verificação) em `fat_documentos` e marca a venda emitida —
    passo 3 da sequência (ver a docstring do módulo). Partilhado por todos
    os caminhos que chegam a um documento real: quem acabou de emitir, e
    quem retoma uma reserva incerta e encontra o documento já lá (ver
    `_retomar_reserva_incerta`)."""
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

    await db[COLECOES["vendas"]].update_one(
        {"id": venda["id"]},
        {"$set": {"estado": "emitida", "documento_id": documento["id"]}},
    )
    return documento


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
        return await _esperar_documento_do_vencedor(db, ext_ref, esperar_efectivo, tentativas_espera)

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
                {"ext_ref": ext_ref}, {"$set": {"em_retoma": None}}
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
    return await _esperar_documento_do_vencedor(db, ext_ref, esperar, tentativas_espera)


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


# --- B1: gestão das reservas incertas ------------------------------------------
#
# 'Um problema associado' da re-revisão do núcleo fiscal: uma reserva incerta
# não tinha NENHUMA saída nem visibilidade. Se o Vendus ficar em baixo, a
# venda fica presa a devolver 503 (VerificacaoFiscalIncerta); quando o turno
# fecha, I1 passa a recusá-la para sempre (a sessão já não está aberta) e o
# dinheiro fica sem Z nenhum que o explique — a única saída era mexer no
# Mongo à mão, sem sequer saber QUANTAS vendas estavam neste estado. Esta
# rota (de GESTÃO, nunca do POS — `gestor_atual`, o backoffice, não o PIN da
# operadora ao balcão) dá por onde começar a investigar.


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


@router.get("/fiscal/reservas-incertas")
async def listar_reservas_incertas(_: dict = Depends(gestor_atual)) -> List[Dict]:
    """Lista as reservas ainda marcadas `incerta` — a venda, a loja, e há
    quanto tempo estão neste estado. Resolvidas (documento encontrado ou
    emitido por uma retoma) deixam de aparecer aqui — ver
    `_limpar_incerta_resolvida` — para esta lista nunca mostrar como
    "presa" uma reserva que já tem, de facto, um documento fiscal."""
    db = obter_db()
    agora = datetime.now(timezone.utc)
    reservas = await db[COLECOES["refs_fiscais"]].find({"incerta": True}).to_list(1000)

    saida = []
    for r in reservas:
        venda = await db[COLECOES["vendas"]].find_one({"id": r.get("venda_id")})
        saida.append({
            "ext_ref": r.get("ext_ref"),
            "venda_id": r.get("venda_id"),
            "loja_id": venda.get("loja_id") if venda else None,
            "criado_em": r.get("criado_em"),
            "presa_ha_segundos": _segundos_desde(r.get("criado_em"), agora),
            "em_retoma": bool(r.get("em_retoma")),
        })
    return saida
