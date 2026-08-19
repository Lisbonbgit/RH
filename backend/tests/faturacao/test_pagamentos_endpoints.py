"""Comportamento dos endpoints editar/apagar de tipos de pagamento (sem base de dados).

Cobre a guarda de 'protegido' (spec §12): o tipo de pagamento usado pela app
L'Açaí não pode ser alterado nem apagado por este ecrã — senão a app passava a
cobrar no Stripe sem emitir factura, em silêncio. Mesmo padrão de duplo de
base de dados que test_lojas.py e test_indices.py.
"""
import asyncio
import base64
from copy import deepcopy

import httpx
import pytest
from fastapi import HTTPException

from faturacao import pagamentos as pagamentos_mod
from faturacao.pagamentos import TipoPagamentoEntrada, apagar, editar, metodos_vendus
from faturacao.vendus.cliente import ClienteVendus


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find_one` real descodifica BSON de fresco a cada chamada: o resultado
    NUNCA está ligado ao que está no Mongo, e duas leituras nunca devolvem o
    MESMO objecto. Um duplo enlatado que devolve sempre o dicionário do teste
    deixa passar por ALIASING tanto uma asserção sobre a fixture (que o código
    de produção mutou sem escrever nada) como um `editar` que respondesse com
    o objecto que leu em vez de reler o que ficou gravado. Já apanhou um caso
    real neste módulo (`cancelar_venda`, em faturacao/venda.py).

    Cópia FUNDA por regra da casa: os tipos de pagamento são hoje planos, mas
    é a mesma função em todos os duplos do módulo — uma que fosse rasa "porque
    ali dá" era a que ficava errada quando a fixture crescesse.
    """
    return deepcopy(documento)


class ResultadoDelete:
    """Duplo do resultado de delete_one do Motor — só o campo que o código usa."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: regista as chamadas e devolve resultados à escolha do teste."""

    def __init__(self, registo, find_one_devolve=None, delete_one_devolve=0):
        self.registo = registo
        self._find_one_devolve = find_one_devolve
        self._delete_one_devolve = delete_one_devolve

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return _como_o_motor(self._find_one_devolve)

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        return None

    async def delete_one(self, filtro):
        self.registo.append(("delete_one", filtro))
        return ResultadoDelete(self._delete_one_devolve)


class DbFalsa:
    def __init__(self, coleccao):
        self._coleccao = coleccao

    def __getitem__(self, nome):
        return self._coleccao


_DADOS = TipoPagamentoEntrada(nome="Glovo", tipo_fiscal="TB", da_troco=False)


def test_editar_tipo_protegido_e_recusado_409(monkeypatch):
    """A guarda central da tarefa: o tipo usado pela app L'Açaí não pode ser alterado."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve={"id": "x", "protegido": True})
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar("x", _DADOS, _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "update_one" for chamada in registo)


def test_editar_tipo_inexistente_devolve_404(monkeypatch):
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve=None)
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar("nao-existe", _DADOS, _={}))
    assert excinfo.value.status_code == 404


def test_editar_tipo_normal_e_editado(monkeypatch):
    """Regressão: um tipo não protegido continua a poder ser editado."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve={"id": "x", "protegido": False})
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    _corre(editar("x", _DADOS, _={}))
    assert any(chamada[0] == "update_one" for chamada in registo)


def test_apagar_tipo_protegido_e_recusado_409(monkeypatch):
    """A mesma guarda ao apagar: sem isto, a app L'Açaí passava a cobrar sem
    emitir factura, em silêncio."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve={"id": "x", "protegido": True})
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar("x", _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "delete_one" for chamada in registo)


def test_apagar_tipo_inexistente_devolve_404(monkeypatch):
    """Um tipo que não existe não pode ser apagado."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve=None, delete_one_devolve=0)
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar("nao-existe", _={}))
    assert excinfo.value.status_code == 404
    assert "Tipo de pagamento não encontrado" in excinfo.value.detail


def test_apagar_tipo_normal_e_apagado(monkeypatch):
    """Regressão: o caminho feliz continua a devolver sucesso."""
    registo = []
    coleccao = ColeccaoFalsa(
        registo, find_one_devolve={"id": "x", "protegido": False}, delete_one_devolve=1
    )
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    resultado = _corre(apagar("x", _={}))
    assert resultado == {"apagado": True}


# --- GET /tipos-pagamento/metodos-vendus -------------------------------------
#
# A rota que fecha o buraco: até aqui o `vendus_payment_method_id` de cada
# tipo era posto à mão na base de dados de produção, e sem ele
# `fiscal.py::finalizar` recusa a emissão com 422. Estes testes nunca tocam a
# rede — `httpx.MockTransport` injectado no ClienteVendus REAL (não um duplo
# do cliente), para o caminho pedido e a leitura da resposta ficarem cobertos
# de ponta a ponta, como em test_emissao.py.

# Os métodos que a conta tem hoje, lidos ao vivo do Vendus — incluindo o
# `App-Online` que a app L'Açaí usa em produção. `id` vem NÚMERO do Vendus, de
# propósito: é metade do que estes testes existem para provar.
METODOS_DO_VENDUS = [
    {"id": 360335513, "title": "App-Online", "type": "TB"},
    {"id": 145234375, "title": "Dinheiro", "type": "NU"},
    {"id": 145234376, "title": "Multibanco", "type": "CD"},
    {"id": 176663039, "title": "Bolt", "type": "TB"},
    {"id": 176663078, "title": "Glovo", "type": "TB"},
    {"id": 176663138, "title": "Uber Eats", "type": "TB"},
    {"id": 176680254, "title": "Stripe", "type": "TB"},
    {"id": 145234379, "title": "Transferência Bancária", "type": "TB"},
]


def _liga_ao_vendus_falso(monkeypatch, handler):
    """Faz a rota falar com um Vendus de mentira, pelo ClienteVendus a sério.

    Substitui-se a CLASSE (não o método) para o `with ClienteVendus(...)` da
    rota continuar a ser exercido tal e qual — incluindo o caminho pedido, a
    paginação e a tradução de erros, que é onde vivem as armadilhas."""

    def fabrica(chave, **kwargs):
        return ClienteVendus(chave, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(pagamentos_mod, "ClienteVendus", fabrica)


def _conta_configurada(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"chave-teste","company_nif":"517542510"}]')
    monkeypatch.setenv("FAT_NIF", "517542510")


def test_metodos_vendus_lista_feliz(monkeypatch):
    """O formato exacto de que o ecrã depende: id (TEXTO), titulo, tipo_fiscal
    — e pela ordem da conta Vendus, que é a que o dono tem à frente no
    backoffice do Vendus enquanto compara as duas listas."""
    _conta_configurada(monkeypatch)
    _liga_ao_vendus_falso(
        monkeypatch,
        lambda pedido: httpx.Response(
            200, json=METODOS_DO_VENDUS, headers={"X-Paginator-Pages": "1"}
        ),
    )

    metodos = _corre(metodos_vendus(_={}))

    assert metodos == [
        {"id": "360335513", "titulo": "App-Online", "tipo_fiscal": "TB"},
        {"id": "145234375", "titulo": "Dinheiro", "tipo_fiscal": "NU"},
        {"id": "145234376", "titulo": "Multibanco", "tipo_fiscal": "CD"},
        {"id": "176663039", "titulo": "Bolt", "tipo_fiscal": "TB"},
        {"id": "176663078", "titulo": "Glovo", "tipo_fiscal": "TB"},
        {"id": "176663138", "titulo": "Uber Eats", "tipo_fiscal": "TB"},
        {"id": "176680254", "titulo": "Stripe", "tipo_fiscal": "TB"},
        {"id": "145234379", "titulo": "Transferência Bancária", "tipo_fiscal": "TB"},
    ]


def test_metodos_vendus_id_sai_sempre_como_texto(monkeypatch):
    """O id vai ser gravado em `vendus_payment_method_id` (Optional[str]) e
    comparado por `str(...)` no fecho de caixa (fiscal.py:1689). Um int a
    escapar daqui fazia `"145234375" == 145234375` — falso em silêncio, e o
    fecho deixava de reconhecer o dinheiro como dinheiro."""
    _conta_configurada(monkeypatch)
    _liga_ao_vendus_falso(
        monkeypatch,
        lambda pedido: httpx.Response(
            200, json=[{"id": 145234375, "title": "Dinheiro", "type": "NU"}],
            headers={"X-Paginator-Pages": "1"},
        ),
    )

    metodos = _corre(metodos_vendus(_={}))

    assert [type(m["id"]) for m in metodos] == [str]
    assert metodos[0]["id"] == "145234375"


def test_metodos_vendus_usa_a_chave_da_conta_configurada(monkeypatch):
    """A chave vem de VENDUS_ACCOUNTS pelo NIF — não de nada que venha de fora."""
    _conta_configurada(monkeypatch)
    autorizacoes = []

    def handler(pedido: httpx.Request):
        autorizacoes.append(pedido.headers.get("Authorization"))
        return httpx.Response(200, json=[], headers={"X-Paginator-Pages": "1"})

    _liga_ao_vendus_falso(monkeypatch, handler)
    _corre(metodos_vendus(_={}))

    esperado = "Basic " + base64.b64encode(b"chave-teste:").decode()
    assert autorizacoes == [esperado]


def test_metodos_vendus_ignora_metodo_sem_id(monkeypatch):
    """O único uso desta lista é escolher um id para gravar. Uma linha sem id
    não se pode escolher — mostrá-la só serviria para o dono carregar nela e
    nada acontecer."""
    _conta_configurada(monkeypatch)
    _liga_ao_vendus_falso(
        monkeypatch,
        lambda pedido: httpx.Response(
            200,
            json=[{"title": "Sem id", "type": "TB"}, {"id": 1, "title": "Com id", "type": "NU"}],
            headers={"X-Paginator-Pages": "1"},
        ),
    )

    assert _corre(metodos_vendus(_={})) == [
        {"id": "1", "titulo": "Com id", "tipo_fiscal": "NU"}
    ]


def test_metodos_vendus_codigo_fiscal_desconhecido_e_mostrado_na_mesma(monkeypatch):
    """Um código que não esteja em TIPOS_FISCAIS é para MOSTRAR, não para
    esconder: escondê-lo fazia desaparecer da lista precisamente o método
    novo que o dono estaria à procura."""
    _conta_configurada(monkeypatch)
    _liga_ao_vendus_falso(
        monkeypatch,
        lambda pedido: httpx.Response(
            200, json=[{"id": 42, "title": "Método futuro", "type": "ZZ"}],
            headers={"X-Paginator-Pages": "1"},
        ),
    )

    assert _corre(metodos_vendus(_={})) == [
        {"id": "42", "titulo": "Método futuro", "tipo_fiscal": "ZZ"}
    ]


def test_metodos_vendus_sem_conta_configurada_diz_o_que_falta(monkeypatch):
    """Sem VENDUS_ACCOUNTS não pode ser um 500 nem uma lista vazia: tem de
    dizer o que falta, e sem chegar a tocar na rede."""
    monkeypatch.delenv("VENDUS_ACCOUNTS", raising=False)
    monkeypatch.setenv("FAT_NIF", "517542510")
    pedidos = []

    def handler(pedido: httpx.Request):
        pedidos.append(pedido.url.path)
        return httpx.Response(200, json=METODOS_DO_VENDUS, headers={"X-Paginator-Pages": "1"})

    _liga_ao_vendus_falso(monkeypatch, handler)

    with pytest.raises(HTTPException) as excinfo:
        _corre(metodos_vendus(_={}))

    assert excinfo.value.status_code == 400
    assert "VENDUS_ACCOUNTS" in excinfo.value.detail
    assert "517542510" in excinfo.value.detail
    assert pedidos == []  # nem sequer se tentou perguntar ao Vendus


def test_metodos_vendus_conta_de_outro_nif_nao_serve(monkeypatch):
    """Uma conta configurada para OUTRO NIF é o mesmo que não haver conta —
    nunca se lê a lista de métodos da empresa errada."""
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"k","company_nif":"111111111"}]')
    monkeypatch.setenv("FAT_NIF", "517542510")

    with pytest.raises(HTTPException) as excinfo:
        _corre(metodos_vendus(_={}))

    assert excinfo.value.status_code == 400
    assert "517542510" in excinfo.value.detail


def test_metodos_vendus_em_baixo_devolve_502_e_nunca_lista_vazia(monkeypatch):
    """Vendus em baixo → 502 com a mensagem do erro. Uma lista vazia fazia o
    ecrã dizer "não há métodos", que é uma afirmação diferente e falsa."""
    _conta_configurada(monkeypatch)
    _liga_ao_vendus_falso(
        monkeypatch, lambda pedido: httpx.Response(503, text="Service Unavailable")
    )

    with pytest.raises(HTTPException) as excinfo:
        _corre(metodos_vendus(_={}))

    assert excinfo.value.status_code == 502
    assert "Vendus" in excinfo.value.detail
    assert "503" in excinfo.value.detail  # a mensagem do erro vai lá dentro


def test_metodos_vendus_sem_rede_devolve_502(monkeypatch):
    """A outra maneira de o Vendus estar em baixo: nem chega a haver resposta."""
    _conta_configurada(monkeypatch)

    def handler(pedido: httpx.Request):
        raise httpx.ConnectError("ligação recusada")

    _liga_ao_vendus_falso(monkeypatch, handler)

    with pytest.raises(HTTPException) as excinfo:
        _corre(metodos_vendus(_={}))

    assert excinfo.value.status_code == 502
    assert "ligação recusada" in excinfo.value.detail


def test_metodos_vendus_erro_http_do_vendus_devolve_502(monkeypatch):
    """Uma chave inválida (403) também é 502 com a razão à vista — nunca um
    500 nem uma lista vazia."""
    _conta_configurada(monkeypatch)
    _liga_ao_vendus_falso(
        monkeypatch,
        lambda pedido: httpx.Response(403, json={"errors": [{"code": "P001"}]}),
    )

    with pytest.raises(HTTPException) as excinfo:
        _corre(metodos_vendus(_={}))

    assert excinfo.value.status_code == 502
    assert "403" in excinfo.value.detail


def test_metodos_vendus_conta_vazia_e_lista_vazia(monkeypatch):
    """O ÚNICO caso em que [] é a resposta certa: a conta existe, respondeu, e
    não tem métodos nenhuns (o 404/A001 do Vendus quer dizer isso mesmo)."""
    _conta_configurada(monkeypatch)
    _liga_ao_vendus_falso(
        monkeypatch,
        lambda pedido: httpx.Response(404, json={"errors": [{"code": "A001", "message": "No data"}]}),
    )

    assert _corre(metodos_vendus(_={})) == []


def test_metodos_vendus_nunca_escreve_no_vendus(monkeypatch):
    """A promessa do cabeçalho do módulo, provada: só GET. Estes métodos são
    da conta que a app L'Açaí usa para faturar em produção."""
    _conta_configurada(monkeypatch)
    verbos = []

    def handler(pedido: httpx.Request):
        verbos.append(pedido.method)
        return httpx.Response(200, json=METODOS_DO_VENDUS, headers={"X-Paginator-Pages": "1"})

    _liga_ao_vendus_falso(monkeypatch, handler)
    _corre(metodos_vendus(_={}))

    assert verbos == ["GET"]
