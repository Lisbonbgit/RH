"""**A prova que atravessa a fronteira**, vista do lado do POS: o corpo que este
servidor monta a sério, julgado pela classe pydantic REAL da app L'Açaí.

**Porque este ficheiro existe.** O voucher ao balcão foi construído com as DUAS
suites verdes por cima de um contrato partido: o POS mandava
`categoria_vendus_ref: None` e a porta da app recusava-o com 422; o «Remover» do
cartão dos pontos mandava `ligacao_id: null` e a porta do POS recusava-o com 422.
Ninguém deu por nenhum dos dois porque **cada lado se provou contra um BONECO do
outro** — o teste do POS finge a resposta da app (um `httpx.MockTransport`) e o
teste da app alimenta à mão um corpo que o POS nunca envia. As duas suites
podiam ficar verdes para sempre sobre uma integração que não trocava uma palavra.

Aqui não há boneco do CONTRATO. O corpo sai do construtor de verdade
(`pontos_app._linhas_para_a_app`, pela própria rota) e quem o julga é a classe de
verdade, lida do repo da app por caminho absoluto. O único duplo que resta é a
REDE — e é só isso que ele é: um transporte que grava o corpo e devolve o que o
teste mandar, porque o que aqui se prova é o que SAI daqui.

**Porque a classe da app se lê num subprocesso, e não por `sys.path` neste.** O
`database.py` da app faz `load_dotenv` do `.env` dela — que aponta para o Atlas
de **produção** — e cria o cliente do Mongo à importação. Trazer esse módulo para
dentro deste processo enchia o ambiente da suite do POS com as variáveis do
`.env` da app (chaves do Vendus incluídas, que é precisamente o que meia dúzia
de testes daqui afirmam estar ou não estar definido) e deixava um cliente
pendurado na base de produção. O subprocesso corre no venv da app, com a base
apontada ao localhost antes de qualquer importação, e não deixa cá nada.

**Sem rede e sem servidor:** o `_transporte` do httpx é um `MockTransport` e o
subprocesso só valida modelos — não abre socket nenhum.

**Se o repo da app não estiver lá, cada teste SALTA COM A RAZÃO ESCRITA.** Um
teste de contrato que se cala quando não consegue correr é pior do que não
existir: passa a verde ao lado do defeito que existe para apanhar.
"""
import json
import os
import subprocess

import httpx
import pytest

from faturacao import pontos_app
from faturacao.db import COLECOES
from tests.faturacao.test_fiscal import (
    ColeccaoFalsa,
    DbFalsa,
    _corre,
    _linha,
    _operador,
    _unicos_de,
    _venda,
)

# --- A porta da app, corrida no venv da app -------------------------------------

_APP = "/Users/matheus.moraes/applacai/backend"
_PYTHON_DA_APP = os.path.join(_APP, ".venv", "bin", "python")

# O guião corre DENTRO do venv da app. Recebe `[[classe, corpo], ...]` em stdin e
# escreve uma linha `CONTRATO:<json>` com uma entrada por corpo: `null` se a
# porta o aceitou, ou a lista dos campos recusados.
#
# A marca `CONTRATO:` existe porque a importação da app pode escrever avisos no
# stdout (o `load_dotenv`, o urllib3 do sistema): sem ela, um aviso novo
# transformava esta prova num erro de JSON e ninguém sabia porquê.
#
# `model_validate` e não `Classe(**corpo)`: é exactamente o que o FastAPI faz ao
# corpo JSON de um pedido, e é a diferença que conta — em pydantic 2 um `None`
# EXPLÍCITO não cai no default de um campo, e era esse o defeito.
_GUIAO = r"""
import json, os, sys

# Antes de importar o que quer que seja: a base do Mongo é a de TESTE. O
# `database.py` da app faz `load_dotenv` e o `.env` dela aponta para o Atlas de
# PRODUÇÃO; o `load_dotenv` não sobrepõe o que já está no ambiente, por isso
# estas três chegam para ninguém apontar lá. (Nada aqui faz uma consulta — o
# motor só liga no primeiro `await` — mas não é por isso que se deixa o cliente
# nascer virado para a produção.)
os.environ["MONGO_URL"] = "mongodb://127.0.0.1:27017"
os.environ["DB_NAME"] = "contrato-de-teste"
os.environ.setdefault("JWT_SECRET", "contrato-de-teste")

sys.path.insert(0, sys.argv[1])
import routes_pos_integracao as porta

saida = []
for classe, corpo in json.load(sys.stdin):
    try:
        getattr(porta, classe).model_validate(corpo)
        saida.append(None)
    except Exception as erro:  # noqa: BLE001 — o que interessa é O QUE recusou
        detalhe = getattr(erro, "errors", None)
        saida.append([".".join(str(p) for p in e["loc"]) for e in detalhe()]
                     if detalhe else ["%s: %s" % (type(erro).__name__, erro)])
print("CONTRATO:" + json.dumps(saida))
"""


def _a_porta_da_app(*pares):
    """`("VoucherReq", corpo)` → `[None]` se a app o aceita, ou os campos que ela
    recusa. É a classe pydantic REAL da app, no venv dela."""
    if not os.path.isdir(_APP) or not os.path.exists(_PYTHON_DA_APP):
        pytest.skip(
            "A PROVA DE FRONTEIRA NÃO CORREU: o repo da app L'Açaí não está em %s "
            "(ou falta-lhe o venv). O corpo que o POS monta ficou SEM ser julgado "
            "pela porta da app — é exactamente assim que `categoria_vendus_ref: "
            "None` foi para produção com as duas suites verdes." % _APP)
    # O corpo vai em JSON de propósito: se ele não for serializável, não cabe na
    # rede e a prova tem de cair aqui e não em produção.
    corrida = subprocess.run(
        [_PYTHON_DA_APP, "-c", _GUIAO, _APP], input=json.dumps(pares),
        capture_output=True, text=True, timeout=180)
    marca = [li for li in corrida.stdout.splitlines() if li.startswith("CONTRATO:")]
    if corrida.returncode != 0 or not marca:
        pytest.skip(
            "A PROVA DE FRONTEIRA NÃO CORREU: não se conseguiu ler a porta da app "
            "(%s). saída=%r erro=%r"
            % (_PYTHON_DA_APP, corrida.stdout[-300:], corrida.stderr[-500:]))
    return json.loads(marca[-1][len("CONTRATO:"):])


# --- A rede a fingir (e SÓ a rede) ----------------------------------------------


class _AppAFingir:
    """Grava cada pedido e devolve o que o teste mandar.

    Escrito aqui e não importado de `test_os_pontos_da_app`: este ficheiro é a
    rede de segurança dos outros e não pode ficar vermelho por uma mudança nos
    duplos deles."""

    def __init__(self):
        self.pedidos = []
        self._corpo = {}

    def responde(self, corpo):
        self._corpo = corpo

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        return httpx.Response(200, json=self._corpo)

    def corpos(self):
        return [json.loads(p.content) for p in self.pedidos]


@pytest.fixture
def app(monkeypatch):
    falsa = _AppAFingir()
    monkeypatch.setattr(pontos_app, "_transporte", httpx.MockTransport(falsa))
    monkeypatch.setenv("APP_LACAI_URL", "http://olacai-api:8001")
    monkeypatch.setenv("APP_LACAI_CHAVE", "chave-de-teste")
    return falsa


# --- O cenário ------------------------------------------------------------------

# O id da categoria no Vendus: a única chave partilhada pelos dois catálogos.
_REF_ACAIS = "1289461"

# Uma conta de balcão com o caso do DIA 1 lá dentro: um açaí cuja categoria já
# tem a ponte preenchida e um doce cuja categoria não tem nada — que no dia 1 são
# todas, porque o enchimento é manual.
_PRODUTOS = [
    {"id": "prod-1", "nome": "Açaí Regular", "categoria_id": "cat-acais"},
    {"id": "prod-2", "nome": "Brownie", "categoria_id": "cat-doces"},
]
_CATEGORIAS = [
    {"id": "cat-acais", "nome": "Açaís", "vendus_ref": _REF_ACAIS},
    {"id": "cat-doces", "nome": "Doces", "vendus_ref": None},
]


def _db(vendas=None, **mais):
    coleccoes = {
        COLECOES["vendas"]: ColeccaoFalsa(vendas if vendas is not None else [
            _venda(linhas=[_linha(id="linha-1"),
                           _linha(id="linha-2", produto_id="prod-2")])]),
        COLECOES["produtos"]: ColeccaoFalsa(list(_PRODUTOS)),
        COLECOES["categorias"]: ColeccaoFalsa([dict(c) for c in _CATEGORIAS]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([
            {"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
             "estado": "aberta"}]),
    }
    coleccoes.update(mais)
    return DbFalsa(coleccoes)


def _pedir_o_voucher(monkeypatch, db, ligacao_id="lig-1"):
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)
    return _corre(pontos_app.voucher_ao_balcao(
        "venda-1", pontos_app.PedidoVoucher(ligacao_id=ligacao_id),
        operador=_operador()))


# --- O corpo do /voucher --------------------------------------------------------


def test_o_corpo_do_VOUCHER_com_uma_categoria_SEM_PONTE_passa_a_porta_da_app(
        monkeypatch, app):
    """**O desencontro que foi para produção.** A linha cuja categoria não tem
    `vendus_ref` viaja com `categoria_vendus_ref: None` — de propósito, e no dia
    1 são todas —, e em pydantic 2 um `None` explícito NÃO cai no default de um
    `str`: a porta da app recusava a LISTA INTEIRA com 422.

    E o pior não era o 422: `escolher_voucher` lê qualquer resposta que não tenha
    a forma do contrato como «não sei», a conta segue como estava e **o cartão da
    caixa fica MUDO**. Bastava uma água sem ponte na conta para o açaí que casava
    na perfeição não levar desconto, e ninguém ao balcão tinha como saber porquê
    — que é o pior desfecho de todos (regra de ouro 2).

    Prova-se também a forma `""`: a mesma coisa do ponto de vista da app
    (categoria sem ponte) e a que o POS passaria a mandar se algum dia deixasse
    de distinguir vazio de ausente. As duas terem de servir é o que dispensa uma
    das pontas de subir primeiro."""
    _pedir_o_voucher(monkeypatch, _db())
    corpo = app.corpos()[0]

    # A guarda anti-vacuidade: sem a linha a `None` no corpo, o resto deste teste
    # valida um corpo que não tem o caso do dia 1 e fica verde por nada.
    refs = [li["categoria_vendus_ref"] for li in corpo["linhas"]]
    assert refs == [_REF_ACAIS, None], (
        "o caso do dia 1 desapareceu do corpo (%r) — sem a linha cuja categoria "
        "não tem `vendus_ref` este teste não prova nada" % (refs,))

    com_vazio = json.loads(json.dumps(corpo))
    com_vazio["linhas"][1]["categoria_vendus_ref"] = ""
    assert _a_porta_da_app(("VoucherReq", corpo), ("VoucherReq", com_vazio)) == [None, None]


def test_o_corpo_do_AVISO_DE_LIBERTACAO_passa_a_porta_da_app(monkeypatch, app):
    """O segundo corpo que o POS manda pela mesma porta: **as `linhas` vazias que
    dizem «esta venda ficou sem desconto, liberta o voucher»**.

    É o que impede o desfecho da regra de ouro 3 — o cliente paga tudo E perde a
    recompensa: a app já reservou o voucher e já armou o `/creditar` com ele, e
    esta conta não levou desconto nenhum. Aqui força-se pelo caminho do contrato
    partido (voucher escolhido sem linha alvo), que é uma das saídas que o
    aciona.

    Um corpo recusado à porta seria a libertação a não acontecer **em silêncio**:
    `escolher_voucher` engole tudo o que corra mal, e tem de o fazer (nada daqui
    pode impedir uma fatura de sair). Por isso é aqui que se prende."""
    app.responde({"voucher_id": "vch-1", "valor": 7.2, "titulo": "Açaí Médio grátis"})
    _pedir_o_voucher(monkeypatch, _db())

    libertacao = [c for c in app.corpos() if c.get("linhas") == []]
    assert libertacao, (
        "o POS não avisou a app de que a venda ficou sem desconto — o voucher fica "
        "reservado e o /creditar consome-o: cliente sem produto e sem recompensa")
    assert _a_porta_da_app(*[("VoucherReq", c) for c in libertacao]) == [None] * len(libertacao)


def test_a_porta_do_POS_aceita_o_REMOVER_que_o_BROWSER_manda(app):
    """**O outro lado do mesmo desencontro, e a única fronteira deste ficheiro que
    não é entre dois servidores.** O «Remover» do cartão dos pontos chama esta
    rota com `ligacao_id: null` (`frontend/src/lib/pos.js::pedirVoucherDaConta`,
    literalmente `{ ligacao_id: ligacaoId || null }`) para o desconto sair da
    conta junto com o cliente.

    Com `min_length=1` isto era 422, e por aí saía dinheiro: o `catch` do ecrã
    engole o erro, a marca e o desconto FICAM na linha, e a partir daí ou a
    funcionária cobra os 7,20 € e o EMITIR recusa (a soma dos pagamentos não bate
    com um total de 0,00 € — **a fatura não sai**, com o cliente à frente), ou
    emite a 0,00 € sem ligação de pontos nenhuma: o `/creditar` nunca corre, o
    voucher nunca é consumido, e o cliente leva o açaí E fica com a recompensa.
    As duas pontas da regra de ouro 3, pelo mesmo 422.

    Nenhuma suite atravessava esta fronteira: os testes da rota constroem o
    pedido em Python, onde `ligacao_id=None` é só um argumento — nunca o corpo
    JSON que o browser escreve."""
    pedido = pontos_app.PedidoVoucher.model_validate({"ligacao_id": None})
    assert pedido.ligacao_id is None


# --- O corpo do /creditar, no EMITIR --------------------------------------------


def test_o_corpo_do_CREDITAR_de_uma_conta_OFERECIDA_passa_a_porta_da_app(monkeypatch):
    """O corpo do EMITIR: a linha da fila que nasce depois de a Fatura Simplificada
    existir, montada pelo `enfileirar_credito` de verdade a partir da venda e do
    documento — nunca escrita à mão num teste.

    O cenário é o do dia 1 do voucher ao balcão, e é o que nunca tinha existido:
    um açaí **oferecido**, FS de **0,00 €** e **sem pagamento nenhum**. Três
    campos onde este contrato se poderia partir sem ninguém ver: `total: 0.0`
    (que a app aceita e desde o voucher já não recusa), `meios_pagamento: []`
    (uma conta a zero não tem pagamentos) e o `numero`/`emitido_em` do documento.

    Este é o corpo que vai para a rede tal e qual: `enviar` manda o `payload`
    gravado sem lhe tocar (só o `fatura_email` o remonta, para lhe juntar o PDF),
    e é por isso que se valida o payload da linha."""
    monkeypatch.setattr(pontos_app, "tentar_ja", lambda db, linha_id: None)
    db = _db(
        vendas=[_venda(
            linhas=[_linha(desconto_eur=8.99, voucher_id="vch-1")],
            pagamentos=[],
            pontos_ligacao={"id": "lig-1", "primeiro_nome": "Ana"})],
        **{
            COLECOES["lojas"]: ColeccaoFalsa([{"id": "loja-1", "nome": "Belém"}]),
            COLECOES["utilizadores"]: ColeccaoFalsa([{"id": "op-1", "nome": "Rafaela"}]),
            COLECOES["pontos_app"]: ColeccaoFalsa(
                [], indices_unicos=_unicos_de("fat_pontos_app")),
        })
    _corre(pontos_app.enfileirar_credito(db, "venda-1", {
        "id": "doc-1", "modo": "normal", "atcud": "JJ3K-1081",
        "numero": "FS 06P2026/1081", "emitido_em": "2026-09-22T11:59:58+00:00",
        "total": 0.0, "deposito": 0.0,
    }))

    fila = db[COLECOES["pontos_app"]]._documentos
    assert len(fila) == 1, "o crédito da conta oferecida não entrou na fila"
    corpo = fila[0]["payload"]
    assert (corpo["total"], corpo["meios_pagamento"]) == (0.0, []), (
        "o cenário deixou de ser o do açaí oferecido")
    recusados = _a_porta_da_app(("CreditarReq", corpo))
    assert recusados == [None], (
        "a porta do /creditar da app recusa o corpo que o POS lhe manda no EMITIR "
        "(campos: %r) — são 24 h de 422 e os pontos perdidos na mesma" % (recusados,))
