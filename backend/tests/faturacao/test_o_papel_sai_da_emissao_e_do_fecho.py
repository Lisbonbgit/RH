"""**O fio entre a venda e o papel — percorrido, não lido.**

`test_impressao.py` prova que a fila funciona. Isto prova outra coisa, e é a
que já falhou neste repositório mais do que uma vez: que alguém a CHAMA.

Uma função de enfileirar perfeita e ninguém a chamar é o defeito mais barato
de escrever e o mais caro de descobrir — descobre-se ao balcão, com o cliente
à frente e o talão que nunca sai. Por isso aqui não se chama `enfileirar`:
chama-se a **rota real** (`fiscal.finalizar`, `caixa.fechar_caixa`), com os
duplos que os testes dessas rotas já usam, e olha-se para a fila no fim.

E prova-se a promessa inversa, que é a mais importante das duas:
**a fatura continua boa quando a impressão falha.** O talão é consequência do
documento fiscal, nunca condição dele.
"""
import base64

import pytest

from faturacao import db as db_mod
from faturacao import escpos
from faturacao import impressao as imp
from faturacao import pontos_app as pa
from faturacao.db import COLECOES

from . import test_fiscal as tf
from . import test_nota_credito as tnc
from .test_venda import ColeccaoFalsa, DbFalsa, _corre


@pytest.fixture(autouse=True)
def _indice_confirmado():
    """A rota `finalizar` recusa emitir sem o índice de idempotência
    confirmado no arranque (I3). É a mesma marca que `test_fiscal.py` põe, e
    é posta aqui pela mesma razão: sem ela estes testes mediam o 503 da
    configuração em falta e nunca chegavam ao papel."""
    db_mod.marcar_indice_idempotencia(True)
    yield
    db_mod.marcar_indice_idempotencia(None)


@pytest.fixture
def envios(monkeypatch):
    """A tentativa imediata substituída por um registo. Aqui prova-se o PAPEL:
    uma tarefa em segundo plano a falar com a app ficava viva depois do teste, e
    o asyncio só guarda referências FRACAS às tarefas (molde de
    `test_os_pontos_da_app.envios`)."""
    enviados = []
    monkeypatch.setattr(pa, "tentar_ja", lambda db, linha_id: enviados.append(linha_id))
    return enviados


class Explode:
    """Uma colecção que levanta em CADA escrita — o Atlas em baixo a meio de uma
    emissão que já entregou a fatura à Autoridade Tributária."""

    async def insert_one(self, doc):
        raise RuntimeError("Atlas em baixo")


def _chave_do_trabalho(doc):
    return doc.get("chave")


def _com_fila(db, qr=()):
    """Acrescenta ao duplo de `test_fiscal` as três colecções deste fio, com os
    índices únicos a serem cumpridos.

    **`fat_pontos_app` com `unico=` e não à solta:** o `DbFalsa.__getitem__` faz
    `setdefault`, por isso uma colecção nova nasce SEM índice nenhum — e uma
    prova de que a mesma emissão não manda dois emails passava por acaso. A
    chave é a mesma do índice de `db.py` (`fat_pontos_app.chave`), e é ela que
    decide se uma emissão a passar duas vezes faz um envio ou dois."""
    db._coleccoes[COLECOES["trabalhos_impressao"]] = ColeccaoFalsa(
        [], [], unico=_chave_do_trabalho)
    db._coleccoes[COLECOES["pontos_app"]] = ColeccaoFalsa(
        [], [], unico=_chave_do_trabalho)
    db._coleccoes[COLECOES["pontos_qr"]] = ColeccaoFalsa([], list(qr))
    return db


def _fila(db):
    return db._coleccoes[COLECOES["trabalhos_impressao"]]._documentos


def _emails(db):
    return [linha for linha in db._coleccoes[COLECOES["pontos_app"]]._documentos
            if linha["tipo"] == "fatura_email"]


# --- A emissão ----------------------------------------------------------------


class _VendusNormal(tf.ClienteEmissaoVendusFalso):
    """O duplo do Vendus da rota a devolver uma fatura REAL (modo `normal`). O
    `_bruto()` de `test_fiscal` devolve `tests`, e em `tests` o papel sai sempre
    — sem isto, o caso da preferência ligada passava pela razão errada."""

    def __init__(self, chave):
        super().__init__(chave)
        self.resposta_criar = tf._bruto(modo="normal")


def _finalizar(db, monkeypatch, cliente=None, pontos_ligacao=None, nif=None):
    tf._configura_vendus_env(monkeypatch)
    monkeypatch.setattr(tf.fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(
        tf.fiscal_mod, "ClienteEmissaoVendus", cliente or tf.ClienteEmissaoVendusFalso)
    tf.ClienteEmissaoVendusFalso.instancias.clear()
    return _corre(tf.finalizar(
        "venda-1",
        tf.PedidoFinalizarVenda(
            pagamentos=[tf.PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)],
            pontos_ligacao=pontos_ligacao, nif=nif),
        operador=tf._operador(),
    ))


def _db_de_venda(qr=()):
    return _com_fila(tf._db(
        vendas=[tf._venda(linhas=[tf._linha()])],
        tipos_pagamento=[tf._tipo_pagamento()],
    ), qr=qr)


def test_FINALIZAR_uma_venda_poe_UM_papel_na_fila_e_e_o_do_CLIENTE(monkeypatch):
    """O caminho inteiro: a rota que a operadora toca, o Vendus a devolver o
    documento, e o papel na fila da loja. **Um, e não dois.**

    O dono corrigiu o pressuposto de que esta rota partia: «não tem nada a
    ver com fatura, o staff é o único que faz a impressão do pedido». A ficha
    da cozinha sai quando alguém carrega em «Imprimir Pedido»
    (`impressao.imprimir_pedido`) — que é como um balcão trabalha: pica-se,
    manda-se para a cozinha, cobra-se no fim. Emitir a fatura já não manda
    papel nenhum à cozinha; se mandasse, uma conta dividida por três mandava
    três fichas do mesmo copo.

    Apagar a linha do `finalizar` que enfileira deixa todo o
    `test_impressao.py` verde — a fila continua perfeita, e o cliente fica
    sem o documento em papel que a lei lhe deve."""
    db = _db_de_venda()
    resultado = _finalizar(db, monkeypatch)
    assert resultado["estado"] == "emitida"

    (trabalho,) = _fila(db)
    assert trabalho["impressora"] == imp.CAIXA
    assert trabalho["tipo"] == imp.TALAO
    assert trabalho["loja_id"] == "loja-1"
    assert trabalho["estado"] == imp.PENDENTE
    assert imp.COZINHA not in [t["impressora"] for t in _fila(db)]


def test_o_papel_do_cliente_e_o_talao_CERTIFICADO_que_o_vendus_devolveu(monkeypatch):
    """Byte a byte o que veio da emissão, e não uma reconstrução nossa: é o
    documento fiscal em papel, com o ATCUD e o QR que a app de fidelização
    lê."""
    db = _db_de_venda()
    _finalizar(db, monkeypatch)
    documento = db._coleccoes[COLECOES["documentos"]]._documentos[0]
    talao = [t for t in _fila(db) if t["impressora"] == imp.CAIXA][0]
    assert base64.b64decode(talao["bytes_b64"]) == documento["talao_escpos"]


def test_a_FATURA_CONTINUA_BOA_quando_a_fila_de_impressao_rebenta(monkeypatch):
    """**A promessa que sustenta o desenho todo.**

    Uma emissão bem sucedida — com Fatura Simplificada REAL já entregue à
    Autoridade Tributária — a devolver erro por causa do papel era o pior
    desfecho possível: o ecrã lê um erro com a venda aparentemente por emitir
    como «não saiu nada, pode repetir», e a operadora emite a segunda fatura
    do mesmo cliente.

    Aqui a fila rebenta em cheio (a colecção levanta em cada escrita) e a
    resposta da rota tem de sair igual: venda emitida, documento gravado."""
    db = _db_de_venda()
    db._coleccoes[COLECOES["trabalhos_impressao"]] = Explode()
    resultado = _finalizar(db, monkeypatch)
    assert resultado["estado"] == "emitida"
    assert resultado["documento"]["atcud"] == "ATCUD-1"


def test_um_RETRY_da_mesma_emissao_nao_faz_um_segundo_talao(monkeypatch):
    """A rota é idempotente por desenho: a segunda tentativa encontra o
    documento já gravado e devolve-o tal e qual. Sem a chave da fila, essa
    segunda passagem enfileirava um segundo talão do mesmo cliente — e a
    operadora ficava com dois papéis iguais sem saber qual era qual."""
    db = _db_de_venda()
    _finalizar(db, monkeypatch)
    # A venda volta a `aberta` sem se lhe tirar a reserva nem o documento: é o
    # retrato de um retry que chega depois de a fatura já ter saído.
    db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] = "aberta"
    _finalizar(db, monkeypatch)
    assert len(_fila(db)) == 1


# --- O papel que NÃO sai: a fatura por email ------------------------------------
#
# Os quatro casos do desenho, todos pela ROTA REAL. A regra que os une: o papel
# só se salta quando a linha do email foi MESMO criada — as duas decisões são
# uma só, e não há desfecho em que não saia nem papel nem email.

_LIGACAO = {"id": "lig-1", "primeiro_nome": "Ana"}
_QR_LIGADO = [{"ligacao_id": "lig-1", "fatura_por_email": True}]


def test_1_SEM_LIGACAO_sai_papel_e_nao_ha_linha_de_email_nenhuma(monkeypatch, envios):
    """O caso normal, que é o de quase toda a gente: quem não mostra a app leva
    talão, como sempre."""
    db = _db_de_venda()

    resultado = _finalizar(db, monkeypatch, cliente=_VendusNormal)

    assert resultado["estado"] == "emitida"
    # Só o talão: o impulso da gaveta já vem dentro dele, e um segundo abria-a
    # duas vezes.
    assert [t["tipo"] for t in _fila(db)] == [imp.TALAO]
    assert _emails(db) == []
    assert resultado["documento"]["fatura_por_email"] is False


def test_2_COM_A_PREFERENCIA_LIGADA_nao_sai_papel_e_fica_a_linha_do_email(monkeypatch, envios):
    """O caso que a funcionalidade existe para fazer. A preferência é lida de
    `fat_pontos_qr` — do servidor — e não do corpo do EMITIR."""
    db = _db_de_venda(qr=_QR_LIGADO)

    resultado = _finalizar(db, monkeypatch, cliente=_VendusNormal,
                           pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    # **Sem talão, mas a gaveta abre na mesma.** O impulso da gaveta vinha
    # DENTRO do talão do Vendus; sem papel ficava fechada — e é lá que se
    # guarda o talão do Multibanco e de onde sai o troco.
    [gaveta] = _fila(db)
    assert gaveta["tipo"] == imp.GAVETA, "com a fatura a ir por email, o talão não se imprime"
    assert gaveta["impressora"] == imp.CAIXA
    assert gaveta["loja_id"] == "loja-1"
    assert base64.b64decode(gaveta["bytes_b64"]) == escpos.abrir_gaveta()
    # **A decisão vai na resposta, porque é ela que o ecrã lê.** Refeita no
    # browser, a frase «não é preciso esperar pelo papel» aparecia por cima de
    # um talão que saiu mesmo — e nenhum dos casos abaixo se distinguia deste
    # sem esta chave.
    assert resultado["documento"]["fatura_por_email"] is True
    documento = db._coleccoes[COLECOES["documentos"]]._documentos[0]
    [linha] = _emails(db)
    assert linha["chave"] == "fatura_email:%s" % documento["id"]
    assert linha["loja_id"] == "loja-1", "a loja é por onde o alarme do POS conta"
    assert linha["payload"] == {
        "ligacao_id": "lig-1",
        "documento_id": documento["id"],
        "vendus_document_id": documento["vendus_document_id"],
        "numero": "FS 2026/1",
        "modo": "normal",
    }
    # **`in` e não `== [id]`.** Nesta MESMA chamada a `finalizar`, o
    # `_ligar_venda_ao_documento` já enfileirou o crédito dos pontos
    # (`fiscal.py:1431-1433`) — modo normal, ligação gravada na venda antes da
    # emissão, ATCUD presente — e o `_enfileirar` de lá também chama
    # `tentar_ja`. O id do crédito está na lista ANTES de o papel se decidir; o
    # que se prende aqui é que o do email também lá vai parar.
    assert linha["id"] in envios, "a tentativa imediata do email tem de sair logo"


def test_2b_a_MESMA_emissao_a_passar_duas_vezes_manda_UM_email_e_nao_traz_papel(monkeypatch, envios):
    """**O `DuplicateKeyError` conta como sucesso.** O gancho da emissão corre
    mais do que uma vez por venda (o retry que reencontra o documento, a
    reconciliação de uma reserva presa); devolver `False` na segunda passagem
    fazia sair papel numa fatura que já ia por email."""
    db = _db_de_venda(qr=_QR_LIGADO)
    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)
    db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] = "aberta"

    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)

    assert len(_emails(db)) == 1
    assert [t["tipo"] for t in _fila(db)] == [imp.GAVETA], (
        "a segunda passagem não pode fazer sair papel nem abrir a gaveta outra vez")


def test_3_com_a_FILA_DO_EMAIL_a_rebentar_o_PAPEL_SAI_a_mesma(monkeypatch, envios):
    """**O desfecho que não pode existir é não sair nem papel nem email.** Aqui
    a colecção da fila levanta em cada escrita: a linha do email não chega a
    existir, `enfileirar_fatura_email` devolve `False`, e o talão sai como se
    nada disto existisse — com a resposta da rota igual, porque as duas chamadas
    estão no mesmo `try/except`."""
    db = _db_de_venda(qr=_QR_LIGADO)
    db._coleccoes[COLECOES["pontos_app"]] = Explode()

    resultado = _finalizar(db, monkeypatch, cliente=_VendusNormal,
                           pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    assert len(_fila(db)) == 1, "sem linha de email, o papel tem de sair"
    assert resultado["documento"]["fatura_por_email"] is False, (
        "a fila rebentou e o papel saiu: o ecrã TEM de falar de papel")


def test_4_em_MODO_TESTS_sai_papel_e_nao_se_manda_email_nenhum(monkeypatch, envios):
    """Uma fatura em `tests` não existe na AT. Mandá-la por email ao cliente era
    entregar-lhe um papel com ar de fatura que não é fatura nenhuma — e o `mode`
    de um documento de testes nem sequer devolve PDF pela porta normal."""
    db = _db_de_venda(qr=_QR_LIGADO)

    resultado = _finalizar(db, monkeypatch, pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    assert len(_fila(db)) == 1
    assert _emails(db) == []
    assert resultado["documento"]["fatura_por_email"] is False


def test_uma_fatura_SEM_ID_DO_VENDUS_sai_em_PAPEL(monkeypatch, envios):
    """**A guarda que impede o único desfecho proibido.** O Vendus só é recusado
    quando faltam o `id` E o `atcud` (`vendus/emissao._documento_da_criacao`):
    um 2xx com ATCUD e sem `id` é aceite de propósito e grava
    `vendus_document_id: None` — é por isso que o botão «PDF da fatura» do
    backoffice tem um 422 dedicado (`documentos._MSG_SEM_ID_NO_VENDUS`).

    Sem esta guarda o papel saltava-se e `_pdf_da_fatura` devolvia `b""` para
    sempre: 13 tentativas, `falhado` às 24 h, e o cliente sem talão E sem
    email."""
    class _SemId(_VendusNormal):
        def __init__(self, chave):
            super().__init__(chave)
            self.resposta_criar = tf._bruto(modo="normal", id=None)

    db = _db_de_venda(qr=_QR_LIGADO)

    resultado = _finalizar(db, monkeypatch, cliente=_SemId, pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    assert len(_fila(db)) == 1, "sem id do Vendus não há PDF — o papel tem de sair"
    assert _emails(db) == []
    assert resultado["documento"]["fatura_por_email"] is False


def test_com_NIF_ESCRITO_a_fatura_vai_A_MESMA_por_email(monkeypatch, envios):
    """**O NIF não decide nada — o seletor do cliente é o único que manda.**
    Palavras do dono: «depende da opção se quer ou não por email a fatura. o
    seletor é que manda.»

    O NIF vai escrito na fatura como sempre foi — a emissão copia-o da venda
    para o documento (`fiscal.py:1266`) — e é ESSA fatura, com NIF, que segue
    para o email da conta de quem mostrou o QR. Quem mostra a app e quem pede a
    fatura são a mesma pessoa; num grupo só uma fica com os pontos e, quando
    querem faturas separadas, dividem a conta, e aí cada parte leva o seu QR e
    o seu NIF.

    A guarda antiga (papel a sair só por haver NIF escrito) custava 1 em cada
    10 faturas: 10,4% das vendas levam NIF e só 1,6% são partes de conta
    dividida.

    **O teste inverteu-se, não se apagou.** O caso do NIF continua coberto; o
    que mudou é o que se espera dele — agora prova que o NIF NÃO muda nada."""
    db = _db_de_venda(qr=_QR_LIGADO)

    _finalizar(db, monkeypatch, cliente=_VendusNormal,
               pontos_ligacao=_LIGACAO, nif="219363935")

    assert [t["tipo"] for t in _fila(db)] == [imp.GAVETA], (
        "com a preferência ligada, o NIF não faz sair papel")
    documento = db._coleccoes[COLECOES["documentos"]]._documentos[0]
    assert documento["cliente_nif"] == "219363935", (
        "o NIF vai escrito na fatura como sempre foi")
    # **`[linha] = _emails(db)` e nunca uma igualdade à colecção toda:** nesta
    # MESMA chamada a `finalizar`, o `_ligar_venda_ao_documento` já pôs a linha
    # do CRÉDITO dos pontos na mesma fila (`fiscal.py:1431-1433`). São duas
    # linhas em `fat_pontos_app`, e só uma delas é o email.
    [linha] = _emails(db)
    assert linha["chave"] == "fatura_email:%s" % documento["id"]


def test_sem_LINHA_NO_QR_o_papel_sai_mesmo_com_a_ligacao_na_venda(monkeypatch, envios):
    """A ligação na venda não chega: um `pontos_ligacao` forjado no corpo do
    EMITIR não pode fazer desaparecer o documento de ninguém. Sem a linha do
    servidor — porque expirou, porque a escrita falhou, porque o cliente não
    pediu — sai papel."""
    db = _db_de_venda()

    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)

    assert len(_fila(db)) == 1
    assert _emails(db) == []


def test_com_a_preferencia_DESLIGADA_na_linha_do_qr_sai_papel(monkeypatch, envios):
    db = _db_de_venda(qr=[{"ligacao_id": "lig-1", "fatura_por_email": False}])

    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)

    assert len(_fila(db)) == 1
    assert _emails(db) == []


# --- A devolução --------------------------------------------------------------
#
# A NOTA DE CRÉDITO é um documento fiscal REAL como a Fatura Simplificada, e o
# cliente que devolve leva papel para casa exactamente como o que compra.
# Aqui não se chama `enfileirar_nota_emitida`: chama-se a ROTA
# (`nota_credito.emitir_nota_credito`), com os duplos do `test_nota_credito`,
# e olha-se para a fila no fim — que é a única coisa que apanha o defeito que
# isto vem fechar (`nota_credito.py` não tinha UMA chamada à impressão).


def _db_de_nota():
    db = tnc._db_nc()
    db._coleccoes[COLECOES["trabalhos_impressao"]] = ColeccaoFalsa(
        [], [], unico=_chave_do_trabalho)
    return db


def _emitir_nota(db, monkeypatch):
    db_mod.marcar_indice_notas_credito(True)
    tf._configura_vendus_env(monkeypatch)
    monkeypatch.setattr(tnc.nc_mod, "ClienteEmissaoVendus", tnc.VendusNCFalso)
    tnc.VendusNCFalso.instancias.clear()
    tnc.VendusNCFalso.emitidos = 0
    monkeypatch.setattr(tnc.nc_mod, "obter_db", lambda: db)
    try:
        return _corre(tnc.emitir_nota_credito(
            "doc-1", tnc._pedido(), operador=tnc._operador()))
    finally:
        db_mod.marcar_indice_notas_credito(None)


def test_EMITIR_uma_NOTA_DE_CREDITO_poe_UM_papel_na_fila_e_e_o_do_CLIENTE(monkeypatch):
    """**O cliente que devolve não pode sair da loja sem nada em papel.**

    Medido antes desta correcção, pelas rotas reais: emitir a fatura punha
    UM papel na fila, emitir a nota de crédito por cima punha ZERO —
    `nota_credito.py` não tinha uma única chamada a `impressao.enfileirar`. E
    o passo 8.6 do INSTALAR-IMPRESSAO.md manda o dono emitir uma nota de
    crédito: ele ficava à espera de papel que não vinha.

    **UM, e é o do balcão.** A ficha da cozinha não sai daqui pela mesma
    razão que não sai da fatura: quem manda para a cozinha é o staff, pelo
    botão."""
    db = _db_de_nota()
    resultado = _emitir_nota(db, monkeypatch)
    assert resultado["atcud"] == "ATCUD-NC-12"

    (trabalho,) = _fila(db)
    assert trabalho["impressora"] == imp.CAIXA
    assert trabalho["tipo"] == imp.TALAO
    assert trabalho["loja_id"] == "loja-1"
    assert trabalho["estado"] == imp.PENDENTE
    assert imp.COZINHA not in [t["impressora"] for t in _fila(db)]


def test_o_papel_da_nota_e_o_talao_CERTIFICADO_e_fica_GUARDADO_com_ela(monkeypatch):
    """As duas metades do mesmo defeito, e a segunda era a que fechava a
    última porta: `_gravar_documento_da_nota` construía o documento campo a
    campo SEM `talao_escpos` — que o Vendus devolve na mesma
    (`vendus/emissao._documento_da_criacao`, `output=escpos`). Sem ele, o
    botão «Imprimir» do separador Faturação respondia 422 sobre uma nota
    acabada de sair: «não tem o talão certificado guardado»."""
    db = _db_de_nota()
    _emitir_nota(db, monkeypatch)
    nota = [d for d in db._coleccoes[COLECOES["documentos"]]._documentos
            if d.get("tipo") == "NC"][0]
    assert nota["talao_escpos"] == tnc._bruto_nc()["talao_escpos"]
    (trabalho,) = _fila(db)
    assert base64.b64decode(trabalho["bytes_b64"]) == nota["talao_escpos"]

    # E o botão «Imprimir» da Faturação já dá papel em vez de 422.
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    segunda = _corre(imp.imprimir_segunda_via(
        nota["id"], operador={"operador_id": "op-1", "nome": "Rafaela",
                              "loja_id": "loja-1", "dispositivo_id": "pc-1"}))
    assert segunda["aceite"] is True


def test_a_NOTA_CONTINUA_BOA_quando_a_fila_de_impressao_rebenta(monkeypatch):
    """A mesma promessa da fatura, e aqui vale ainda mais: um 500 sobre uma NC
    REAL já entregue à AT convida a operadora a devolver o dinheiro outra
    vez."""
    db = _db_de_nota()

    class Explode:
        async def insert_one(self, doc):
            raise RuntimeError("Atlas em baixo")

    db._coleccoes[COLECOES["trabalhos_impressao"]] = Explode()
    resultado = _emitir_nota(db, monkeypatch)
    assert resultado["atcud"] == "ATCUD-NC-12"
    assert resultado["numero"] == "NC 05P2026/12"


# --- O fecho ------------------------------------------------------------------


def _db_de_fecho(vendas=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa([], [
            {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão"}]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([], [{
            "id": "sessao-1", "caixa_id": "caixa-1", "loja_id": "loja-1",
            "aberta_por": {"id": "op-1", "nome": "Rafaela"},
            "aberta_em": "2026-08-22T09:00:00+00:00", "fundo": 50.0,
            "estado": "aberta", "movimentos_confirmados": [],
        }]),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa([], []),
        COLECOES["vendas"]: ColeccaoFalsa([], vendas or []),
        COLECOES["notas_credito"]: ColeccaoFalsa([], []),
        COLECOES["refs_fiscais"]: ColeccaoFalsa([], []),
        COLECOES["dispositivos"]: ColeccaoFalsa([], []),
        COLECOES["trabalhos_impressao"]: ColeccaoFalsa([], [], unico=_chave_do_trabalho),
    })


def _fechar(db, monkeypatch, contado=50.0):
    from faturacao import caixa as caixa_mod

    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    return _corre(caixa_mod.fechar_caixa(
        caixa_mod.PedidoFecharCaixa(caixa_id="caixa-1", contado=contado),
        operador={"operador_id": "op-1", "nome": "Ana", "loja_id": "loja-1",
                  "dispositivo_id": "pc-1"},
    ))


def test_FECHAR_a_caixa_poe_o_Z_na_fila_da_impressora_do_balcao(monkeypatch):
    db = _db_de_fecho()
    z = _fechar(db, monkeypatch)
    assert z["estado"] == "fechada"
    (trabalho,) = _fila(db)
    assert trabalho["tipo"] == imp.Z
    assert trabalho["impressora"] == imp.CAIXA
    assert trabalho["loja_id"] == "loja-1"


def test_o_papel_do_Z_traz_os_NUMEROS_do_Z_que_ficou_gravado(monkeypatch):
    """O Z é o papel que a funcionária assina. Um papel que não corresponda ao
    que ficou gravado na sessão é a pior espécie de papel que esta loja pode
    produzir."""
    db = _db_de_fecho()
    z = _fechar(db, monkeypatch, contado=42.5)
    (trabalho,) = _fila(db)
    saiu = base64.b64decode(trabalho["bytes_b64"]).decode("cp850")
    assert "42,50" in saiu
    assert ("%.2f" % z["diferenca"]).replace(".", ",") in saiu


def test_o_FECHO_continua_feito_quando_a_fila_de_impressao_rebenta(monkeypatch):
    """Regra 3 do dono: o fecho nunca bloqueia. Um 500 aqui mandava a
    funcionária fechar outra vez uma caixa já fechada."""
    db = _db_de_fecho()

    class Explode:
        async def insert_one(self, doc):
            raise RuntimeError("Atlas em baixo")

    db._coleccoes[COLECOES["trabalhos_impressao"]] = Explode()
    z = _fechar(db, monkeypatch)
    assert z["estado"] == "fechada"
    assert z["esperado"] == 50.0


@pytest.mark.parametrize("talao, esperado", [
    (b"\x1b@talao", True), ("G0B0YWxhbw==", True), (b"", False), (None, False)])
def test_a_resposta_diz_ao_ecra_se_a_fatura_TROUXE_TALAO(talao, esperado):
    """Uma fatura confirmada sem a resposta da emissão vem sem talão: o ecrã
    não pode dizer «Talão na fila» (ver `lib/pos.js::fraseDoPapel`)."""
    from faturacao.fiscal import _resposta_documento
    assert _resposta_documento({"id": "d-1", "talao_escpos": talao})["tem_talao"] is esperado


def test_a_emissao_normal_responde_que_TEM_talao(monkeypatch):
    resultado = _finalizar(_db_de_venda(), monkeypatch)
    assert resultado["documento"]["tem_talao"] is True
