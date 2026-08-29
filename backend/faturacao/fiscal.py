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
from .modo import modo_efectivo
from .pos_auth import operador_atual
from .caixa_math import soma_vendas_dinheiro
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
from .vendus.cliente import (
    VendusErro,
    VendusHTTPErro,
    VendusIndisponivel,
    obter_conta,
)
from .vendus.emissao import (
    ClienteEmissaoVendus,
    RegisterIdInvalido,
    VendusModoInvalido,
    VendusRateLimitado,
    _register_id_configurado,
)

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
# A caixa está a MEIO de um fecho (`caixa.py`: o estado intermédio
# `a_fechar`, posto ANTES de o fecho somar seja o que for). É uma ESPERA, e
# não um fim: enquanto a marca lá está não se emite, mas o fecho ainda pode
# ser recusado e desfeito — é o que acontece sempre que ele encontra uma
# emissão viva nesta caixa. Dizer a esta operadora o mesmo que se diz a quem
# chega depois de um Z assinado (`_MSG_SESSAO_FECHADA_ENTRETANTO`) era
# mandá-la ir picar a conta a uma sessão nova que pode nunca vir a existir —
# com o cliente à frente e a conta ainda ali, aberta e faturável. Medido
# nesta ronda: 18 em 300 interposições diziam "o turno acabou" com a caixa a
# terminar `aberta`, sem Z nenhum escrito e sem uma única emissão ao Vendus.
_MSG_SESSAO_A_FECHAR_AGORA = (
    "A caixa desta venda está a FECHAR o turno neste momento — o Z está a "
    "ser calculado e, enquanto isso, esta sessão não emite faturas. NÃO saiu "
    "nenhuma Fatura Simplificada e nada foi enviado ao Vendus: a conta "
    "continua aqui, tal como está. Espere alguns segundos e carregue outra "
    "vez em FINALIZAR — um fecho demora um instante, e um que apanhe uma "
    "emissão a meio nesta caixa é recusado e desfeito por ela própria. Se o "
    "turno fechar mesmo, o ecrã dir-lho-á com outras palavras."
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
# Não manda chamar ninguém, de propósito: não há nada de errado com esta
# conta nem com este sistema — alguém mexeu na conta no outro PC enquanto
# esta fatura era preparada, e o que ela pagou deixou de ser o que a conta
# diz. Basta olhar para a conta como está agora e repetir.
_MSG_CONTA_ALTERADA_ENTRETANTO = (
    "A conta MUDOU enquanto a fatura estava a ser preparada — alguém "
    "acrescentou, tirou ou alterou alguma coisa. NÃO saiu nenhuma Fatura "
    "Simplificada e nada foi enviado ao Vendus. Confirme a conta como ela "
    "está agora, receba o que faltar (ou devolva o que sobrar) e finalize "
    "outra vez."
)
# A LISTA CURTA do que sabemos ser seguro libertar (`_emitir_e_gravar`).
#
# Libertar a reserva é dizer "não saiu fatura nenhuma, podem emitir de novo".
# Só entra aqui o que É PROVA disso, e cada entrada tem de dizer porquê:
#
# - `RegisterIdInvalido` e `VendusModoInvalido` — levantados por
#   `vendus/emissao.py` ANTES de qualquer pedido sair para a rede. Nada
#   chegou ao Vendus, e a prova é essa: o pedido não existiu.
# - `VendusRateLimitado` — o Vendus respondeu 429 ("créditos esgotados") a
#   TODAS as tentativas. Um 429 é uma recusa a processar, não um documento
#   criado com uma resposta infeliz.
# - `VendusHTTPErro` — um 4xx que não é 429 (os 5xx e os erros de rede
#   viram `VendusIndisponivel`, tratado acima com a verificação por
#   referência externa). O Vendus, ou o que estiver à frente dele, recusou o
#   pedido: um tax_id errado, uma chave inválida, um método de pagamento
#   inexistente. É o caso COMUM ao balcão e é preciso que a conta destranque
#   — a operadora corrige e volta a finalizar.
#
# O que NÃO entra, de propósito: tudo o que possa acontecer DEPOIS de uma
# resposta 2xx. `VendusRespostaIlegivel` (o corpo que não se lê num 200) é
# `VendusErro` mas NÃO é `VendusHTTPErro`, e por isso cai — como tem de
# cair — no ramo do desfecho desconhecido.
_ERROS_COM_PROVA_DE_QUE_NADA_SAIU = (
    RegisterIdInvalido,
    VendusModoInvalido,
    VendusRateLimitado,
    VendusHTTPErro,
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


class SessaoEmFechoAgora(SessaoJaNaoAberta):
    """O caso PARTICULAR de `SessaoJaNaoAberta` em que a sessão está em
    `a_fechar` — um fecho a DECORRER, não um fecho FEITO.

    Para o núcleo é a mesma decisão de sempre (não se emite, a reserva
    liberta-se, nada vai ao Vendus) e por isso é uma subclasse: quem só
    quiser saber "a sessão deixou de estar aberta?" continua a apanhá-la sem
    mudar uma linha. O que muda é o que se DIZ a quem está ao balcão, e a
    diferença não é de estilo — é de facto:

    - fecho FEITO → o Z daquele turno está assinado, esta conta não se
      fatura mais aqui, e a saída é picá-la na sessão nova
      (`_MSG_SESSAO_FECHADA_ENTRETANTO`);
    - fecho A DECORRER → não há Z nenhum, a caixa pode acabar a noite
      `aberta` (o fecho é recusado e desfeito assim que encontra uma emissão
      viva nesta caixa, ver `caixa.py::fechar_caixa`), e a conta continua
      exactamente onde está. É uma espera de segundos
      (`_MSG_SESSAO_A_FECHAR_AGORA`).

    Reproduzido em processo, varrendo 300 interposições do FINALIZAR contra o
    FECHAR: em 18 delas a operadora lia "a caixa foi FECHADA [...] o Z desse
    turno já foi assinado sem ela" e o estado real no fim era sessão
    `aberta`, nenhum Z escrito, conta `aberta`, zero emissões. Três
    afirmações, as três falsas — e a única acção que a mensagem sugeria
    (picar tudo de novo noutra sessão) era a única que estava errada."""


class ContaAlteradaDepoisDeConfirmada(FiscalErro):
    """A CONTA mudou entre o retrato que a rota `finalizar` leu e o momento
    em que esta tentativa ganhou a reserva: uma linha a mais, uma linha a
    menos, uma quantidade ou um desconto diferentes.

    É a terceira forma da mesma família de `VendaJaNaoAberta` e
    `SessaoJaNaoAberta` — a validação toda corre sobre um retrato tirado
    antes dela — e a que faltava. Nesta janela a venda ainda está `aberta` e
    ainda não tem reserva, por isso `venda.py::juntar_linha` (e as outras
    três rotas de escrita) passam o `_garante_sem_emissao` E a escrita
    condicional a `{"estado": "aberta"}`: a linha entra na conta e NÃO entra
    na fatura, porque a `emitir` fechou sobre os `itens` do retrato velho.
    Reproduzido em processo, sobre as rotas reais: um segundo açaí picado
    dentro da janela e uma Fatura Simplificada REAL de 8,99 € numa conta de
    17,98 €.

    **E a saída não é recompor os itens com as linhas novas** — essa é a
    correcção óbvia e é a errada. A soma dos pagamentos foi validada contra
    os `_totais` do retrato VELHO (a rota recusa com 422 quando não bate):
    emitir as linhas novas produzia uma fatura cujo total já não é o que a
    operadora recebeu do cliente, e trocava um erro por outro pior — uma FS
    real de 17,98 € contra 8,99 € que entraram mesmo na gaveta. O que a
    operadora confirmou deixou de ser verdade, e o que ela tem de ver é a
    conta nova: por isso não se emite, e diz-se-lhe que confirme e finalize
    outra vez.

    Como em `VendaJaNaoAberta`: nada foi ao Vendus, a reserva liberta-se, e
    não se emite."""


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


class DesfechoDaEmissaoIncerto(FiscalErro):
    """A emissão rebentou de uma forma que NÃO prova que o Vendus deixou de
    criar o documento — tudo o que não está em
    `_ERROS_COM_PROVA_DE_QUE_NADA_SAIU`.

    O caso concreto que lhe deu origem: `criar_fatura_simplificada` recebe
    uma resposta **2xx** (o documento fiscal já existe do lado da AT) e
    rebenta a seguir, a ler o corpo — um proxy à frente do Vendus a devolver
    200 com o HTML de uma página de manutenção. Nenhum desses erros é
    `VendusErro`, por isso não caía no ramo da verificação por referência
    externa; caía no `except Exception` que LIBERTAVA a reserva. Medido:
    «FS 2026/900 criada → JSONDecodeError → venda='aberta' | reservas=0 |
    fat_documentos=0», o ecrã a dizer "não saiu nenhum documento, pode
    emitir outra vez", e uma SEGUNDA Fatura Simplificada real.

    Como em `VerificacaoFiscalIncerta`, e pela mesma razão: a reserva NÃO se
    liberta — fica `incerta`, o que obriga a tentativa seguinte a verificar
    no Vendus antes de emitir seja o que for. A rota traduz isto no MESMO
    503 de "não sabemos se saiu", nunca num 500 (que o ecrã lê, pela venda
    relida, como "nada saiu — pode repetir")."""


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
        # Esta lista é branca: o que não estiver nela NÃO sai para o Vendus,
        # por muito que `precos.linha_de_venda` o produza. O `id` (o id do
        # produto no Vendus, ver `precos.id_vendus_do_produto`) tem de estar
        # cá — sem isto ele era construído na linha e deitado fora aqui, em
        # silêncio, e o Vendus continuava a criar um produto novo por cada
        # venda como se nada fosse.
        #
        # Cuidado ao ler: este `id` é o do PRODUTO no Vendus, não o uuid da
        # linha da nossa conta — esse nunca chega aqui, porque
        # `linha_de_venda` não o copia para a linha que constrói.
        item = {
            chave: li[chave]
            for chave in ("id", "title", "qty", "gross_price", "tax_id")
            if chave in li
        }
        alvo_liquido = round(liquido_apos_propria - parte_global, 2)
        pct = _percentagem_que_reproduz(bruto, alvo_liquido)
        if pct > 0:
            item["discount_percentage"] = pct
        saida.append(item)
    return saida


# **A marca que separa, dentro do nosso prefixo, uma NOTA DE CRÉDITO de uma
# Fatura Simplificada.** Vive aqui e não em `nota_credito.py` porque quem
# precisa de a LER é a reconciliação do fecho, que é deste ficheiro — e
# `nota_credito.py` importa deste, nunca ao contrário. Uma segunda cópia do
# `"nc-"` escrita lá era exactamente a divergência que o resto do módulo
# passa a vida a fechar.
MARCA_NOTA_CREDITO = "nc-"


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


async def _reservar(db, ext_ref: str, venda_id: str) -> Optional[str]:
    """A reserva atómica (passo 2). Devolve o `id` DA RESERVA que esta
    chamada criou, se ganhou a corrida; `None` se perdeu (já existe uma
    reserva para esta `ext_ref`) — é o índice único em `ext_ref` (db.py) que
    decide, não uma leitura antes de inserir.

    **Devolve a identidade e já não um `True`**, e é daqui que sai a
    correcção da sexta revisão. A `ext_ref` é determinística — é isso que a
    torna útil para a idempotência, e é exactamente isso que a impede de ser
    única NO TEMPO: apagada uma reserva, a tentativa seguinte cria outra
    rigorosamente igual. Um filtro que só diga `{"ext_ref": ...}` prende a
    FORMA, e quem escreve por ele actua sobre a reserva que lá estiver, não
    sobre a sua. Quem ganha aqui sai com um uuid4 que nenhuma reserva futura
    da mesma venda pode partilhar, e é por ele — nunca pela `ext_ref`
    sozinha — que `_libertar_reserva`, `_marcar_reserva_incerta` e
    `_ligar_venda_ao_documento` dizem "a MINHA"."""
    reserva_id = str(uuid.uuid4())
    try:
        await db[COLECOES["refs_fiscais"]].insert_one({
            "id": reserva_id,
            "ext_ref": ext_ref,
            "venda_id": venda_id,
            "criado_em": _agora(),
        })
        return reserva_id
    except DuplicateKeyError:
        return None


async def _libertar_reserva(db, ext_ref: str, reserva_id: Optional[str]) -> bool:
    """Remove A RESERVA DE QUEM CHAMA (a que tem este `id`) — chamado quando
    algo falha DEPOIS de reservar (nunca depois de o Vendus confirmar que
    emitiu, ver ConflitoDocumentoFiscal), para a próxima tentativa poder
    reservar de novo em vez de ficar presa atrás de uma reserva órfã. `True`
    se apagou; `False` se a reserva que estava na `ext_ref` já não era a de
    quem chama — e nesse caso NADA foi apagado.

    **Porque é que este apagar deixou de ser incondicional.** Apagava por
    `{"ext_ref": ...}` e mais nada, com esta justificação: «quem chama isto
    ACABOU de ganhar a reserva e é dono dela; para apagar a reserva ERRADA, a
    sua teria de ter desaparecido primeiro, e ninguém lha pode tirar — o
    índice único garante que não há segunda reserva desta ext_ref enquanto a
    dela existir, e a rota do gestor recusa-se a apagar tanto uma reserva
    recente (é uma emissão a decorrer) como uma cuja retoma esteja
    reclamada». A primeira metade é verdade. A SEGUNDA é falsa nas duas
    pontas, e é-o precisamente para uma RETOMA:

    - «uma reserva recente» — a guarda da idade mede o `criado_em` da reserva
      ORIGINAL. Numa `incerta` das 20h retomada à meia-noite isso são HORAS:
      os `_SEGUNDOS_DE_EMISSAO_NORMAL` passam sem sequer se aproximarem do
      limite. É o mesmo relógio trocado que obrigou `em_retoma_desde` a
      existir.
    - «uma cuja retoma esteja reclamada» — a rota NÃO recusa uma retoma
      reclamada: recusa uma reclamada há MENOS de
      `_SEGUNDOS_DE_RETOMA_NORMAL`. Passados esses, o gestor pode libertá-la,
      e é para isso que essa saída existe (um processo morto num deploy). Só
      que esse limite é a SOMA EXACTA do pior caso da retoma, sem margem
      nenhuma: uma retoma que lá chegue ainda está viva, e a próxima coisa
      que faz — se o Vendus não tiver o documento — é chamar isto.

    Um comentário que justifica uma segurança que não existe é pior do que
    não haver comentário nenhum; daí este parágrafo, e daí o `id`.

    O cenário, medido sobre as rotas reais: reserva `incerta` das 20h;
    FINALIZAR nº1 reclama a retoma e fica pendurado no Vendus; o gestor abre
    a lista de presas, confirma no Vendus que não existe documento e LIBERTA
    (e apaga a reserva CERTA — era mesmo aquela que ele viu); FINALIZAR nº2
    ganha uma reserva NOVA e está a EMITIR; só então a retoma nº1 recebe o
    timeout, verifica (nada) e chama isto — que apagava a reserva NOVA;
    FINALIZAR nº3 encontra a `ext_ref` livre e emite outra vez →
    «EMISSÕES REAIS pedidas ao Vendus -> 2 ['FS 2026/901', 'FS 2026/902']»,
    duas Faturas Simplificadas REAIS da mesma venda.

    **`id`, e é a mesma correcção de `_libertar_reserva_se_intacta`** (a
    função ao lado, que tinha o defeito à vista): o `id` é o uuid4 que
    `_reservar` escreve no próprio insert — o único campo que uma reserva
    NOVA da mesma venda não pode partilhar com a que quem chama ganhou. O que
    NÃO se prende aqui são os campos de FORMA (`em_retoma`, `documento_id`)
    que essa função prende, e é deliberado: a pergunta dela é «ninguém lhe
    mexeu desde que a li?», a daqui é só «é a minha?» — e quem chama isto
    pode ter sido o próprio a marcá-la (a retoma reclama primeiro e só depois
    liberta).

    É o `deleted_count` que decide, nunca a leitura de cima."""
    resultado = await db[COLECOES["refs_fiscais"]].delete_one({
        "ext_ref": ext_ref,
        "id": reserva_id,
    })
    if resultado.deleted_count == 1:
        return True
    logger.warning(
        "[faturacao] a reserva de %s já não era a desta tentativa (id=%r) — "
        "não se apagou nada. Quem está na ext_ref é outra emissão, e "
        "apagar-lhe a reserva era autorizar-lhe uma segunda Fatura "
        "Simplificada da mesma venda.", ext_ref, reserva_id,
    )
    return False


async def _libertar_reserva_se_intacta(db, ext_ref: str, reserva: Dict) -> bool:
    """Apaga a reserva SÓ SE ela continuar exactamente como estava quando a
    decisão de a apagar foi tomada. `True` se apagou; `False` se alguém lhe
    mexeu entretanto — e nesse caso NADA foi apagado.

    **Porquê condicional, e não `_libertar_reserva`.** A rota de gestão
    (`libertar_reserva_presa`) decide sobre a reserva que leu no PRIMEIRO
    passo e só depois de mais três `await`s (o documento, a venda, a sessão)
    é que apagava — incondicionalmente. Uma retoma que reclamasse dentro
    dessa janela levava com a reserva apagada por baixo de uma emissão que
    estava, nesse instante, a falar com o Vendus. Reproduzido em processo,
    com a saída medida: «1. gestor: libertar LEU a reserva → em_retoma=None
    / 3. retoma: EMISSÃO REAL nº1 a caminho do Vendus / 4. estado real da
    reserva AGORA: em_retoma=True / 5. gestor: libertar APAGA a reserva /
    7. operadora: 2.º FINALIZAR → emitida nº FS 2026/902» — duas Faturas
    Simplificadas REAIS da mesma venda.

    É o `deleted_count` que decide esta corrida, nunca a leitura de cima —
    exactamente como o `matched_count` decide a de `cancelar_venda`
    (`venda.py`) e a de `_reclamar_retoma`. Uma decisão tomada sobre uma
    fotografia tem de ser aplicada com uma escrita que exija que a
    fotografia ainda seja verdade.

    **`id`: a IDENTIDADE daquela reserva, e porque é que faltava.** A versão
    anterior desta função descrevia só a FORMA de uma reserva intacta
    (`em_retoma`/`em_retoma_desde`/`documento_id`) — e uma reserva NOVA tem
    exactamente essa forma. A `ext_ref` é determinística (`pos-{loja}-
    {sessão}-{venda}`), por isso NÃO é única no tempo: libertada a reserva
    velha, a tentativa seguinte cria outra com a MESMA `ext_ref` e sem marca
    nenhuma, porque `_reservar` insere só id/ext_ref/venda_id/criado_em.
    Reproduzido em processo, com a saída medida: «2. libertar leu a reserva
    r-velha / 3. FINALIZAR nº1 → o Vendus recusa com 4xx → a reserva velha é
    libertada / 5. FINALIZAR nº2 → reserva NOVA, emissão a caminho do Vendus
    / 7. APAGOU 1 reserva(s) [a NOVA] / 10. FINALIZAR nº3 → emitida nº FS
    2026/902» → **duas Faturas Simplificadas REAIS da mesma venda**. O filtro
    fechava o defeito que tinha à frente e abria uma versão mais estreita de
    si próprio.

    **Porquê o `id` e não o `criado_em`** (as duas hipóteses reais): o `id` é
    um uuid4 escrito por `_reservar` no próprio insert — é a identidade do
    documento, e é o ÚNICO campo que uma reserva nova, criada para a mesma
    venda, não pode partilhar com a que o gestor viu. O `criado_em` é um
    relógio: mede *quando*, não *qual*. Duas reservas da mesma venda criadas
    no mesmo instante ISO seriam indistinguíveis por ele, e uma retoma
    mantém-no o da reserva ORIGINAL (é por isso que `em_retoma_desde` teve de
    existir) — usar um relógio como identidade foi exactamente o erro que a
    guarda da idade cometeu, e que custou duas faturas reais. Uma reserva sem
    `id` (dados anteriores a este campo) casa com `{"id": None}`, mas uma
    reserva NOVA nunca, porque `_reservar` põe-lhe sempre um uuid — a única
    coisa que pode apagar é outra igualmente sem identidade.

    **E os três campos de forma continuam lá**, porque respondem a outra
    pergunta — "ninguém lhe mexeu?" — e a identidade sozinha não a responde:

    - `em_retoma` e `em_retoma_desde` — o par que `_reclamar_retoma` escreve
      de uma vez. Passa-se o valor LIDO (não `None` à força): uma retoma
      ABANDONADA há muito, que a rota já decidiu tratar como morta
      (`_retoma_em_curso` devolveu `False`), continua a poder ser libertada,
      que é a única saída dessa conta; o que o filtro proíbe é que a marca
      MUDE entre a decisão e a escrita.
    - `documento_id` — se uma retoma reclamou, emitiu e ACABOU dentro da
      janela, a marca de retoma volta a `None` (`_limpar_incerta_resolvida`)
      e o par acima já não a apanhava; o que fica é o documento carimbado na
      reserva. Apagar a reserva de uma venda que passou a `emitida` era
      deitar fora a própria peça que sustenta a idempotência."""
    resultado = await db[COLECOES["refs_fiscais"]].delete_one({
        "ext_ref": ext_ref,
        "id": reserva.get("id"),
        "em_retoma": reserva.get("em_retoma"),
        "em_retoma_desde": reserva.get("em_retoma_desde"),
        "documento_id": None,
    })
    return resultado.deleted_count == 1


async def _marcar_reserva_incerta(db, ext_ref: str, reserva_id: Optional[str]) -> bool:
    """Marca A RESERVA DE QUEM CHAMA como incerta em vez de a libertar — ver
    VerificacaoFiscalIncerta. A diferença para `_libertar_reserva` é
    exactamente o ponto desta defesa: libertar convidava a tentativa
    seguinte a reservar de novo e emitir sem mais nenhuma pergunta; marcar
    incerta obriga-a a verificar primeiro (`_retomar_reserva_incerta`).
    `True` se marcou; `False` se a reserva que lá estava já não era a sua.

    **`id` pela mesma razão de `_libertar_reserva`**, e era o OUTRO dos dois
    últimos sítios do núcleo onde uma escrita prendia a forma (`ext_ref`) e
    não a identidade. O estrago é o simétrico do de lá, e sai da mesma
    coreografia (a retoma que se arrasta e acorda depois de a reserva ter
    sido substituída): em vez de APAGAR a reserva de uma emissão em voo,
    marcava-a `incerta` — e uma reserva incerta é um convite escrito à
    tentativa seguinte para a RETOMAR. Medido: «reservas no Mongo depois de a
    retoma acabar: [(reserva nova, 'incerta')] / FINALIZAR nº3 -> emitida nº
    FS 2026/902» com a FS 2026/901 já em voo — duas Faturas Simplificadas
    REAIS da mesma venda.

    É o `matched_count` que decide, nunca a leitura de cima."""
    resultado = await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref, "id": reserva_id}, {"$set": {"incerta": True}}
    )
    if resultado.matched_count == 1:
        return True
    logger.warning(
        "[faturacao] a reserva de %s já não era a desta tentativa (id=%r) — "
        "não se marcou nada como incerta. Marcar a reserva de outra emissão "
        "era convidar a tentativa seguinte a retomá-la e a emitir por cima "
        "de uma FS que pode estar a nascer neste instante.",
        ext_ref, reserva_id,
    )
    return False


async def _reclamar_retoma(db, ext_ref: str, carimbo: Optional[str] = None) -> bool:
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
    apontar para a outra).

    **`carimbo`**: quem chama pode escolher o valor de `em_retoma_desde` para
    o guardar e, no fim, desfazer só a reclamação que fez — ver o `finally`
    de `_retomar_reserva_incerta`. Sem ele o carimbo é o de agora, como
    sempre foi.

    **Porque é que este filtro NÃO precisa de prender a identidade da
    reserva** (ao contrário de `_libertar_reserva_se_intacta` e
    `_limpar_incerta_se_intacta`): esta escrita não aplica uma decisão tomada
    sobre uma reserva LIDA antes — a condição `incerta: True, em_retoma: None`
    é ela própria toda a licença para agir, e é verdadeira ou falsa no
    instante da escrita. Se a reserva lida em `finalizar_venda` tiver sido
    entretanto substituída por outra, o que acontece é o correcto: ou a nova
    também está incerta e por reclamar (e reclamá-la é exactamente o que a
    retoma serve para fazer — verificar no Vendus antes de emitir seja o que
    for), ou não está, e então não se reclama nada."""
    resultado = await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref, "incerta": True, "em_retoma": None},
        {"$set": {
            "em_retoma": True,
            "em_retoma_desde": carimbo if carimbo is not None else _agora(),
        }},
    )
    return resultado.matched_count == 1


async def _limpar_incerta_se_intacta(db, ext_ref: str, reserva: Dict) -> bool:
    """O mesmo que `_limpar_incerta_resolvida`, mas SÓ se a marca de retoma
    continuar a ser a que quem chama viu. `True` se limpou.

    É a mesma forma de defeito de `_libertar_reserva_se_intacta`, na outra
    rota de gestão: `reconciliar_reserva_presa` pergunta `_retoma_em_curso`
    sobre a reserva lida no primeiro passo e só escreve MUITO depois — pelo
    meio faz uma chamada HTTP ao Vendus, que são SEGUNDOS e não
    milissegundos. Uma retoma que reclame nessa janela está a falar com o
    Vendus neste instante, e a limpeza incondicional apagava-lhe a marca da
    reclamação por baixo — precisamente a marca que impede `libertar` (e a
    própria reconciliação) de mexer numa emissão em voo.

    Quem NÃO limpa não faz nada e diz-o no log: a reserva fica ao cuidado de
    quem a reclamou, que a resolve no seu `finally`
    (`_retomar_reserva_incerta`). A venda já está `emitida` e a reserva já
    leva o `documento_id` — não fica presa nem aparece na listagem de
    presas.

    **`id` pela mesma razão de `_libertar_reserva_se_intacta`**, e é a mesma
    janela: a reserva lida à entrada da rota pode ter sido libertada e
    SUBSTITUÍDA por outra durante a chamada HTTP ao Vendus (a `ext_ref` é
    determinística, logo repete-se). Aqui o estrago é mais surdo do que o do
    `delete` — limpar `em_retoma`/`em_retoma_desde` numa reserva ALHEIA
    apaga-lhe a marca da reclamação, e é essa marca que impede `libertar` (e
    esta própria rota) de mexer numa emissão em voo: em vez de matar a
    emissão, abria-lhe a porta a quem a matasse a seguir."""
    resultado = await db[COLECOES["refs_fiscais"]].update_one(
        {
            "ext_ref": ext_ref,
            "id": reserva.get("id"),
            "em_retoma": reserva.get("em_retoma"),
            "em_retoma_desde": reserva.get("em_retoma_desde"),
        },
        {"$set": {"incerta": False, "em_retoma": None, "em_retoma_desde": None}},
    )
    if resultado.matched_count == 1:
        return True
    logger.warning(
        "[faturacao] reconciliação de %s: a marca de retoma da reserva mudou "
        "entre a leitura e a limpeza — não se lhe tocou (a emissão que a "
        "reclamou é que a resolve).", ext_ref,
    )
    return False


async def _limpar_incerta_resolvida(db, ext_ref: str, carimbo: str) -> None:
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
    que só pode induzir em erro quem o leia a seguir (`_retoma_em_curso`).

    **`carimbo` é obrigatório, e é a identidade da RECLAMAÇÃO** — o valor que
    esta mesma retoma escreveu em `em_retoma_desde` ao reclamar. A escrita é
    condicionada a ele pela mesma razão que o `delete` de
    `_libertar_reserva_se_intacta`: entre reclamar e chegar aqui pode ter
    passado uma chamada ao Vendus, e a `ext_ref` é determinística — uma
    reserva NOVA da mesma venda casaria com um filtro que só diga
    `{"ext_ref": ...}`, e limpar-lhe as marcas era apagar a reclamação de
    quem estivesse a emitir nesse instante. Um valor obrigatório (e não um
    `None` que significasse "limpa o que lá estiver") é o que impede a
    próxima chamada de reintroduzir o defeito sem dar por isso."""
    await db[COLECOES["refs_fiscais"]].update_one(
        {"ext_ref": ext_ref, "em_retoma": True, "em_retoma_desde": carimbo},
        {"$set": {"incerta": False, "em_retoma": None, "em_retoma_desde": None}},
    )


def _conta_a_faturar(venda: Dict) -> Dict:
    """O que, nesta venda, DEFINE a fatura: as linhas e os dois descontos
    globais — e mais nada. É o critério de comparação de
    `_garante_conta_inalterada`, e a escolha do critério é o ponto todo.

    **Porquê estes três campos.** São exactamente os que `_itens_vendus` e
    `_totais` lêem da venda, e nenhum outro: as linhas produzem os itens que
    vão para o Vendus, e as linhas mais os descontos globais produzem o total
    contra o qual a soma dos pagamentos foi validada. Mudar um deles muda a
    fatura, o total, ou os dois; mudar qualquer coisa fora deles não muda
    nem uma coisa nem outra.

    **As duas comparações erradas, uma para cada lado.**

    - *O documento inteiro* recusaria emissões perfeitamente boas, com o
      cliente à frente. A compensação de `venda.py::cancelar_venda` repõe
      `cancelada_em: None` e `cancelada_por: None` numa venda que acabou por
      NÃO ser cancelada (ordem 3 em `_garante_venda_ainda_aberta`): o
      retrato não trazia esses campos, a releitura traz-nos a `None`, e a
      fatura é rigorosamente a mesma. O mesmo vale para `pagamentos` e
      `cliente_nif`, que uma tentativa anterior pode ter gravado.
    - *Só o total* deixaria passar uma troca de linhas com a mesma soma:
      dois açaís de 8,99 € trocados por um artigo de 17,98 €, ou — pior,
      porque nem no total se vê — uma linha de 13 % (INT) trocada por outra
      de 23 % (NOR) ao mesmo preço. Saía uma Fatura Simplificada REAL com
      artigos e IVA que ninguém confirmou, entregue à AT.

    Comparam-se os campos CRUS e não os itens derivados (`_itens_vendus`):
    derivá-los aqui obrigava a chamar `_linha_vendus`, que levanta um
    HTTPException 422 numa linha com dados impossíveis — e esse 422, atirado
    de dentro do núcleo depois de a reserva já estar ganha, saltava por cima
    de todos os `except` de `finalizar` e deixava a reserva órfã a trancar a
    conta. Os campos crus não fazem contas nenhumas e não levantam nada.

    `or []` / `.get(...)`: uma venda sem `linhas` e outra com `linhas: []`
    faturam as duas exactamente o mesmo (nada), e uma venda a que falte o
    campo do desconto nunca pode cair num KeyError aqui."""
    return {
        "linhas": venda.get("linhas") or [],
        "desconto_global_pct": venda.get("desconto_global_pct"),
        "desconto_global_eur": venda.get("desconto_global_eur"),
    }


async def _garante_conta_inalterada(
    db, ext_ref: str, retrato: Dict, actual: Dict, reserva_id: Optional[str]
) -> None:
    """Depois de GANHAR a reserva e de confirmar que venda e sessão continuam
    abertas: se a CONTA mudou entre o retrato e a reserva, liberta a reserva
    e aborta — sem emitir. Ver `ContaAlteradaDepoisDeConfirmada`, onde estão
    o cenário e a razão de não se recomporem os itens.

    `actual` é a releitura que `_garante_venda_ainda_aberta` já fez, passada
    para aqui em vez de se ler a venda outra vez: duas leituras eram duas
    fotografias de dois instantes, e as perguntas "ainda está aberta?" e "é a
    mesma conta?" têm de ser respondidas sobre a MESMA."""
    antes = _conta_a_faturar(retrato)
    depois = _conta_a_faturar(actual)
    if antes != depois:
        # Ainda não se falou com o Vendus: libertar é seguro E necessário,
        # pelo mesmo motivo de `_garante_venda_ainda_aberta` — sem isto
        # ficava uma reserva órfã a trancar uma conta que a operadora tem
        # precisamente de voltar a finalizar a seguir. `reserva_id`: liberta-se
        # A NOSSA, nunca "a que estiver na ext_ref" (ver `_libertar_reserva`).
        await _libertar_reserva(db, ext_ref, reserva_id)
        # Diz-se QUE campos mudaram, e não só que "a conta mudou": quem for
        # ver ao log porque é que aquela conta deu 409 precisa de saber se
        # foram as linhas ou o desconto (das linhas dá-se a contagem, que é
        # a única parte que cabe numa linha de log).
        mudou = ", ".join(
            "%s (%d → %d)" % (campo, len(antes[campo]), len(depois[campo]))
            if campo == "linhas" else
            "%s (%r → %r)" % (campo, antes[campo], depois[campo])
            for campo in antes if antes[campo] != depois[campo]
        )
        raise ContaAlteradaDepoisDeConfirmada(
            "A conta da venda %s mudou entre o retrato que a rota leu e a "
            "reserva — mudou: %s. A fatura ia sair com os itens e o total "
            "antigos; a reserva %s foi libertada e NADA foi enviado ao "
            "Vendus." % (retrato.get("id"), mudou, ext_ref)
        )


async def _garante_venda_ainda_aberta(
    db, ext_ref: str, venda_id: str, reserva_id: Optional[str]
) -> Dict:
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
    lê-se pelo `sessao_id` DA RELEITURA, pela mesma razão.

    Devolve a releitura da venda para `_garante_conta_inalterada` a comparar
    com o retrato: a pergunta que se segue ("é a mesma conta?") tem de ser
    respondida sobre a MESMA fotografia que esta, não sobre uma segunda
    leitura de outro instante."""
    actual = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if actual is None or actual.get("estado") != "aberta":
        # Ainda não se falou com o Vendus, por isso libertar é seguro E
        # necessário: sem isto ficava uma reserva órfã a trancar para sempre
        # uma conta que já ninguém pode emitir nem cancelar.
        await _libertar_reserva(db, ext_ref, reserva_id)
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
    if sessao is not None and sessao.get("estado") == "a_fechar":
        # Um fecho A DECORRER, e não um fecho FEITO: a decisão é a mesma
        # (não se emite, a reserva liberta-se, nada vai ao Vendus) mas o
        # facto é outro, e é a operadora que o vai ler — ver
        # `SessaoEmFechoAgora`. A reserva liberta-se também por uma razão do
        # outro lado: enquanto ela existir, o fecho recusa-se a si próprio
        # (`caixa.py::_venda_com_emissao_viva`) e a caixa não fecha.
        await _libertar_reserva(db, ext_ref, reserva_id)
        raise SessaoEmFechoAgora(
            "A sessão de caixa %r da venda %s está a meio de um fecho "
            "(estado=%r) — o Z está a ser calculado neste instante. A reserva "
            "%s foi libertada e NADA foi enviado ao Vendus; a conta continua "
            "aberta e faturável se o fecho não for por diante." % (
                actual.get("sessao_id"), venda_id,
                sessao.get("estado"), ext_ref,
            )
        )
    if sessao is None or sessao.get("estado") != "aberta":
        await _libertar_reserva(db, ext_ref, reserva_id)
        raise SessaoJaNaoAberta(
            "A sessão de caixa %r da venda %s já não está aberta (estado=%r) — "
            "o fecho entrou entre a validação e a reserva. A reserva %s foi "
            "libertada e NADA foi enviado ao Vendus." % (
                actual.get("sessao_id"), venda_id,
                (sessao or {}).get("estado"), ext_ref,
            )
        )

    return actual


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


def _mesmo_documento(gravado: Dict, bruto: Dict) -> bool:
    """O documento já gravado e o que o Vendus acaba de devolver são o MESMO
    documento fiscal? Compara-se a identidade que a AT reconhece — o id do
    Vendus e o ATCUD — nunca o total nem o número (dois documentos
    diferentes da mesma conta têm o mesmo total, e é precisamente esse o
    caso que isto tem de apanhar).

    Compara em texto: o id do Vendus vem como inteiro na criação e pode vir
    como string numa leitura, e `501 != "501"` diria "documentos
    diferentes" sobre o mesmo documento — um alarme falso na retoma normal,
    que é o caminho de recuperação mais usado."""
    def _texto(valor):
        return "" if valor is None else str(valor).strip()

    return (
        _texto(gravado.get("vendus_document_id")) == _texto(bruto.get("id"))
        and _texto(gravado.get("atcud")) == _texto(bruto.get("atcud"))
    )


async def _gravar_documento(
    db, ext_ref: str, venda: Dict, bruto: Dict, *, reserva_id: Optional[str]
) -> Dict:
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
    # `emitido_em` é o instante em que a AT recebeu o documento QUANDO O
    # VENDUS O DISSER (`vendus/emissao._instante_do_vendus`, nos documentos
    # trazidos por verificação ou reconciliação); para um documento criado
    # agora mesmo, o instante actual É esse instante. Nunca uma data
    # inventada a partir de um campo ilegível: nesse caso o Vendus não manda
    # `emitido_em` nenhum, cai-se aqui, e o aviso já ficou no log de lá.
    emitido_em = bruto.get("emitido_em") or _agora()
    documento = {
        "id": str(uuid.uuid4()),
        "vendus_document_id": bruto.get("id"),
        "atcud": bruto.get("atcud"),
        "numero": bruto.get("numero"),
        "total": bruto.get("total"),
        # O CONTRATO COM O DASHBOARD: `dashboard.py::_campo_valor` soma
        # `total_bruto` (com IVA) ou `total_liquido` (sem) — nenhum dos dois
        # era gravado aqui, e por isso toda a receita das 5 lojas valia
        # 0,00 €. `total` mantém-se tal e qual: é o que o ecrã do POS lê.
        "total_bruto": bruto.get("total_bruto"),
        "total_liquido": bruto.get("total_liquido"),
        # O outro campo que `dashboard.py::_valor_documento` lê de CADA
        # documento: o tipo (uma nota de crédito conta com sinal negativo).
        # Escreve-se com todas as letras em vez de se ficar pelo valor que o
        # campo ausente dá por omissão — este POS só emite Faturas
        # Simplificadas hoje, mas uma linha de documento fiscal que não diz o
        # que é obriga quem a soma a adivinhar, e no dia em que houver notas
        # de crédito a adivinha muda de sinal.
        #
        # `anulado` NÃO se grava, e é deliberado: o ausente já significa "não
        # anulado" nos dois lados do Dashboard (`_valor_documento` e o
        # `$ne: True` de `_existe_venda`), e lá está um teste a guardar essa
        # ausência — gravá-lo a `False` não acrescentava nada e obrigava a
        # rever aquela consulta.
        "tipo": "FS",
        "modo": bruto.get("modo"),
        # **O talão certificado, guardado com a fatura.** O Vendus devolve-o já
        # em ESC/POS na resposta da emissão (`vendus/emissao.py`, `output=escpos`)
        # e isto deitava-o fora: o dicionário era construído campo a campo e
        # este não estava na lista. Reimprimir o talão de um cliente que voltou
        # obrigava a ir outra vez ao Vendus — mais uma chamada por reimpressão,
        # e nada feito com ele em baixo.
        #
        # Guardá-lo NÃO o torna a identidade do documento: se o `output` vier
        # estragado, `_talao_de` devolve `None` e a emissão continua boa — o que
        # se perde é o papel, nunca o registo da fatura (ver a docstring de lá).
        "talao_escpos": bruto.get("talao_escpos"),
        "ext_ref": ext_ref,
        "venda_id": venda["id"],
        "loja_id": venda["loja_id"],
        # **O NIF de quem pediu a fatura, GRAVADO NO DOCUMENTO** e não só na
        # venda. É uma cópia de propósito: sem ela, listar os clientes ou somar
        # as vendas por cliente obriga a ler as vendas TODAS para descobrir a
        # que NIF pertence cada documento — uma junção por linha, cada vez que
        # alguém abre o ecrã. Com ela, a pergunta responde-se no documento, que
        # é onde o dinheiro está.
        #
        # A venda continua a ser a fonte: isto escreve-se a partir dela, no
        # instante da emissão, e nunca se edita depois. `None` na esmagadora
        # maioria — que é o Consumidor Final.
        "cliente_nif": venda.get("cliente_nif"),
        "emitido_em": emitido_em,
    }
    try:
        await db[COLECOES["documentos"]].insert_one(dict(documento))
    except DuplicateKeyError:
        existente = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
        if existente is not None and _mesmo_documento(existente, bruto):
            # Uma tentativa anterior desta MESMA venda já gravou o MESMO
            # documento (ex.: um retry depois de a resposta se ter
            # perdido) — reutiliza-o, sem inventar um segundo.
            documento = existente
        elif existente is not None:
            # Existe já um documento para esta `ext_ref` mas é OUTRO
            # documento fiscal (id/ATCUD diferentes) — ou seja, a mesma
            # venda tem DUAS faturas reais entregues à AT. Antes de o
            # índice único de `ext_ref` existir isto passava em silêncio
            # (duas linhas em `fat_documentos`, a venda a apontar para uma,
            # o ecrã a mostrar a que o Mongo calhasse); reutilizar "o que já
            # lá estava" seria a mesma coisa, com o segundo ATCUD a
            # desaparecer sem ninguém saber. É alto, e é para investigação
            # manual — a reserva NÃO se liberta.
            raise ConflitoDocumentoFiscal(
                "A referência externa %s já tem gravado o documento nº %r "
                "(id=%r, ATCUD=%r) e o Vendus devolveu agora um DIFERENTE "
                "(id=%r, ATCUD=%r) — são duas Faturas Simplificadas reais da "
                "MESMA venda. Nada foi sobreposto; isto precisa de uma nota "
                "de crédito e de investigação manual." % (
                    ext_ref, existente.get("numero"),
                    existente.get("vendus_document_id"), existente.get("atcud"),
                    bruto.get("id"), bruto.get("atcud"),
                )
            )
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

    await _ligar_venda_ao_documento(
        db, ext_ref, venda["id"], documento, reserva_id=reserva_id)
    return documento


async def _ligar_venda_ao_documento(
    db, ext_ref: str, venda_id: str, documento: Dict, *, reserva_id: Optional[str]
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
    #
    # `id` — o TERCEIRO sítio com a porta de `_libertar_reserva`, e o mais
    # surdo dos três porque não dá erro nenhum: sem ele, este `$set` carimbava
    # com o documento DESTA emissão a reserva de OUTRA — a `ext_ref` é
    # determinística, logo repete-se, e a reserva desta tentativa pode ter
    # sido libertada e substituída enquanto se falava com o Vendus. O campo
    # diz "o documento que saiu DESTA reserva", e passava a dizer uma mentira
    # sobre a reserva de uma emissão que ainda está em voo: é por ele que
    # `listar_reservas_presas` faz a primeira triagem (`{"documento_id":
    # None}`, antes sequer da junção com a venda), e é ele que um gestor lê
    # quando vai perceber, semanas depois, que documento é que saiu de que
    # tentativa. `reserva_id` a `None` (a reconciliação de uma venda que já
    # não tem reserva nenhuma) não casa com nada: não há o que carimbar, e é
    # isso mesmo que acontece.
    try:
        await db[COLECOES["refs_fiscais"]].update_one(
            {"ext_ref": ext_ref, "id": reserva_id},
            {"$set": {"documento_id": documento["id"]}},
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
    *,
    reserva_id: Optional[str],
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

    E, fora do timeout, a pergunta que decide tudo o resto: **sabemos que o
    Vendus não criou nada?** Só a lista curta de
    `_ERROS_COM_PROVA_DE_QUE_NADA_SAIU` é prova disso e liberta a reserva.
    Tudo o resto — em particular o que rebenta DEPOIS de uma resposta 2xx, a
    ler o corpo — marca a reserva incerta e sai como
    `DesfechoDaEmissaoIncerto`. Era aqui que estava o segundo defeito desta
    ronda: um `except Exception` largo que libertava a reserva de uma fatura
    que JÁ existia.

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
        # **E no dicionário que segue viagem, não só na base de dados.**
        #
        # O `venda` que esta função recebeu foi lido ANTES desta escrita, e é
        # ele — não uma releitura — que chega a `_gravar_documento` lá em
        # baixo. Sem esta linha, `venda.get("cliente_nif")` devolvia o valor
        # de antes (`None`) e o documento nascia sem o NIF que a operadora
        # tinha acabado de escrever.
        #
        # Medido em produção a 29/08: 16 vendas com NIF, 2 documentos com
        # NIF. As 14 dos dias em que as lojas faturaram a sério perderam-no
        # todas, e a zona de Clientes — que se deriva dos documentos — ficou
        # com duas linhas.
        #
        # A fatura fiscal nunca esteve em risco: o NIF vai para o Vendus pelo
        # `cliente_payload`, que não passa por aqui, e o talão que sai em
        # papel é o certificado que o Vendus devolve. O que se perdia era a
        # cópia local, que é a que responde à pergunta "quem são os meus
        # clientes?".
        venda.update(dados_pagamento)
    try:
        bruto = await emitir(ext_ref)
    except VendusIndisponivel as erro_emissao:
        try:
            encontrado = await verificar(ext_ref)
        except Exception as erro_verificacao:
            await _marcar_reserva_incerta(db, ext_ref, reserva_id)
            raise VerificacaoFiscalIncerta(
                "Timeout na emissão (ext_ref=%s) e a própria verificação por "
                "referência externa também falhou (%s) — não é seguro "
                "concluir nada sobre se o Vendus criou o documento. A "
                "reserva foi mantida, marcada incerta; confirme no Vendus "
                "antes de repetir." % (ext_ref, erro_verificacao)
            ) from erro_emissao
        if encontrado is None:
            await _libertar_reserva(db, ext_ref, reserva_id)
            raise erro_emissao
        bruto = encontrado
    except _ERROS_COM_PROVA_DE_QUE_NADA_SAIU:
        # SÓ estes: cada um deles é uma PROVA de que o documento fiscal não
        # existe (ver `_ERROS_COM_PROVA_DE_QUE_NADA_SAIU`). Aqui a reserva
        # liberta-se, para a próxima tentativa (correcção de dados, nova
        # tentativa manual) poder reservar de novo, e o erro original sobe
        # tal e qual.
        await _libertar_reserva(db, ext_ref, reserva_id)
        raise
    except Exception as erro_desconhecido:
        # E tudo o resto — que é o defeito que esta lista fecha. O `except
        # Exception` que estava aqui libertava a reserva a dizer que
        # "sabemos que o Vendus NÃO criou nada": não sabemos. Ele apanhava
        # também o que rebenta DEPOIS de uma resposta 2xx, com o documento
        # fiscal já criado (`vendus/emissao.py`: o corpo que não se lê, o
        # `output` que não é base64, o `amount_gross` que não é número).
        # Medido: «documento fiscal REAL criado: FS 2026/900 →
        # JSONDecodeError → venda='aberta' | reservas=0 | fat_documentos=0»,
        # o ecrã a reler a venda, a receber `emissao_por_confirmar: False` e
        # a convidar a emitir outra vez — duas FS reais da mesma venda.
        #
        # Um erro que não sabemos classificar não liberta nada: marca a
        # reserva `incerta`, que é literalmente o que ela significa ("não se
        # sabe se a fatura saiu"), e obriga a tentativa seguinte a verificar
        # no Vendus antes de poder emitir (`_retomar_reserva_incerta`).
        await _marcar_reserva_incerta(db, ext_ref, reserva_id)
        raise DesfechoDaEmissaoIncerto(
            "A emissão desta venda (ext_ref=%s) falhou de uma forma que não "
            "permite concluir nada sobre o Vendus: %s: %s. Se a resposta "
            "chegou a sair de lá, o documento fiscal EXISTE. A reserva foi "
            "mantida, marcada incerta — confirme no Vendus antes de repetir." % (
                ext_ref, type(erro_desconhecido).__name__, erro_desconhecido,
            )
        ) from erro_desconhecido

    return await _gravar_documento(db, ext_ref, venda, bruto, reserva_id=reserva_id)


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
    # O carimbo desta reclamação, guardado ANTES de a escrever: é ele que
    # identifica a marca que este `finally` (e só ele) pode desfazer. Ver
    # `_limpar_incerta_resolvida`.
    carimbo = _agora()
    if not await _reclamar_retoma(db, ext_ref, carimbo):
        return await _esperar_documento_do_vencedor(
            db, ext_ref, esperar_efectivo, tentativas_espera, venda["id"]
        )

    # QUAL é a reserva que esta reclamação carimbou. `_reclamar_retoma` decide
    # a corrida (e não precisa da identidade para isso, ver a docstring dela),
    # mas as escritas que se seguem — libertar, marcar incerta, carimbar o
    # documento — precisam: a `ext_ref` é determinística e a reserva pode ser
    # substituída por outra enquanto esta retoma fala com o Vendus (segundos
    # de rede, até 300 s no pior caso). Esta leitura troca a identidade da
    # RECLAMAÇÃO (o `carimbo`, que é o que `_limpar_incerta_resolvida` já usa
    # como tal) pela identidade da RESERVA, que é a que aquelas três escritas
    # têm de prender — um uuid4 que nenhuma reserva futura pode repetir.
    #
    # Não encontrar nada significa que a reserva que acabámos de reclamar
    # desapareceu debaixo de nós: não se emite às cegas por cima de uma
    # ext_ref cujo dono já não sabemos qual é — cai-se no caminho de sempre de
    # quem não tem reserva, que lê o desfecho de quem lá está agora. Nada foi
    # enviado ao Vendus.
    reclamada = await db[COLECOES["refs_fiscais"]].find_one(
        {"ext_ref": ext_ref, "em_retoma": True, "em_retoma_desde": carimbo}
    )
    if reclamada is None:
        return await _esperar_documento_do_vencedor(
            db, ext_ref, esperar_efectivo, tentativas_espera, venda["id"]
        )
    reserva_id = reclamada.get("id")

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
            documento = await _gravar_documento(
                db, ext_ref, venda, encontrado, reserva_id=reserva_id)
        else:
            # A verificação correu bem e não encontrou nada: só agora é
            # seguro tentar emitir — com a MESMA rede de segurança de
            # sempre (se este timeout também falhar, a reserva volta a
            # ficar incerta, ver _emitir_e_gravar/_marcar_reserva_incerta),
            # e É esta tentativa que vai emitir de facto, por isso É o seu
            # dados_pagamento que deve gravar-se.
            documento = await _emitir_e_gravar(
                db, ext_ref, venda, emitir, verificar, dados_pagamento,
                reserva_id=reserva_id)
        resolvida = True
        return documento
    finally:
        # SEMPRE limpa a marca de retoma, em QUALQUER desfecho (resolvida,
        # continua incerta, ou até um erro que a própria _emitir_e_gravar
        # já tenha tratado à sua maneira) — sem isto, esta reclamação
        # ficava presa para sempre e nenhuma tentativa futura conseguia
        # voltar a reclamar: um impasse pior do que o defeito original.
        #
        # E limpa A RECLAMAÇÃO DESTA CHAMADA, identificada pelo `carimbo`
        # que ela própria escreveu — nunca "a marca de retoma que houver
        # nesta ext_ref". Entre reclamar e chegar aqui a reserva pode ter
        # sido libertada (`_emitir_e_gravar` liberta-a nos caminhos que
        # provam que nada saiu) e SUBSTITUÍDA por outra, porque a `ext_ref`
        # é determinística e a tentativa seguinte cria uma igual: limpar a
        # marca de retoma dessa era desarmar a defesa de uma emissão em voo
        # — a mesma forma de defeito que apagava a reserva errada em
        # `_libertar_reserva_se_intacta`, aqui a escrever em vez de apagar.
        if resolvida:
            await _limpar_incerta_resolvida(db, ext_ref, carimbo)
        else:
            await db[COLECOES["refs_fiscais"]].update_one(
                {"ext_ref": ext_ref, "em_retoma": True, "em_retoma_desde": carimbo},
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

    # A IDENTIDADE da reserva que esta tentativa ganhou (`None` = perdeu a
    # corrida). É ela que acompanha todas as escritas seguintes: sem ela,
    # cada uma actuava sobre "a reserva que estiver nesta ext_ref", que pode
    # já ser a de outra tentativa (ver `_reservar`).
    reserva_id = await _reservar(db, ext_ref, venda["id"])
    if reserva_id is not None:
        # Ganhar a reserva não chega: a venda que temos em mãos é o retrato de
        # ANTES da validação toda, e nessa janela pode ter mudado de duas
        # maneiras diferentes — o ESTADO (cancelada, ou a caixa fechada: ver
        # `_garante_venda_ainda_aberta`, que percorre as ordens possíveis uma
        # a uma) e a CONTA em si (linhas e descontos: ver
        # `ContaAlteradaDepoisDeConfirmada`). As duas perguntas, sobre a mesma
        # releitura, ANTES de qualquer chamada ao Vendus.
        actual = await _garante_venda_ainda_aberta(
            db, ext_ref, venda["id"], reserva_id)
        await _garante_conta_inalterada(db, ext_ref, venda, actual, reserva_id)
        return await _emitir_e_gravar(
            db, ext_ref, venda, emitir, verificar, dados_pagamento,
            reserva_id=reserva_id)

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


def _e_nota_de_credito(documento: Dict, prefixo_ext_ref: str) -> bool:
    """Se este documento do Vendus é uma NOTA DE CRÉDITO — o dinheiro dele
    SAIU da gaveta, não entrou.

    Duas perguntas e não uma, porque as duas fontes são independentes: o
    `type` é do Vendus (é o que lá foi gravado, `vendus/emissao.py` envia
    `type: "NC"`) e a marca da `ext_ref` é NOSSA
    (`fiscal.MARCA_NOTA_CREDITO`, o `nc-` que `nota_credito.
    ext_ref_da_intencao` põe a seguir ao prefixo da sessão). Basta uma delas
    dizer que é: entre contar uma devolução como venda e contar uma venda
    como devolução, os dois erros são caros, mas o primeiro é o que já custou
    — e um `type` que o Vendus deixe de devolver não pode desligar isto em
    silêncio."""
    if str(documento.get("type") or "").strip().upper() == "NC":
        return True
    resto = str(documento.get("external_reference") or "")[len(prefixo_ext_ref):]
    return resto.startswith(MARCA_NOTA_CREDITO)


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
    com `vendas_dinheiro_local`; um aviso claro se não bater.

    **O SINAL de cada documento vem do que ele é**, e não do sinal do
    `amount`. Uma nota de crédito leva o nosso prefixo de propósito (é o que
    a torna reconhecível como nossa e deste turno) e vai ao Vendus com
    `payments.amount` POSITIVO — é assim que a API do Vendus recebe a
    devolução. Somá-la como venda era o defeito medido: uma FS de 11,29 € em
    dinheiro mais a NC que a credita por inteiro davam «O Vendus regista
    22,58 € em dinheiro nesta sessão; as nossas vendas somam 0,00 €» — toda a
    noite com uma devolução em dinheiro acusava uma diferença falsa do DOBRO
    da devolução, e o único número que o fecho tem para a segunda opinião
    passava a ser ruído que a operadora aprendia a ignorar."""
    relevantes = [
        d for d in documentos_vendus
        if str(d.get("external_reference") or "").startswith(prefixo_ext_ref)
        and d.get("status") != "A"
    ]
    soma_vendus = 0.0
    for documento in relevantes:
        sinal = -1.0 if _e_nota_de_credito(documento, prefixo_ext_ref) else 1.0
        for pagamento in documento.get("payments") or []:
            if str(pagamento.get("id")) in ids_pagamento_dinheiro:
                soma_vendus += sinal * float(pagamento.get("amount") or 0)
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
    encontra nenhuma sessão, e o `if not sessao` já trata isso.

    A entrada da rota distingue os MESMOS dois casos que a releitura do
    núcleo (`_garante_venda_ainda_aberta`): um fecho A DECORRER (`a_fechar`)
    é uma espera de segundos e a conta continua faturável onde está; um fecho
    FEITO é o fim desta conta neste turno. A pergunta é a mesma; a resposta
    que a operadora lê é que não podia continuar a ser (ver
    `SessaoEmFechoAgora`)."""
    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": venda.get("sessao_id")})
    if sessao and sessao.get("estado") == "a_fechar":
        raise HTTPException(status_code=409, detail=_MSG_SESSAO_A_FECHAR_AGORA)
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

    # **O modo resolvido AQUI, e passado para baixo.** A emissão corre numa
    # thread (`asyncio.to_thread`) e não consegue ler a base de dados, que é
    # onde o botão do backoffice o guarda. Esta é a camada que consegue, e é
    # por isso que a resolução vive aqui — pela fonte única
    # (`modo.modo_efectivo`), a mesma que responde à faixa do POS.
    #
    # Se isto desaparecer, a emissão cai na variável de ambiente e o botão
    # passa a MENTIR: o ecrã diz `normal` e a fatura sai em `tests`, sem nada
    # partir. Há um teste a exigir esta chamada por essa razão exacta.
    modo_da_emissao = await modo_efectivo(db)

    with ClienteEmissaoVendus(conta.chave) as cliente_vendus:

        async def emitir(ref: str) -> Dict:
            return await asyncio.to_thread(
                cliente_vendus.criar_fatura_simplificada,
                linhas=itens,
                pagamentos=pagamentos_vendus,
                cliente=cliente_payload,
                external_reference=ref,
                register_id=register_id,
                modo=modo_da_emissao,
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
        except SessaoEmFechoAgora:
            # ANTES do `except SessaoJaNaoAberta` de propósito — é uma
            # subclasse dele, e o Python entrega ao primeiro que casar. O
            # fecho está a DECORRER: não há Z nenhum e a conta continua ali.
            # Trocar a ordem destes dois `except` volta a pôr a operadora a
            # ler que o turno acabou com a caixa aberta.
            logger.warning(
                "[faturacao] finalizar adiado: a caixa da venda %s está a "
                "meio de um fecho — a conta fica como está", venda_id,
            )
            raise HTTPException(status_code=409, detail=_MSG_SESSAO_A_FECHAR_AGORA)
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
        except ContaAlteradaDepoisDeConfirmada as e:
            # A conta mudou dentro da janela de validação (ver
            # `ContaAlteradaDepoisDeConfirmada`). Também aqui nada saiu para o
            # Vendus — e não há nada de errado a resolver: a operadora vê a
            # conta como ela está agora e finaliza outra vez. O detalhe
            # técnico fica no log, não no ecrã do balcão — e vai INTEIRO, com
            # os campos que mudaram: sem ele, quem for ao log perceber porque
            # é que aquela conta deu 409 fica a saber só que "mudou".
            logger.warning("[faturacao] finalizar abortado: %s", e)
            raise HTTPException(status_code=409, detail=_MSG_CONTA_ALTERADA_ENTRETANTO)
        except EmissaoEmCurso as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ConflitoDocumentoFiscal as e:
            raise HTTPException(status_code=500, detail=str(e))
        except (VerificacaoFiscalIncerta, DesfechoDaEmissaoIncerto) as e:
            # Não se sabe se o Vendus emitiu — ou porque o timeout foi
            # seguido de uma verificação que também falhou
            # (`VerificacaoFiscalIncerta`), ou porque a emissão rebentou de
            # uma forma que não prova nada, tipicamente DEPOIS de uma
            # resposta 2xx (`DesfechoDaEmissaoIncerto`). As duas são o mesmo
            # facto para quem está ao balcão, e por isso o mesmo 503: nunca
            # um "tente outra vez" genérico, que convidaria a operadora a
            # repetir às cegas, e MUITO menos um 500 — o ecrã lê um 500 com
            # a venda ainda `aberta` como "nada saiu, pode repetir", que é
            # exactamente a segunda Fatura Simplificada (ver a docstring de
            # `DesfechoDaEmissaoIncerto`).
            logger.error("[faturacao] finalizar sem desfecho conhecido: %s", e)
            raise HTTPException(status_code=503, detail=str(e))
        except VendusErro as e:
            raise HTTPException(status_code=502, detail="Vendus indisponível: %s" % e)

    venda_actualizada = await db[COLECOES["vendas"]].find_one({"id": venda_id})

    # **O PAPEL — depois de o documento fiscal existir, e nunca antes.**
    #
    # UM trabalho para a fila de impressão (`impressao.py`): o talão
    # certificado do cliente, na impressora do balcão. É o único ponto em que
    # esta rota toca no assunto, e é deliberadamente o último: o talão é
    # CONSEQUÊNCIA da fatura, nunca condição dela.
    #
    # **A ficha da cozinha não sai daqui**, e não é esquecimento: quem a manda
    # imprimir é o staff, pelo botão «Imprimir Pedido» do ecrã da venda
    # (`impressao.imprimir_pedido`), antes de haver fatura nenhuma. Enfileirá-la
    # aqui fazia uma conta dividida por três mandar três fichas do mesmo copo.
    #
    # Nada aqui pode falhar para fora — `impressao.enfileirar` engole tudo o
    # que lhe aconteça (ver a docstring de lá) e este `try` é a segunda rede,
    # para o caso de rebentar antes de lá chegar. Uma emissão bem sucedida,
    # com uma Fatura Simplificada REAL já entregue à Autoridade Tributária, a
    # devolver 500 por causa do papel era o pior desfecho possível: o ecrã lê
    # um 500 como "não saiu nada" e convida a operadora a emitir outra vez.
    #
    # O import é LOCAL pela mesma razão que os de `caixa.py` e do
    # `_verificar_vendas_dinheiro` aqui em cima: mantém o núcleo fiscal a não
    # depender, à importação, de um módulo cuja avaria não pode travar uma
    # venda.
    try:
        from .impressao import enfileirar_venda_emitida
        await enfileirar_venda_emitida(db, venda_actualizada or venda, documento)
    except Exception as e:  # noqa: BLE001 — perde-se o papel, nunca o registo
        logger.error(
            "[faturacao] a fatura %s saiu mas não foi possível pôr o papel na "
            "fila de impressão: %s. O documento fiscal está gravado e "
            "reimprime-se pelo separador Faturação.", venda_id, e,
        )

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
_MSG_LIBERTAR_RESERVA_SUBSTITUIDA = (
    "A reserva que esta página lhe mostrou já não existe: entretanto alguém "
    "voltou a carregar em FINALIZAR nesta conta e o que está lá agora é uma "
    "reserva NOVA, criada há %s. NÃO foi apagada nada — apagá-la era apagar "
    "a reserva de uma emissão que pode estar a falar com o Vendus neste "
    "instante, e sair uma SEGUNDA Fatura Simplificada da mesma venda. O que "
    "confirmou no Vendus era sobre a tentativa ANTERIOR: espere, volte a "
    "abrir a lista de reservas presas e, se esta conta ainda lá estiver, "
    "confirme outra vez antes de decidir."
)
_MSG_LIBERTAR_ULTRAPASSADA = (
    "A reserva desta venda (%s) MUDOU entre o momento em que esta página a "
    "leu e o momento de a apagar — NÃO foi apagada, e nada mudou no sistema. "
    "Foi de propósito: apagá-la sem confirmar que continuava igual era o que "
    "deixava a reserva de uma emissão em voo desaparecer por baixo dela, e "
    "sair uma SEGUNDA Fatura Simplificada da mesma venda. Volte a abrir a "
    "lista de reservas presas e veja como esta conta está agora."
)
_MSG_LIBERTAR_O_QUE_CONFIRMOU = (
    "Ao libertar esta reserva declarou ter aberto o Vendus, procurado a "
    "referência externa %s e visto que NÃO existe lá nenhum documento desta "
    "venda. Se existir, a próxima emissão desta conta cria uma SEGUNDA "
    "Fatura Simplificada da mesma venda, que só se corrige com uma nota de "
    "crédito."
)
# A conta que a operadora ENTREGOU ao gestor: nenhuma das duas frases abaixo
# lhe serve. Ela não "volta ao POS" (a marca `entregue_ao_gestor_em` tira-a do
# balcão e libertar a reserva não a devolve — era exactamente essa devolução
# silenciosa que punha a conta do cliente anterior dentro da fatura do
# seguinte), e também não é uma conta de um turno fechado: o turno dela pode
# estar a decorrer neste instante.
_MSG_LIBERTAR_A_SEGUIR_ENTREGUE = (
    "Esta conta foi ENTREGUE ao gestor no POS e continua a ser dele: libertar "
    "a reserva não a devolve ao balcão. Resolva-a aqui, em Contas por "
    "Resolver — dê-a por perdida se ninguém a pagou, ou use a reconciliação "
    "(Reconciliar) se afinal aparecer um documento no Vendus para esta venda."
)
_MSG_LIBERTAR_A_SEGUIR = (
    "A conta voltou a poder ser alterada, cancelada ou finalizada no POS. Se "
    "afinal aparecer um documento no Vendus para esta venda, NÃO a finalize: "
    "use a reconciliação (Reconciliar), que grava o documento que já existe "
    "e põe a venda como emitida."
)
# A conta REPARTIDA (a mãe `separada`): nenhuma das frases acima lhe serve, e
# esta é a que faltava. Exercitadas as três saídas que a frase de cima promete,
# sobre uma mãe `separada` de 11,64 €: alterar -> 409 «Esta conta foi
# dividida…», cancelar -> 409 com a mesma frase, e `GET /pos/venda/aberta` ->
# `null` (nem chega ao ecrã). Três saídas nomeadas, zero executáveis — e o
# gestor carregava em LIBERTAR precisamente porque a mensagem do fecho o
# mandava aqui.
#
# Uma mãe com partes resolve-se NAS PARTES; uma mãe SEM partes é uma divisão
# que morreu a meio e não há como a desfazer no POS. Nos dois casos a conta
# fica onde o dinheiro dela é contado — no Z do turno e na lista do gestor —, e
# é lá que ela se arruma.
_MSG_LIBERTAR_A_SEGUIR_REPARTIDA = (
    "Esta conta foi REPARTIDA e não volta ao balcão: o POS recusa alterá-la, "
    "cancelá-la e finalizá-la, e ela nem aparece no ecrã da operadora. Se a "
    "divisão tiver partes, é em cada PARTE que se cobra; se não tiver "
    "nenhuma (a divisão morreu a meio), resolva-a aqui, em Contas por "
    "Resolver — dê-a por perdida se ninguém a pagou. Ela continua a contar "
    "como dinheiro por receber no Z deste turno. Se afinal aparecer um "
    "documento no Vendus para esta venda, use a reconciliação (Reconciliar)."
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
# A caixa está a MEIO de um fecho (`caixa.py`: o estado `a_fechar`, posto
# ANTES de o fecho ler as vendas). Recusa-se e manda-se esperar, e a escolha
# é deliberada:
#
# - o que o `reconciliar` faz é passar a venda a `emitida` — e é EXACTAMENTE
#   isso que o fecho vai ler a seguir para calcular o Z. Feito dentro da
#   marca, os mesmos euros entram no Z E na lista do que falta acertar à mão.
#   Reproduzido: «RECONCILIAR → z_por_acertar=True, dinheiro_por_acertar=8.99»
#   e a seguir «Z escrito → vendas_dinheiro=8.99» — quem seguisse o aviso
#   fabricava uma diferença de +8,99 € num turno que estava certo, e ficava
#   registado na sessão a dizer o mesmo para quem lá fosse ver daí a um mês.
# - esperar não custa nada e resolve tudo: um fecho dura o que duram três
#   escritas locais. Do outro lado da marca a resposta é sempre exacta — com
#   o Z já escrito, sabe-se que ele não conta esta venda e o aviso diz
#   quanto falta na gaveta; se o fecho for recusado e desfeito, a caixa volta
#   a `aberta` e a venda entra no Z normalmente, sem aviso nenhum.
# - as alternativas eram piores: recalcular um Z que está a ser calculado, ou
#   adivinhar de que lado a venda vai cair — e este módulo não adivinha
#   números que alguém vai usar para mexer numa gaveta.
_MSG_RECONCILIAR_FECHO_A_DECORRER = (
    "A caixa desta venda (sessão %s) está a FECHAR o turno neste momento — o "
    "Z está a ser calculado. Reconciliar agora era arriscar contar os mesmos "
    "euros duas vezes: esta venda entrava no Z que está a sair E levava o "
    "aviso de que tinha ficado de fora dele, e quem seguisse o aviso criava "
    "uma diferença numa gaveta que estava certa. NÃO se gravou nada — o "
    "documento continua no Vendus, onde estava. Espere alguns segundos (um "
    "fecho demora um instante) e carregue outra vez em Reconciliar: aí a "
    "resposta já lhe diz com exactidão o que falta acertar, ou que não falta "
    "nada."
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
# O aviso do Z, com a repartição REAL do pagamento — nunca o total bruto do
# documento.
#
# A versão anterior mandava acertar a gaveta pelo total da fatura ("se foram
# recebidos em dinheiro, é esse o valor que estava a mais"). Num pagamento
# MISTO isso é falso e cria a diferença ao contrário: 8,99 € de fatura com
# 4,50 € em dinheiro e 4,49 € em multibanco mandava acertar 8,99 € e ficava
# uma diferença de 4,49 € do outro lado — numa gaveta que já tinha sido
# contada e assinada. A repartição está gravada na PRÓPRIA venda
# (`pagamentos`, com o `tipo_fiscal` em retrato) e é exactamente a mesma que
# o Z usa (`caixa_math.soma_vendas_dinheiro`): usa-se essa.
_MSG_RECONCILIAR_Z_POR_ACERTAR = (
    "ATENÇÃO ÀS CONTAS DO TURNO: esta venda pertence à sessão de caixa %s, "
    "que já está fechada — o relatório Z desse turno foi calculado e "
    "assinado SEM ela, e esta operação não o recalcula (um Z fechado não se "
    "reescreve por trás de quem o assinou). A fatura é de %s, dos quais %s "
    "em DINHEIRO e %s por outros meios (multibanco, etc.). Na GAVETA desse "
    "fecho só faltam contar os %s em dinheiro — o resto nunca lá passou. "
    "Fica registado na própria sessão de caixa, para se poder encontrar "
    "depois."
)
# A MESMA situação quando a venda não tem a repartição gravada: a reserva
# ficou presa ANTES de a emissão chegar a registar os pagamentos escolhidos
# (`fiscal._emitir_e_gravar` só os grava depois de ganhar a reserva). Aqui
# não se sabe quanto foi em dinheiro — e não se inventa um número que o
# gestor vá usar para mexer numa gaveta já contada.
_MSG_RECONCILIAR_Z_POR_ACERTAR_SEM_REPARTICAO = (
    "ATENÇÃO ÀS CONTAS DO TURNO: esta venda pertence à sessão de caixa %s, "
    "que já está fechada — o relatório Z desse turno foi calculado e "
    "assinado SEM ela, e esta operação não o recalcula (um Z fechado não se "
    "reescreve por trás de quem o assinou). A fatura é de %s, mas esta venda "
    "NÃO tem gravado como foi paga (a emissão ficou-se antes disso), por "
    "isso não é possível dizer quanto entrou na gaveta e quanto foi por "
    "outros meios: veja o talão ou o documento no Vendus antes de acertar "
    "seja o que for. Fica registado na própria sessão de caixa, para se "
    "poder encontrar depois."
)
# O caso em que o fecho ATRAVESSOU esta operação: a caixa não estava a fechar
# quando se escreveu (senão a rota tinha recusado, ver
# `_MSG_RECONCILIAR_FECHO_A_DECORRER`) e estava noutro estado logo a seguir.
# O fecho lê as vendas `emitida` entre a marca e o Z, por isso esta venda tanto
# pode ter entrado no Z como não — e isso NÃO se adivinha a partir daqui.
# Dizer "o Z foi assinado sem ela" seria afirmar uma coisa que não sabemos,
# exactamente o defeito que este aviso passou a ronda toda a fechar; dizer
# "está tudo bem" seria a mesma aposta ao contrário, e essa perde dinheiro em
# silêncio. Diz-se o que se sabe e manda-se confirmar no próprio Z, que é o
# único sítio onde a resposta existe.
_MSG_RECONCILIAR_Z_AO_MESMO_TEMPO = (
    "ATENÇÃO ÀS CONTAS DO TURNO: o fecho da sessão de caixa %s correu ao "
    "MESMO TEMPO que esta operação — a caixa estava '%s' quando esta venda "
    "foi ligada ao documento fiscal e estava '%s' logo a seguir. Por isso "
    "não é possível dizer daqui se o relatório Z desse turno já conta esta "
    "venda: ou conta (e não há nada a acertar), ou foi calculado sem ela (e "
    "então faltam %s na gaveta desse fecho). A fatura é de %s. ABRA O Z desse "
    "turno e compare as vendas em dinheiro ANTES de mexer seja no que for — "
    "esta é a única situação em que este aviso não consegue responder "
    "sozinho. Fica registado na própria sessão de caixa, para se poder "
    "encontrar depois."
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
    # **Primeiro de todos: a reserva ESTRAGADA.** Sem `ext_ref` nenhuma das
    # duas saídas desta lista lhe serve — LIBERTAR recusa-a
    # (`_MSG_LIBERTAR_SEM_EXT_REF`) e é a referência que se procuraria no
    # Vendus —, e por isso ela não pode aparecer como «órfã», que é a família
    # ao lado e essa liberta-se. Ver `caixa._MSG_CONTA_ESQUECIDA_RESERVA_-
    # ESTRAGADA`: é a mesma verdade, do lado de lá.
    if not reserva.get("ext_ref"):
        return {
            "motivo": "sem_ext_ref",
            "descricao": (
                "Reserva ESTRAGADA: ficou sem referência externa (`ext_ref`), "
                "que é o campo por onde se procura no Vendus. Libertar não "
                "serve — libertar exige confirmar no Vendus que não saiu "
                "documento para a referência, e sem referência não há o que "
                "procurar. Reconciliar ainda a pode salvar (procura o "
                "documento pela referência que a emissão teria usado); se o "
                "Vendus não tiver nada, esta reserva não se resolve em ecrã "
                "nenhum: leve-a a quem mantém o sistema."
            ),
        }
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


async def _recusa_de_libertacao_ultrapassada(
    db, ext_ref: str, venda_id: str, lida: Dict
) -> HTTPException:
    """A recusa a devolver quando o `delete_one` condicional NÃO apagou nada
    (ver `_libertar_reserva_se_intacta`): alguém mexeu na reserva entre a
    leitura da rota e a escrita.

    **A decisão já está tomada** — foi o `deleted_count` que a tomou, e nada
    foi apagado. Esta releitura serve só para escolher as PALAVRAS a mostrar
    ao gestor, e por isso pode ser feita sobre uma fotografia sem risco
    nenhum: no pior caso diz-lhe a razão errada de uma recusa certa.

    As razões possíveis são as de sempre, e por isso o texto é o mesmo: uma
    retoma em voo, um documento fiscal que apareceu entretanto, ou — se nem
    uma nem outro — a reserva mudou de forma que já não é a que ele viu.

    A ESSA lista juntou-se uma quarta nesta ronda, e é a mais importante das
    quatro: a reserva que ele viu foi libertada e SUBSTITUÍDA por outra
    (`lida["id"]` != o id de agora). Para o sistema é "a reserva mudou", mas
    para quem está a decidir é outra coisa completamente — houve uma TENTATIVA
    NOVA de emitir esta conta, que pode estar a falar com o Vendus neste
    instante, e a confirmação que ele foi fazer ao Vendus era sobre a
    tentativa anterior. Dizer-lhe só "mudou" convidava-o a repetir o gesto
    com a mesma confiança de há um minuto."""
    agora = datetime.now(timezone.utc)
    reserva = await db[COLECOES["refs_fiscais"]].find_one({"ext_ref": ext_ref})
    if reserva is not None and _retoma_em_curso(reserva, agora):
        return HTTPException(
            status_code=409,
            detail=_MSG_LIBERTAR_EM_RETOMA % (
                _retoma_reclamada_ha(reserva, agora),
                int(_SEGUNDOS_DE_RETOMA_NORMAL),
            ),
        )
    documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
    if documento is not None:
        return HTTPException(
            status_code=409,
            detail=_MSG_LIBERTAR_COM_DOCUMENTO % (
                documento.get("numero"), documento.get("atcud"),
            ),
        )
    if reserva is None:
        # Outro gestor (ou a própria emissão, ao abortar) libertou-a nesta
        # janela: o resultado é o que ele queria, mas quem o fez foi outro —
        # e a rota não pode responder "libertada por si" a quem não a apagou.
        logger.warning(
            "[faturacao] libertar %s (venda %s): a reserva desapareceu entre a "
            "leitura e a libertação — não foi esta chamada que a apagou.",
            ext_ref, venda_id,
        )
        return HTTPException(status_code=404, detail=_MSG_LIBERTAR_SEM_RESERVA)
    if reserva.get("id") != lida.get("id"):
        # A reserva foi libertada e outra nasceu no lugar dela (a `ext_ref` é
        # determinística, por isso repete-se). É o cenário que o `id` no
        # filtro do `delete_one` passou a apanhar — sem ele, era esta reserva
        # NOVA, com uma emissão real em voo, que ia abaixo.
        idade = _segundos_desde(reserva.get("criado_em"), agora)
        logger.warning(
            "[faturacao] libertar %s (venda %s): a reserva lida (%r) foi "
            "substituída por outra (%r, criada há %ss) — não se lhe tocou.",
            ext_ref, venda_id, lida.get("id"), reserva.get("id"), idade,
        )
        return HTTPException(
            status_code=409,
            detail=_MSG_LIBERTAR_RESERVA_SUBSTITUIDA % (
                "%.0f segundos" % idade if idade is not None else "instantes"
            ),
        )
    return HTTPException(status_code=409, detail=_MSG_LIBERTAR_ULTRAPASSADA % ext_ref)


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
    5. **A reserva mudou entre a leitura e o apagar** — as quatro guardas
       acima são respondidas sobre a reserva lida no primeiro passo, e a
       seguir a rota faz mais três `await`s (o documento, a venda, a
       sessão) antes de apagar. Uma retoma que reclame dentro dessa janela
       está a falar com o Vendus NESTE instante, e apagar-lhe a reserva por
       baixo é autorizar a segunda fatura — reproduzido, duas FS reais. Por
       isso o apagar é CONDICIONAL e é o `deleted_count` que decide (ver
       `_libertar_reserva_se_intacta`), do mesmo modo que é o
       `matched_count` que decide a corrida em `cancelar_venda` e em
       `_reclamar_retoma`.

    **A venda NÃO se toca: fica exactamente como estava.** O que se apaga é só
    a reserva.

    Esta frase dizia a seguir «que é precisamente o que devolve o balcão ao
    serviço», e era essa metade que estava errada — e cara. Enquanto a
    excepção da porta do POS fosse CALCULADA ("não conta a conta que tiver
    reserva viva"), apagar a reserva aqui destrancava, à distância e sem
    escrever nada na venda, uma conta que a operadora já tinha largado do
    ecrã: ela ressuscitava à frente do cliente SEGUINTE, sem marca nenhuma, e
    o primeiro produto dele aterrava na conta do anterior. Medido nas rotas
    reais: 8,99 € do cliente A + 2,00 € do cliente seguinte numa só conta de
    10,99 €, com a Fatura Simplificada a levar os dois artigos (ver a
    docstring de `venda.py::entregar_ao_gestor`).

    Deixou de ser possível porque a excepção passou a ser uma MARCA GRAVADA na
    venda (`entregue_ao_gestor_em`). Esta rota continua a não tocar na venda —
    e é por isso que a marca sobrevive: uma conta que a operadora entregou ao
    gestor continua do gestor depois de ele libertar a reserva, e resolve-se
    onde ela está, na lista dele (`GET /caixa/contas-esquecidas`, com o botão
    de a dar por perdida, e `reconciliar_reserva_presa` para o caso de a FS ter
    mesmo saído). O balcão não a recebe de volta.

    O que a resposta promete a seguir depende da CAIXA desta venda: com a
    sessão fechada, `finalizar` não é uma das saídas (ver
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
    # CONDICIONAL, e é o `deleted_count` que decide: todas as guardas acima
    # foram respondidas sobre a reserva lida no primeiro passo desta rota, e
    # entre essa leitura e esta linha correram três `await`s em que uma
    # retoma pode ter reclamado a emissão (ver
    # `_libertar_reserva_se_intacta`).
    if not await _libertar_reserva_se_intacta(db, ext_ref, reserva):
        raise await _recusa_de_libertacao_ultrapassada(db, ext_ref, venda_id, reserva)

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
        # **A frase tem de nomear só saídas que existam.** A marca da venda
        # manda sobre o estado da sessão (uma conta entregue não volta ao POS,
        # esteja o turno aberto ou fechado), e o ESTADO da venda manda sobre as
        # duas: uma conta repartida não se altera, não se cancela e não se
        # finaliza — medido, 409/409/`null` sobre a mãe `separada` de 11,64 €
        # que a mensagem do fecho mandava libertar.
        "a_seguir": (
            _MSG_LIBERTAR_A_SEGUIR_REPARTIDA
            if (venda or {}).get("estado") == "separada"
            else _MSG_LIBERTAR_A_SEGUIR_ENTREGUE
            if (venda or {}).get("entregue_ao_gestor_em")
            else (
                _MSG_LIBERTAR_A_SEGUIR if sessao_aberta
                else _MSG_LIBERTAR_A_SEGUIR_SESSAO_FECHADA
            )
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


def _reparticao_do_pagamento(venda: Dict) -> Optional[Dict]:
    """Como é que esta venda foi PAGA: quanto entrou na gaveta (dinheiro) e
    quanto veio por outros meios. `None` quando a venda não tem os
    `pagamentos` gravados — e aí não se inventa uma repartição.

    A parte em dinheiro calcula-se com `caixa_math.soma_vendas_dinheiro`, a
    MESMA função que o Z usa: se o aviso ao gestor usasse outra conta, era
    outra conta que ele ia acertar. Essa função só soma vendas `emitida` e,
    dentro delas, só os pagamentos com `tipo_fiscal == "NU"` (o retrato
    gravado no momento da emissão, nunca a configuração de hoje).

    O estado força-se a `emitida` de propósito: quando isto é chamado, a
    venda ACABOU de ser ligada ao documento fiscal — é isso que ela é. Sem o
    forçar, uma releitura que apanhasse o instante errado dava 0,00 € em
    dinheiro numa venda paga inteirinha em dinheiro, que é o número mais
    perigoso desta função."""
    pagamentos = venda.get("pagamentos") or []
    if not pagamentos:
        return None
    dinheiro = soma_vendas_dinheiro([dict(venda, estado="emitida")])
    total_pago = round(sum(float(p.get("valor") or 0) for p in pagamentos), 2)
    return {
        "dinheiro": dinheiro,
        "outros": round(total_pago - dinheiro, 2),
        "total_pago": total_pago,
    }


async def _marcar_venda_ligada_depois_do_fecho(
    db, sessao: Dict, venda_id: str, ext_ref: str, documento: Dict,
    reparticao: Optional[Dict], gestor: Dict,
    fecho_ao_mesmo_tempo: bool = False,
) -> Optional[Dict]:
    """Deixa na PRÓPRIA sessão de caixa o rasto de que esta venda lhe foi
    ligada DEPOIS do fecho — e devolve a marca escrita (ou `None` se não foi
    possível escrevê-la).

    **Não recalcula o Z, e não é para recalcular.** Aquele talão foi
    assinado por uma funcionária com a gaveta contada à frente dela;
    reescrevê-lo por trás era mentir sobre o que foi contado. O que fica é
    um registo à parte (`vendas_ligadas_depois_do_fecho`), com o valor, a
    parte em dinheiro, o documento e a data — a informação que o gestor
    precisa para acertar as contas desse turno à mão, e que até aqui só
    existia no corpo de UMA resposta HTTP e num `logger.warning`: passada
    uma semana não havia sítio nenhum onde se visse que aqueles euros
    existiram.

    `$push` e não um `$set` de uma lista relida: duas reconciliações da
    mesma sessão (duas contas presas da mesma noite, o caso normal quando um
    deploy apanha o serviço a meio) perdiam uma das marcas.

    Nunca rebenta a rota: a reconciliação em si JÁ correu bem — o documento
    fiscal está gravado e a venda está `emitida`. Falhar a marca é perder um
    registo de apoio, e transformar isso num 500 mandava o gestor repetir
    uma operação que já estava feita (mesmo raciocínio de
    `_ligar_venda_ao_documento`)."""
    marca = {
        "venda_id": venda_id,
        "ext_ref": ext_ref,
        "documento_id": documento.get("id"),
        "numero": documento.get("numero"),
        "atcud": documento.get("atcud"),
        "total": documento.get("total"),
        # `None` (e não 0,00 €) quando não se sabe como foi paga — ver
        # `_reparticao_do_pagamento`.
        "dinheiro": (reparticao or {}).get("dinheiro"),
        "outros_meios": (reparticao or {}).get("outros"),
        "ligada_em": _agora(),
        "por": gestor.get("email") or gestor.get("user_id"),
        # `True` quando o fecho desta sessão correu ao MESMO TEMPO que a
        # ligação e não se sabe de que lado do Z a venda caiu (ver
        # `_MSG_RECONCILIAR_Z_AO_MESMO_TEMPO`). Fica GRAVADO, e não só dito
        # na resposta: quem for ver esta marca daqui a um mês tem de poder
        # distinguir "faltam mesmo estes euros na gaveta" de "isto é para
        # confirmar no Z antes de mexer" — a diferença entre as duas é uma
        # diferença de caixa inventada.
        "fecho_ao_mesmo_tempo": fecho_ao_mesmo_tempo,
    }
    try:
        # O `$ne` sobre o `venda_id` das marcas já lá gravadas é o que torna
        # isto IDEMPOTENTE: reconciliar duas vezes a mesma conta (um duplo
        # clique, ou o gestor a repetir para ver a resposta) é um pedido que
        # esta rota promete responder na mesma sem escrever nada de novo —
        # duas marcas dos MESMOS 8,99 € convidavam a acertar a gaveta duas
        # vezes, que é o estrago que este registo existe para evitar.
        resultado = await db[COLECOES["sessoes_caixa"]].update_one(
            {
                "id": sessao.get("id"),
                "vendas_ligadas_depois_do_fecho.venda_id": {"$ne": venda_id},
            },
            {"$push": {"vendas_ligadas_depois_do_fecho": marca}},
        )
    except Exception as e:  # noqa: BLE001 — ver a docstring: registo de apoio
        logger.error(
            "[faturacao] não foi possível registar na sessão %r que a venda %s "
            "lhe foi ligada depois do fecho (%s) — o documento fiscal ficou "
            "gravado à mesma: %r", sessao.get("id"), venda_id, e, marca,
        )
        return None
    if resultado.matched_count == 1:
        return marca
    # Não escreveu: ou a marca desta venda já lá estava (pedido repetido), ou
    # a sessão desapareceu. Só a releitura distingue as duas — e a diferença
    # importa, porque a primeira é um sucesso e a segunda é uma falha.
    sessao_agora = await db[COLECOES["sessoes_caixa"]].find_one({"id": sessao.get("id")})
    ja_marcada = next(
        (m for m in ((sessao_agora or {}).get("vendas_ligadas_depois_do_fecho") or [])
         if m.get("venda_id") == venda_id),
        None,
    )
    if ja_marcada is not None:
        return ja_marcada
    logger.error(
        "[faturacao] a sessão %r não aceitou o registo da venda %s ligada "
        "depois do fecho — o documento fiscal ficou gravado à mesma: %r",
        sessao.get("id"), venda_id, marca,
    )
    return None


def _recusa_se_a_caixa_esta_a_fechar(sessao: Optional[Dict], venda_id: str) -> None:
    """Recusa a reconciliação enquanto a caixa desta venda estiver a MEIO de
    um fecho (`a_fechar`) — ver `_MSG_RECONCILIAR_FECHO_A_DECORRER`, onde
    está a escolha por extenso.

    Chamada DUAS vezes na rota, e as duas são precisas: à entrada (para não
    gastar uma ida ao Vendus numa operação que vai ser recusada) e outra vez
    imediatamente antes de escrever — porque entre as duas está uma chamada
    HTTP ao Vendus, que são SEGUNDOS, e um fecho inteiro cabe lá dentro à
    vontade. É a segunda que fecha a janela; a primeira é só cortesia. Mesma
    forma da lição desta ronda: quem decide sobre uma leitura antiga tem de
    voltar a perguntar imediatamente antes de escrever."""
    if sessao is not None and sessao.get("estado") == "a_fechar":
        logger.warning(
            "[faturacao] reconciliação da venda %s adiada: a sessão %r está a "
            "meio de um fecho — nada foi gravado.",
            venda_id, sessao.get("id"),
        )
        raise HTTPException(
            status_code=409,
            detail=_MSG_RECONCILIAR_FECHO_A_DECORRER % sessao.get("id"),
        )


def _dinheiro_por_acertar_em_texto(reparticao: Optional[Dict]) -> str:
    """A parte da frase que diz quanto falta na gaveta — ou que não se sabe.
    Sem a repartição gravada não se manda acertar pelo total do documento
    (ver `_MSG_RECONCILIAR_Z_POR_ACERTAR_SEM_REPARTICAO`): num pagamento
    misto isso cria a diferença ao contrário."""
    if reparticao is None:
        return (
            "o que desta fatura tiver entrado em dinheiro (esta venda não tem "
            "gravado como foi paga, por isso não é possível dizer quanto)"
        )
    return "%s em dinheiro" % _euros(reparticao["dinheiro"])


def _aviso_do_z(
    sessao_id,
    documento: Dict,
    reparticao: Optional[Dict],
    transicao: Optional[List[Optional[str]]] = None,
) -> str:
    """A frase que o gestor lê quando a sessão desta venda já está fechada.
    Com a repartição gravada, diz-lhe exactamente o que falta na GAVETA (só
    a parte em dinheiro); sem ela, diz que não sabe — nunca manda acertar
    pelo total (ver `_MSG_RECONCILIAR_Z_POR_ACERTAR`).

    `transicao` (o estado da caixa antes e depois da escrita) só vem
    preenchida quando o fecho ATRAVESSOU esta operação — e aí a frase é
    outra, porque o facto é outro: não se sabe de que lado do Z esta venda
    caiu, e diz-se isso (ver `_MSG_RECONCILIAR_Z_AO_MESMO_TEMPO`)."""
    if transicao is not None:
        return _MSG_RECONCILIAR_Z_AO_MESMO_TEMPO % (
            sessao_id,
            # A sessão pode ter DESAPARECIDO pelo meio (o caso extremo). Aí
            # o estado não é `None` na frase — é "sem sessão nenhuma", que é
            # o que o gestor tem de ir ver.
            transicao[0] or "sem sessão nenhuma",
            transicao[1] or "sem sessão nenhuma",
            _dinheiro_por_acertar_em_texto(reparticao),
            _euros(documento.get("total")),
        )
    if reparticao is None:
        return _MSG_RECONCILIAR_Z_POR_ACERTAR_SEM_REPARTICAO % (
            sessao_id, _euros(documento.get("total")),
        )
    return _MSG_RECONCILIAR_Z_POR_ACERTAR % (
        sessao_id,
        _euros(documento.get("total")),
        _euros(reparticao["dinheiro"]),
        _euros(reparticao["outros"]),
        _euros(reparticao["dinheiro"]),
    )


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

    # A caixa desta venda ANTES de qualquer escrita. Duas coisas de uma vez:
    # recusa se o fecho estiver a decorrer (ver
    # `_recusa_se_a_caixa_esta_a_fechar`) e fica a ser o estado contra o qual
    # se compara, no fim, o de depois da escrita — é a passagem da venda a
    # `emitida` que decide se ela entra ou não no Z, por isso é do estado da
    # caixa NESSE instante que o aviso depende.
    sessao_antes = await _sessao_da_venda(db, venda)
    _recusa_se_a_caixa_esta_a_fechar(sessao_antes, venda_id)

    documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
    if documento is not None:
        # O documento já cá estava. Duas hipóteses, e as duas acabam bem sem
        # incomodar o Vendus: ou a venda também já está `emitida` (isto é um
        # pedido repetido — responde-se o mesmo, sem escrever nada de novo),
        # ou o processo morreu entre as duas escritas de `_gravar_documento`
        # e a venda ficou para trás em `aberta` com uma FS real gravada — e
        # aí a religação é exactamente o que falta.
        if venda.get("estado") != "emitida" or venda.get("documento_id") != documento["id"]:
            # `reserva.id`: carimba-se a reserva que ESTA rota leu no
            # princípio, nunca "a que estiver na ext_ref". Sem isto, o `$set`
            # de `_ligar_venda_ao_documento` acertava numa reserva NOVA — a
            # operadora carregou outra vez em FINALIZAR entretanto, e a
            # `ext_ref` é determinística, logo repete-se — e escrevia-lhe um
            # `documento_id` que não saiu dela. O campo quer dizer "o
            # documento que saiu DESTA reserva", e passava a dizer uma
            # mentira sobre uma emissão que ainda está EM VOO: é por ele que
            # `listar_reservas_presas` faz a primeira triagem, e é ele que o
            # gestor lê quando vai perceber, semanas depois, que documento
            # saiu de que tentativa. Ver `_ligar_venda_ao_documento`.
            #
            # O que NÃO muda, medido nas duas variantes: a listagem de presas
            # responde o mesmo (vazia) e a conta fica igualmente trancada — a
            # MESMA escrita põe a venda `emitida`, e é o estado da venda que
            # a junção da listagem descarta e que as rotas de escrita
            # recusam. Este comentário chegou a prometer aqui "a conta ficava
            # trancada E invisível ao gestor", que é a descrição do OUTRO
            # sítio e é falsa neste: foi um comentário falso — o do
            # `_libertar_reserva` — que escondeu um bloqueador durante duas
            # rondas, e a lição é não repetir uma frase para outro sítio sem
            # a voltar a medir lá.
            await _ligar_venda_ao_documento(
                db, ext_ref, venda_id, documento,
                reserva_id=(reserva or {}).get("id"))
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

        # A caixa OUTRA VEZ, agora que a chamada ao Vendus (segundos de rede)
        # já passou: é esta releitura, imediatamente antes da escrita, que
        # fecha a janela — um fecho inteiro cabe dentro de uma chamada HTTP.
        sessao_antes = await _sessao_da_venda(db, venda)
        _recusa_se_a_caixa_esta_a_fechar(sessao_antes, venda_id)

        try:
            documento = await _gravar_documento(
                db, ext_ref, venda, encontrado,
                reserva_id=(reserva or {}).get("id"))
        except ConflitoDocumentoFiscal as e:
            raise HTTPException(status_code=500, detail=str(e))
        veio_do_vendus_agora = True

    # A reserva (se existir) deixa de estar `incerta`: já se sabe o que
    # aconteceu — saiu mesmo, e o documento está gravado. `_gravar_documento`
    # já lhe pôs o `documento_id`, que é o que a tira da listagem de presas.
    # CONDICIONAL: a decisão de lhe mexer foi tomada lá em cima, antes da
    # chamada ao Vendus (ver `_limpar_incerta_se_intacta`).
    if reserva is not None:
        await _limpar_incerta_se_intacta(db, ext_ref, reserva)

    sessao = await _sessao_da_venda(db, venda)
    sessao_estado = sessao.get("estado") if sessao else None
    estado_antes = sessao_antes.get("estado") if sessao_antes else None
    # O fecho ATRAVESSOU esta operação? A caixa não estava a fechar antes da
    # escrita (a rota tinha recusado) e mudou de estado durante ela: entre a
    # marca `a_fechar` e o Z, o fecho lê as vendas `emitida`, e esta venda
    # tanto pode ter chegado a tempo dessa leitura como não. É a única
    # situação em que este aviso não sabe responder, e é por isso que o diz
    # com todas as letras em vez de escolher a resposta mais provável — as
    # duas escolhas erradas custam dinheiro, uma em cada sentido.
    fecho_ao_mesmo_tempo = estado_antes != sessao_estado
    # O Z de uma sessão já fechada NÃO se recalcula aqui — e não se finge que
    # ficou tudo bem: diz-se ao gestor o que tem de acertar à mão nesse turno.
    z_por_acertar = sessao_estado != "aberta" or fecho_ao_mesmo_tempo

    # A repartição lê-se da venda COMO ELA ESTÁ AGORA (já `emitida`, já com
    # os pagamentos gravados por quem tentou emitir), nunca do retrato lido à
    # entrada desta rota.
    actual = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    reparticao = _reparticao_do_pagamento(actual or venda)

    marca = None
    if z_por_acertar and sessao is not None:
        marca = await _marcar_venda_ligada_depois_do_fecho(
            db, sessao, venda_id, ext_ref, documento, reparticao, gestor,
            fecho_ao_mesmo_tempo,
        )

    logger.warning(
        "[faturacao] venda reconciliada com o documento do Vendus: ext_ref=%s "
        "venda=%s documento=%s numero=%r atcud=%r do_vendus_agora=%s "
        "sessao=%r sessao_estado=%r (antes da escrita: %r) dinheiro=%r "
        "outros=%r por=%s nota=%r",
        ext_ref, venda_id, documento.get("id"), documento.get("numero"),
        documento.get("atcud"), veio_do_vendus_agora, venda.get("sessao_id"),
        sessao_estado, estado_antes, (reparticao or {}).get("dinheiro"),
        (reparticao or {}).get("outros"),
        gestor.get("email") or gestor.get("user_id"),
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
        # Os números da repartição, à parte da frase: quem mostra isto no
        # ecrã não tem de os voltar a extrair do texto. `None` quando a venda
        # não tem os pagamentos gravados — nunca um zero, que se leria como
        # "não entrou dinheiro nenhum" (ver `_reparticao_do_pagamento`).
        "dinheiro_por_acertar": (reparticao or {}).get("dinheiro"),
        "outros_meios": (reparticao or {}).get("outros"),
        "aviso_do_z": _aviso_do_z(
            venda.get("sessao_id"), documento, reparticao,
            [estado_antes, sessao_estado] if fecho_ao_mesmo_tempo else None,
        ) if z_por_acertar else None,
        # Se a marca ficou mesmo escrita na sessão de caixa. Enquanto era só
        # o corpo desta resposta e um `logger.warning`, passada uma semana
        # não havia UM ÚNICO sítio onde se visse que aqueles euros existiram.
        "registada_na_sessao": marca is not None,
        "o_que_aconteceu": _MSG_RECONCILIAR_O_QUE_ACONTECEU % ext_ref,
    }
