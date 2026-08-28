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
    # Definições do backoffice, um documento por chave. Genérica de
    # propósito: a próxima definição não precisa de colecção nova.
    "definicoes": "fat_definicoes",
    "lojas": "fat_lojas",
    "caixas": "fat_caixas",
    "utilizadores": "fat_utilizadores",
    "tipos_pagamento": "fat_tipos_pagamento",
    "motivos_nc": "fat_motivos_nc",
    "categorias": "fat_categorias",
    # As subcategorias vivem DENTRO de uma categoria (Venda ao Público →
    # Açaís, Salgados…) e são só nossas: o Vendus não as tem, e a
    # importação nunca lhes toca. Servem para arrumar a grelha do POS.
    "subcategorias": "fat_subcategorias",
    # A ficha do cliente — só o que os documentos não sabem (nome, contacto).
    # Quem é cliente decide-se pelas COMPRAS, não por esta colecção.
    "clientes": "fat_clientes",
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
    # A INTENÇÃO de uma nota de crédito (faturacao/nota_credito.py), gravada
    # ANTES de qualquer pedido ao Vendus e com identidade PRÓPRIA — é ela, e
    # não a fatura de origem, que serve de reserva atómica: contra a mesma
    # fatura pode haver várias notas de crédito parciais, e uma reserva por
    # documento de origem tornava a segunda impossível de emitir. O `id` é o
    # da intenção (índice único abaixo) e a referência externa deriva dele.
    "notas_credito": "fat_notas_credito",
    # A FILA DE IMPRESSÃO (`faturacao/impressao.py`): o que tem de sair em
    # papel na loja e ainda não saiu. Um documento por PAPEL — o talão do
    # cliente, o pedido da cozinha, o Z, a segunda via — mais o impulso que
    # abre a gaveta, que não é papel nenhum mas sai pelo mesmo caminho.
    #
    # **Não é um registo fiscal e não substitui nenhum.** O documento fiscal
    # vive em `fat_documentos` para sempre; isto é o papel, e o papel
    # reimprime-se. É por isso que esta colecção tem um índice TTL (abaixo) e
    # nenhuma outra do módulo tem: ao fim de uma semana, um trabalho já
    # impresso não responde a pergunta nenhuma que `fat_documentos` não
    # responda melhor, e sem o TTL a colecção guardava os BYTES de cada talão
    # de cinco lojas para sempre.
    "trabalhos_impressao": "fat_trabalhos_impressao",
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
    ("fat_subcategorias", [("categoria_id", 1), ("ordem", 1)], {}),
    ("fat_produtos", [("categoria_id", 1)], {}),
    ("fat_produtos", [("subcategoria_id", 1)], {"sparse": True}),
    ("fat_produtos", [("ativo", 1)], {}),
    ("fat_produtos", [("vendus_ref", 1)], {"sparse": True}),
    ("fat_grupos_personalizacao", [("nome", 1)], {}),
    # Dashboard: a série diária/mensal lê por data (todas as lojas) e por loja+data.
    ("fat_documentos", [("emitido_em", 1)], {}),
    ("fat_documentos", [("loja_id", 1), ("emitido_em", 1)], {}),
    # O ecrã de Clientes e o relatório por cliente perguntam "quais os
    # documentos deste NIF?" — sem índice era um varrimento da colecção toda.
    ("fat_documentos", [("cliente_nif", 1)], {"sparse": True}),
    ("fat_clientes", [("nif", 1)], {"unique": True}),
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
    # **`id` procurado por `$in`** — «dá-me as vendas destes documentos».
    #
    # `relatorios.eventos_dos_documentos` é quem pergunta, e passou a ser
    # perguntado a cada abertura do PAINEL (os cartões «Mais Vendidos» e
    # «Mais Rentáveis»), e não só quando alguém pede um relatório à mão. Sem
    # índice, cada abertura varria `fat_vendas` de ponta a ponta — a colecção
    # que cresce com cada conta de cinco lojas, para sempre.
    #
    # Não é único: a unicidade do `id` está garantida noutro sítio (a reserva
    # atómica da emissão), e declará-la aqui era arriscar que a criação do
    # índice falhasse numa colecção com um duplicado antigo e levasse consigo
    # o arranque da API.
    ("fat_vendas", [("id", 1)], {}),
    # As PARTES de uma conta dividida (`venda.py::dividir_conta`, Plano 2C):
    # a pergunta é "quais são as partes desta conta?" — o ecrã do finalizar
    # precisa dela para mostrar quem já pagou e quanto falta receber, e a
    # gestão para ligar N faturas à conta de onde saíram.
    #
    # ESPARSO de propósito: só as filhas têm o campo. A esmagadora maioria das
    # vendas não é parte de nada, e um índice normal indexava-as todas com a
    # chave a `null` — a parte da chave que ninguém procura, e a que cresce
    # com cada venda do dia.
    ("fat_vendas", [("conta_mae_id", 1)], {"sparse": True}),
    # **UMA CONTA DE CADA VEZ POR POSTO — a garantia, e não a cortesia.**
    #
    # `venda.abrir_venda` verificava e depois inseria, sem lock e sem índice:
    # dois `POST /pos/venda` simultâneos do mesmo PC liam os dois um balcão
    # livre e inseriam os dois. Medido com o duplo de Mongo a ceder o event
    # loop em cada leitura (que é o que o Motor faz contra o Mongo real):
    # **201 e 201, duas contas abertas no mesmo posto** — e, antes da marca
    # `entregue_ao_gestor_em`, uma delas invisível no ecrã.
    #
    # A chave é `posto_em_curso` — a etiqueta `"{loja_id}|{dispositivo_id}"`
    # que `venda.abrir_venda` escreve na conta que nasce no balcão, e SÓ nela
    # (`venda._etiqueta_do_posto`).
    #
    # **A etiqueta era `"{sessao_id}|{dispositivo_id}"`, e por aí a corrida
    # atravessava-a.** Numa loja com duas caixas activas, dois `POST
    # /pos/venda` simultâneos do mesmo PC em CAIXAS DIFERENTES davam 201 +
    # 201: as chaves diferiam no `sessao_id`, e o posto ficava com duas contas
    # abertas — uma delas invisível. O âmbito da chave tem de ser o mesmo de
    # `venda._contas_do_balcao`, que é o POSTO; e é por isso que a sessão saiu
    # dela. O preço está pago em `caixa._largar_o_posto_das_contas_abertas`:
    # sem a sessão na chave, uma conta esquecida num turno fechado trancava
    # esse PC no dia seguinte, por isso o fecho tira-lhe a etiqueta.
    #
    # **Porque é que a chave é um campo derivado e não `{loja_id,
    # dispositivo_id}`.** O predicado a impor é o de
    # `venda._contas_do_balcao`, e ele exclui duas famílias: as PARTES de uma
    # conta dividida (várias por posto, de propósito) e as contas já entregues
    # ao gestor. Excluí-las no filtro parcial exigia `conta_mae_id: null` /
    # `entregue_ao_gestor_em: null` lá dentro, e a igualdade a `null` num
    # `partialFilterExpression` não é terreno em que se aposte uma garantia
    # (o `$exists: false` não é sequer aceite). Com a etiqueta, o filtro usa
    # só as duas formas que o Mongo documenta como aceites — uma igualdade e
    # um `$exists: true` — e as partes ficam de fora por não terem o campo.
    #
    # **Só se tornou expressável num índice depois de a excepção da travada
    # deixar de ser calculada.** Enquanto "não conta a que tem reserva viva"
    # fosse uma pergunta a OUTRA colecção (`fat_refs_fiscais`), nenhum índice
    # de `fat_vendas` o podia dizer.
    #
    # **Há DOIS sítios que tiram a etiqueta**, e os dois estão escritos:
    # `venda.entregar_ao_gestor` (a conta travada deixa de ser do balcão) e
    # `caixa._largar_o_posto_das_contas_abertas` (o turno fechou, e o que
    # ficou aberto é do gestor). As outras três saídas da conta (emitida,
    # cancelada, separada) tiram-na sozinhas, porque o filtro parcial é
    # `estado: "aberta"` e uma venda que muda de estado sai do índice sem
    # ninguém lhe tocar. Os dois sítios são um a mais do que se queria — um
    # esquecimento em qualquer deles tranca um posto — e é por isso que os
    # dois são recusas EXPLICADAS e não 409 mudos: o `abrir_venda` relê o
    # posto quando o índice recusa e, se não encontrar nada, diz por extenso
    # que é uma etiqueta presa de um turno fechado e que quem a arruma é o
    # gestor (`venda._MSG_ETIQUETA_PRESA`).
    #
    # Numa base que já tenha duas `aberta` no mesmo posto (as órfãs de antes
    # desta ronda), a CRIAÇÃO falha — `criar_indices` regista o erro e o
    # módulo arranca na mesma, com a garantia de antes, que é a leitura de
    # `abrir_venda`. É o desfecho certo: recusar o arranque do POS de cinco
    # lojas por causa de contas velhas seria o estrago ao contrário.
    (
        "fat_vendas",
        [("posto_em_curso", 1)],
        {
            "unique": True,
            "partialFilterExpression": {
                "estado": "aberta",
                "posto_em_curso": {"$exists": True},
            },
        },
    ),
    # As contas que ficaram ABERTAS num turno já fechado (`caixa.py::
    # _contas_esquecidas`, o ecrã do gestor). A pergunta é
    # `{"estado": "aberta"}` ordenada por `criada_em`, e sem índice era um
    # varrimento completo de `fat_vendas` — a mesma colecção que ao fim de um
    # ano tem centenas de milhares de vendas RESOLVIDAS, que são exactamente
    # as que esta pergunta não quer ver.
    #
    # PARCIAL, e pela mesma razão do índice único de sessão aberta aqui em
    # cima: o que interessa indexar são as poucas contas `aberta` que existem
    # em cada instante (as em curso, mais as esquecidas), e não as 365 mil
    # que já viraram fatura. O `criada_em` na chave serve a ordenação da
    # listagem sem uma passagem extra. Uma venda que muda de estado sai
    # sozinha do índice.
    (
        "fat_vendas",
        [("criada_em", 1)],
        {"partialFilterExpression": {"estado": "aberta"}},
    ),
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
    # **A RESERVA ATÓMICA da nota de crédito** (`nota_credito.py`), e a
    # mesma garantia que `fat_refs_fiscais.ext_ref` dá à Fatura Simplificada:
    # o duplo-toque no botão «Emitir Nota de Crédito» insere DUAS vezes a
    # mesma intenção, e a segunda apanha `DuplicateKeyError` antes de falar
    # com o Vendus. Uma NC a dobrar é um documento fiscal a mais entregue à
    # AT, tão caro como uma fatura a dobrar.
    #
    # ÚNICO sobre o `id`, que é o id da INTENÇÃO gerado pelo ecrã e repetido
    # em cada retentativa do mesmo toque — e não sobre o documento de origem:
    # contra a mesma fatura pode haver várias notas parciais, e um único
    # sobre a origem recusava a segunda para sempre (é o que o POS da
    # Pizzaria faz, e é por isso que lá só existe a NC TOTAL).
    ("fat_notas_credito", [("id", 1)], {"unique": True}),
    # O TRAVÃO do que já foi creditado: "quanto desta fatura já saiu?" — a
    # pergunta que `nota_credito.linhas_creditaveis` faz antes de deixar
    # creditar mais.
    ("fat_notas_credito", [("documento_id", 1)], {}),
    # O Ponto de Caixa e o Z: as devoluções DESTE turno
    # (`caixa._notas_de_credito_do_turno`), e a nota em curso que trava o
    # fecho (`caixa._nota_de_credito_em_curso`).
    ("fat_notas_credito", [("sessao_id", 1)], {}),
    # **A IDEMPOTÊNCIA DA FILA DE IMPRESSÃO** (`impressao.py::enfileirar`), e
    # a mesma forma de garantia que `fat_refs_fiscais.ext_ref` dá à emissão:
    # o que já está na fila não entra outra vez.
    #
    # A emissão da Fatura Simplificada é idempotente por desenho — uma
    # segunda tentativa da mesma venda encontra o documento já gravado e
    # devolve-o tal e qual (`fiscal._gravar_documento`). Sem este índice,
    # essa segunda tentativa (um retry do POS, uma retoma de reserva incerta,
    # a reconciliação de uma reserva presa) enfileirava um SEGUNDO talão do
    # mesmo cliente e uma SEGUNDA ficha da mesma cozinha, e a operadora
    # ficava com dois papéis iguais sem perceber qual era qual.
    #
    # A chave é escolhida por quem enfileira, e é aí que se decide o que pode
    # repetir: `talao:{documento_id}` e `pedido:{venda_id}` são fixos (a mesma
    # venda nunca produz dois), e a segunda via, a gaveta e o pedido pedido à
    # mão trazem um uuid novo de propósito — ali, dois toques no botão são
    # duas coisas.
    ("fat_trabalhos_impressao", [("chave", 1)], {"unique": True}),
    # A pergunta do programa da loja, e a única que corre em ciclo: "o que é
    # que esta loja tem à espera?", pela ordem de chegada
    # (`impressao.recolher`). Com poucos segundos entre cada pergunta, isto
    # sem índice era um varrimento completo da colecção a cada volta, em
    # cinco lojas ao mesmo tempo, o dia inteiro.
    ("fat_trabalhos_impressao", [("loja_id", 1), ("estado", 1), ("criado_em", 1)], {}),
    # **O TTL — a única colecção do módulo que se apaga sozinha.** O campo é
    # uma DATA a sério (e não a string ISO que o resto do módulo grava): o
    # Mongo só sabe expirar documentos por um campo do tipo Date, e um índice
    # TTL sobre uma string não apaga nada — nem dá erro, o que é pior.
    # `expireAfterSeconds: 0` quer dizer "apaga quando a data que lá está
    # passar", e é `impressao.enfileirar` que a põe a uma semana de distância.
    #
    # Sete dias é para uma pessoa poder ir ver o que aconteceu ao papel de
    # ontem ou da semana passada. Nada de fiscal se perde aqui — os
    # documentos ficam em `fat_documentos`, e o talão certificado com eles.
    ("fat_trabalhos_impressao", [("apagar_depois_de", 1)], {"expireAfterSeconds": 0}),
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


async def _tem_indice_unico(db, coleccao: str, campo: str) -> bool:
    """Lê os índices REAIS de uma colecção e diz se existe um ÚNICO sobre
    aquele campo — nunca assume nada a partir de `criar_indices` ter corrido
    sem excepção. Qualquer falha a ler (Atlas em baixo, por exemplo) conta
    como AUSENTE, nunca como "não consegui verificar, assumo que está lá".

    Uma função e não duas cópias: são duas as reservas atómicas do módulo (a
    da Fatura Simplificada, em `fat_refs_fiscais.ext_ref`, e a da nota de
    crédito, em `fat_notas_credito.id`) e as duas têm de ser confirmadas com
    o MESMO critério — uma segunda cópia deste laço divergia da primeira no
    dia em que uma delas fosse corrigida."""
    try:
        indices = await db[coleccao].index_information()
    except Exception as e:  # noqa: BLE001 — falha na verificação = ausente
        logger.error(
            "[faturacao] não foi possível confirmar o índice único de %s.%s: %s",
            coleccao, campo, e,
        )
        return False
    for detalhes in indices.values():
        if list(detalhes.get("key") or []) == [(campo, 1)] and detalhes.get("unique"):
            return True
    return False


async def indice_idempotencia_presente(db) -> bool:
    """O índice único de `fat_refs_fiscais.ext_ref` — a garantia central da
    idempotência da Fatura Simplificada."""
    return await _tem_indice_unico(db, COLECOES["refs_fiscais"], "ext_ref")


async def indice_notas_credito_presente(db) -> bool:
    """O índice único de `fat_notas_credito.id` — a mesma garantia para a
    nota de crédito, que é o que impede o duplo-toque no botão «Emitir Nota
    de Crédito» de entregar DUAS notas reais à AT."""
    return await _tem_indice_unico(db, COLECOES["notas_credito"], "id")


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


_indice_notas_credito_ok = None  # type: Optional[bool]  # None = ainda não confirmado


def marcar_indice_notas_credito(ok: Optional[bool]) -> None:
    """O gémeo de `marcar_indice_idempotencia`, para a reserva atómica da
    nota de crédito."""
    global _indice_notas_credito_ok
    _indice_notas_credito_ok = ok


def indice_notas_credito_confirmado() -> bool:
    """`True` só depois de `arrancar()` confirmar que o índice único de
    `fat_notas_credito.id` existe. `nota_credito.emitir_nota_credito`
    consulta-o antes de gravar a intenção: sem ele, dois toques no botão
    inserem as duas intenções e saem DUAS notas de crédito reais da mesma
    fatura — o mesmo estrago da fatura a dobrar, com o sinal ao contrário."""
    return _indice_notas_credito_ok is True
