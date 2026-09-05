"""**"Não há documentos" não é uma falha de leitura.**

Medido em produção a 2026-09-05, com a chave real: o Vendus responde

    GET documents/?since=...&until=...&store_id=... -> **404**
    {"errors": [{"code": "A001", "message": "No data"}]}

quando não existem documentos no intervalo. Uma loja fechada nesse dia devolve
exactamente isto.

Este ficheiro existe por causa de um defeito **meu**, apanhado em produção dez
minutos depois de ir para o ar: a guarda que impede uma falha de apagar vendas
lia este 404 como leitura falhada, e passava a recusar a gravação — e a acusar
uma avaria de hora a hora — numa loja que apenas não tinha vendido. As duas
coisas têm de continuar a distinguir-se para sempre, e é isso que aqui se
prende: **vazio é `[]` e a leitura fica completa; falha é `None` e a leitura
trava.**
"""
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


class RespostaFalsa:
    def __init__(self, status, corpo):
        self.status_code = status
        self._corpo = corpo

    def json(self):
        if isinstance(self._corpo, Exception):
            raise self._corpo
        return self._corpo


class ClienteFalso:
    """Substitui o `httpx.Client` que o `_fin_vendus_http` abre."""

    resposta = None
    pedidos = 0

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        ClienteFalso.pedidos += 1
        return ClienteFalso.resposta


@pytest.fixture
def vendus(monkeypatch):
    ClienteFalso.pedidos = 0
    monkeypatch.setattr(server.httpx, "Client", ClienteFalso)
    return ClienteFalso


SEM_DADOS = {"errors": [{"code": "A001", "message": "No data"}]}


def test_o_404_de_sem_dados_e_uma_lista_vazia(vendus):
    """A resposta que a loja fechada dá. Tem de sair daqui como `[]` — quem
    pagina lê isso como "acabaram as páginas" e a leitura fica COMPLETA."""
    vendus.resposta = RespostaFalsa(404, SEM_DADOS)

    assert server._fin_vendus_http("chave", "documents/?x=1") == []


def test_um_404_de_verdade_continua_a_ser_falha(vendus):
    """Um 404 sem o código A001 é outra coisa (um caminho errado, um recurso
    que não existe) e não pode passar por "não há nada": passaria por leitura
    completa e mandava apagar o intervalo."""
    vendus.resposta = RespostaFalsa(404, {"errors": [{"code": "X999", "message": "Not found"}]})

    assert server._fin_vendus_http("chave", "documents/?x=1") is None


def test_um_404_com_corpo_ilegivel_e_falha(vendus):
    """Na dúvida, o lado seguro: não se grava e, por não se gravar, não se
    apaga."""
    vendus.resposta = RespostaFalsa(404, ValueError("isto não é JSON"))

    assert server._fin_vendus_http("chave", "documents/?x=1") is None


def test_o_401_continua_a_ser_falha(vendus):
    """A chave recusada é o caso que NUNCA pode passar por vazio — passava, e
    o sync apagava as vendas de três dias de todas as lojas."""
    vendus.resposta = RespostaFalsa(401, {"errors": [{"code": "A001"}]})

    assert server._fin_vendus_http("chave", "documents/?x=1") is None, (
        "o código A001 só vale num 404; num 401 a chave é que foi recusada"
    )


def test_uma_loja_sem_vendas_da_leitura_completa(monkeypatch, vendus):
    """O caminho inteiro, de ponta a ponta: a loja não vendeu nada, o Vendus
    responde 404/A001, e a função de paginação tem de dizer COMPLETA — senão
    a unidade não é gravada e o registo de leituras acusa uma avaria que não
    existe."""
    vendus.resposta = RespostaFalsa(404, SEM_DADOS)

    by_day, completa, erro = server._fin_vendus_fetch_store_days(
        "chave", "loja-1", "2026-09-02", "2026-09-05", False, {}
    )

    assert completa is True
    assert erro is None
    assert by_day == {}
