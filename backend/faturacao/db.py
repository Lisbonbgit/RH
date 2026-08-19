"""Acesso à base de dados do módulo Faturação.

O cliente é criado à PRIMEIRA UTILIZAÇÃO (e não ao importar o módulo) para que o
pacote possa ser importado em testes sem MONGO_URL/DB_NAME definidos.
"""
import logging
import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

# Nomes das colecções, todos com prefixo fat_ (convenção do repositório: fin_, mkt_).
COLECOES = {
    "lojas": "fat_lojas",
    "caixas": "fat_caixas",
    "utilizadores": "fat_utilizadores",
    "tipos_pagamento": "fat_tipos_pagamento",
    "motivos_nc": "fat_motivos_nc",
    "categorias": "fat_categorias",
    "grupos_personalizacao": "fat_grupos_personalizacao",
    "produtos": "fat_produtos",
    # Documentos fiscais emitidos pelo POS próprio (Plano 2 enche esta colecção;
    # até lá está vazia, e uma procura numa colecção vazia devolve vazio — não
    # dá erro). É esta colecção, não o Vendus, que o Dashboard (Plano 3) lê.
    "documentos": "fat_documentos",
    # Dispositivos do POS: um código de emparelhamento de uso único (gerado
    # pelo gestor) que se troca por um token de dispositivo persistente (ver
    # faturacao/pos_auth.py). O PC da loja guarda o token no localStorage.
    "dispositivos": "fat_dispositivos",
    # Sessão de caixa (Task 3 do Plano 2A, spec §7.2): abre com o fundo de
    # maneio, acumula movimentos, fecha com a contagem e o Z (faturacao/caixa.py).
    "sessoes_caixa": "fat_sessoes_caixa",
    # Entradas e saídas de dinheiro ao longo da sessão (faturacao/caixa.py).
    #
    # ATENÇÃO a quem vier somar isto: a linha existir NÃO quer dizer que o
    # dinheiro saiu da gaveta. Ela é inserida ANTES da escrita que a confirma
    # (é essa ordem que impede um movimento de aparecer depois de um Z já
    # assinado, ver `caixa.py::registar_movimento`), e quem manda é a lista
    # `movimentos_confirmados` da SESSÃO — lá entra o `id` na mesma escrita
    # que verifica que a sessão ainda está aberta. Uma linha marcada
    # `por_confirmar: True` e fora dessa lista é uma tentativa que ficou a
    # meio: não entra em Z nenhum, e não se soma em lado nenhum.
    "movimentos_caixa": "fat_movimentos_caixa",
    # A conta do balcão (Plano 2B, Task 2, faturacao/venda.py): nasce
    # 'aberta', acumula linhas, e só a Task 3 (emissão) a passa a 'emitida'.
    "vendas": "fat_vendas",
    # A RESERVA atómica da Task 3 (faturacao/fiscal.py, spec §6.1 passo 2):
    # um documento por `ext_ref`, inserido ANTES de qualquer pedido ao
    # Vendus. O índice único em `ext_ref` (ver INDICES abaixo) É a garantia
    # — quem perde a corrida (dois toques na mesma venda, ou um retry a
    # cruzar-se com o pedido original) apanha DuplicateKeyError e nunca
    # chega a emitir. Coleção pequena e efémera por natureza: cada linha
    # representa UMA tentativa de emissão, não um documento fiscal em si
    # (isso é fat_documentos).
    "refs_fiscais": "fat_refs_fiscais",
}

_cliente = None  # type: Optional[AsyncIOMotorClient]


def obter_db():
    """Devolve a base de dados, criando o cliente na primeira chamada."""
    global _cliente
    if _cliente is None:
        _cliente = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return _cliente[os.environ["DB_NAME"]]


# (coleccao, chaves, opcoes). Declarados como dados para serem testáveis sem Mongo.
#
# NOTA: propositadamente NÃO há índice único sobre pin_hash. O bcrypt usa sal
# aleatório, por isso o mesmo PIN gera um pin_hash diferente de cada vez — um
# índice único sobre esse campo nunca detectaria PINs repetidos. Ver
# test_nao_existe_indice_unico_sobre_pin_hash e o comentário em
# faturacao/pins.py sobre como a unicidade do PIN é garantida.
INDICES = [
    ("fat_lojas", [("empresa_id", 1)], {}),
    ("fat_caixas", [("loja_id", 1)], {}),
    ("fat_utilizadores", [("ativo", 1)], {}),
    ("fat_tipos_pagamento", [("ordem", 1)], {}),
    ("fat_categorias", [("ordem", 1)], {}),
    ("fat_produtos", [("categoria_id", 1)], {}),
    ("fat_produtos", [("ativo", 1)], {}),
    ("fat_produtos", [("vendus_ref", 1)], {"sparse": True}),
    ("fat_grupos_personalizacao", [("nome", 1)], {}),
    # Dashboard: a série diária/mensal lê por data (todas as lojas) e por loja+data.
    ("fat_documentos", [("emitido_em", 1)], {}),
    ("fat_documentos", [("loja_id", 1), ("emitido_em", 1)], {}),
    # A Task 3 (spec §4.3): terceira e quarta defesa contra a fatura a dobrar
    # — únicos em `vendus_document_id` E em `atcud`. Mesmo que a reserva em
    # fat_refs_fiscais falhasse por alguma razão, um documento com o mesmo id
    # (ou ATCUD, que a AT nunca repete) do Vendus não consegue ser gravado
    # duas vezes aqui.
    ("fat_documentos", [("vendus_document_id", 1)], {"unique": True}),
    ("fat_documentos", [("atcud", 1)], {"unique": True}),
    # A verificação por timeout (Task 3, passo 4) e a reconciliação do fecho
    # (Task 4) procuram por `ext_ref` — e é ÚNICO.
    #
    # Era um índice de leitura simples, com o argumento de que "o único de
    # verdade é o de fat_refs_fiscais". Só que a reserva garante uma
    # tentativa de EMISSÃO por venda, e isto garante outra coisa: um
    # DOCUMENTO por venda. Sem ele, quando alguma coisa duplicasse a fatura
    # ficavam duas linhas com a mesma `ext_ref` e ATCUDs diferentes e nada o
    # assinalava — a venda apontava para uma, o ecrã mostrava a que o Mongo
    # calhasse, e a listagem de reservas presas deixava de a mostrar. Com o
    # único, a segunda gravação rebenta no instante em que acontece e
    # `fiscal._gravar_documento` transforma-a num
    # `ConflitoDocumentoFiscal` alto (a reserva NÃO se liberta) em vez de
    # uma duplicação silenciosa.
    #
    # PARCIAL (só onde `ext_ref` é mesmo uma string): dois documentos sem
    # `ext_ref` — dados estragados ou de uma migração — colidiriam entre si
    # num único simples, e recusar a gravação de um documento fiscal REAL
    # por causa disso era o estrago ao contrário.
    (
        "fat_documentos",
        [("ext_ref", 1)],
        {"unique": True, "partialFilterExpression": {"ext_ref": {"$type": "string"}}},
    ),
    # Entrada no POS: busca o dispositivo pelo hash do código (emparelhar) ou
    # do token (dispositivo_atual, em cada pedido).
    ("fat_dispositivos", [("codigo_hash", 1)], {"sparse": True}),
    ("fat_dispositivos", [("token_hash", 1)], {"sparse": True}),
    # A GARANTIA da Task 3 (spec §7.2): único PARCIAL em {caixa_id,
    # estado:'aberta'} — impossível haver duas sessões abertas na mesma
    # caixa, mesmo com dois PCs a tentar ao mesmo tempo. Sem isto, o fecho e
    # o Z (Task 4) partiam-se com uma corrida entre duas sessões paralelas.
    # PARCIAL, não simples: só se aplica aos documentos com estado='aberta',
    # senão a segunda sessão FECHADA da mesma caixa (perfeitamente normal, é
    # o histórico do dia seguinte) colidiria com a primeira.
    (
        "fat_sessoes_caixa",
        [("caixa_id", 1)],
        {"unique": True, "partialFilterExpression": {"estado": "aberta"}},
    ),
    ("fat_sessoes_caixa", [("loja_id", 1)], {}),
    # O fecho (Task 4) lê todos os movimentos de uma sessão de uma vez.
    ("fat_movimentos_caixa", [("sessao_id", 1)], {}),
    # A venda do balcão (Plano 2B, Task 2): o fecho de caixa (Task 4) vai
    # somar as vendas em dinheiro de uma sessão; o backoffice lista por
    # loja+data (spec §4.3).
    ("fat_vendas", [("sessao_id", 1)], {}),
    ("fat_vendas", [("loja_id", 1), ("criada_em", 1)], {}),
    # A GARANTIA central da Task 3 (spec §6.1 passo 2): impossível duas
    # tentativas de emissão da MESMA venda reservarem com sucesso ao mesmo
    # tempo — quem perde a corrida apanha DuplicateKeyError e nunca chega a
    # falar com o Vendus. É este índice, não uma leitura antes de inserir,
    # que decide a corrida real (mesmo raciocínio do índice de sessão aberta
    # acima).
    ("fat_refs_fiscais", [("ext_ref", 1)], {"unique": True}),
    # A pergunta "esta venda tem uma reserva de emissão?" — feita por TODAS as
    # rotas de escrita da conta do balcão (venda.py: juntar/editar/remover
    # linha, desconto global, cancelar — e o cancelar pergunta DUAS vezes,
    # antes e depois de escrever) e ainda pelo `emissao_por_confirmar` de
    # `GET /pos/venda/aberta`. Sem este índice era um VARRIMENTO COMPLETO da
    # colecção por cada uma dessas perguntas, e esta colecção nunca encolhe:
    # a reserva de uma venda já emitida fica lá para sempre, porque é ela que
    # sustenta a idempotência (ver a docstring de `refs_fiscais` acima). A
    # 5 lojas × ~200 vendas/dia são ~365 mil documentos ao fim de um ano —
    # cada toque num produto no ecrã pagava o varrimento inteiro.
    ("fat_refs_fiscais", [("venda_id", 1)], {}),
    # A listagem de gestão das reservas PRESAS (`fiscal.py::
    # listar_reservas_presas`) pergunta pelas que ainda não têm documento
    # gravado — `{"documento_id": None}`, que no Mongo casa com o campo
    # AUSENTE e com o campo a `null`. Índice NORMAL (não esparso) de
    # propósito: é precisamente a parte `null` da chave que interessa
    # percorrer, e é ela que fica minúscula (as presas são um punhado), ao
    # passo que um índice esparso indexava só as resolvidas — as 365 mil que
    # a listagem NÃO quer ver.
    ("fat_refs_fiscais", [("documento_id", 1)], {}),
]


async def criar_indices(db):
    """Aplica os índices. Uma falha é registada mas NÃO impede o arranque —
    o módulo tem de subir mesmo que um índice não possa ser criado."""
    for coleccao, chaves, opcoes in INDICES:
        try:
            await db[coleccao].create_index(chaves, **opcoes)
        except Exception as e:  # noqa: BLE001 — arrancar é mais importante
            logger.error("[faturacao] índice %s %s falhou: %s", coleccao, chaves, e)


# --- I3: o índice de idempotência é VERIFICADO, nunca assumido -----------------
#
# `criar_indices` engole a falha de CADA índice individualmente, e o arranque
# (`faturacao/__init__.py::arrancar`) corta a espera total aos
# LIMITE_INDICES_SEGUNDOS — com um Atlas lento, o índice único de
# `fat_refs_fiscais.ext_ref` (o ÚLTIMO dos 22 declarados acima, por isso o
# PRIMEIRO a ficar por criar quando o tempo esgota) podia nunca chegar a
# existir, em silêncio, e o POS continuava a servir vendas sem defesa nenhuma
# contra o duplo-toque. Isto verifica esse índice concreto a sério — nunca
# "criar_indices não rebentou, logo deve estar lá" — e `arrancar()` usa o
# resultado para decidir se o POS pode servir `/pos/venda/{id}/finalizar`.

_indice_idempotencia_ok = None  # type: Optional[bool]  # None = ainda não confirmado


async def indice_idempotencia_presente(db) -> bool:
    """Lê os índices REAIS de `fat_refs_fiscais` e confirma que existe um
    único sobre `ext_ref` — não assume nada a partir de `criar_indices` ter
    corrido sem excepção. Qualquer falha a ler os índices (Atlas em baixo,
    por exemplo) conta como AUSENTE, nunca como "não consegui verificar,
    assumo que está lá"."""
    try:
        indices = await db[COLECOES["refs_fiscais"]].index_information()
    except Exception as e:  # noqa: BLE001 — falha na verificação = ausente
        logger.error("[faturacao] não foi possível confirmar o índice de idempotência: %s", e)
        return False
    for detalhes in indices.values():
        chave = list(detalhes.get("key") or [])
        if chave == [("ext_ref", 1)] and detalhes.get("unique"):
            return True
    return False


def marcar_indice_idempotencia(ok: Optional[bool]) -> None:
    """Chamado por `arrancar()` depois de `indice_idempotencia_presente` —
    guarda o resultado para as rotas do POS consultarem sem repetir a
    leitura a cada pedido."""
    global _indice_idempotencia_ok
    _indice_idempotencia_ok = ok


def indice_idempotencia_confirmado() -> bool:
    """`True` só depois de `arrancar()` confirmar mesmo que o índice único
    de `ext_ref` existe — NUNCA por omissão (`None`, o valor antes de
    `arrancar()` correr, conta como "não confirmado", não como "assumido
    OK"). É esta função que `fiscal.finalizar` consulta antes de tocar na
    reserva atómica."""
    return _indice_idempotencia_ok is True
