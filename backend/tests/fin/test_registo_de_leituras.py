"""**Nenhuma sincronização passa sem ficar escrita.**

O `bol_leituras` existe para responder a uma pergunta que hoje não tem
resposta: *um dia sem vendas foi um dia fechado, ou um dia em que ninguém
leu?* O escritor salta os dias a zero (não gera linha em `fin_sales`) e não
existe `last_sync` em lado nenhum — sem este registo, os dois casos são
indistinguíveis.

O registo vive num INVÓLUCRO (`_fin_vendus_run_account` envolve
`_fin_vendus_run_account_sem_registo`) e não nas rotas, porque são sete as
rotas que lhe chamam. É essa decisão que estes testes defendem: se alguém
amanhã voltar a pôr o registo nas rotas e esquecer uma, isto fica vermelho.
"""
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


class ColeccaoFalsa:
    """Guarda o que lhe mandam escrever. `insert_one` é assíncrono, como o do
    Motor."""

    def __init__(self):
        self.escritos = []

    async def insert_one(self, doc):
        self.escritos.append(doc)


class BaseFalsa:
    def __init__(self):
        self.bol_leituras = ColeccaoFalsa()


@pytest.fixture
def registos(monkeypatch):
    """Substitui só a base de dados. O `_bol_registar_leitura` real corre tal
    e qual — é ele que está a ser posto à prova."""
    base = BaseFalsa()
    monkeypatch.setattr(server, "db", base)
    return base.bol_leituras.escritos


def _corre(coro):
    import asyncio

    return asyncio.get_event_loop().run_until_complete(coro)


def test_uma_corrida_que_correu_bem_fica_escrita(monkeypatch, registos):
    async def falso(acc, since, until, with_cost):
        return {"written": 12, "stores": [{"store": "Belém", "complete": True}], "errors": []}

    monkeypatch.setattr(server, "_fin_vendus_run_account_sem_registo", falso)
    _corre(server._fin_vendus_run_account({}, "2026-08-18", "2026-08-20", False))

    assert len(registos) == 1
    r = registos[0]
    assert r["origem"] == "vendus"
    assert r["since"] == "2026-08-18" and r["until"] == "2026-08-20"
    assert r["escritas"] == 12
    assert r["completa"] is True
    assert r["comecou_em"] and r["terminou_em"]


def test_uma_corrida_com_erros_fica_marcada_como_incompleta(monkeypatch, registos):
    """É este o caso que interessa: a leitura de uma loja falhou, o
    `write_store` não gravou nada — e sem registo isso desaparecia no log."""
    async def falso(acc, since, until, with_cost):
        return {
            "written": 0,
            "stores": [{"store": "Oeiras", "complete": False}],
            "errors": ["loja 'Oeiras': a leitura da página 1 não devolveu documentos"],
        }

    monkeypatch.setattr(server, "_fin_vendus_run_account_sem_registo", falso)
    _corre(server._fin_vendus_run_account({}, "2026-08-18", "2026-08-20", False))

    assert registos[0]["completa"] is False
    assert "página 1" in registos[0]["erros"][0]


def test_uma_corrida_que_REBENTOU_tambem_fica_escrita(monkeypatch, registos):
    """O `finally` não é zelo a mais. Uma exceção que suba daqui é apanhada
    pelas rotas, mas sem registo não deixava rasto nenhum — e é precisamente
    o caso em que alguém vai querer saber o que aconteceu."""
    async def rebenta(acc, since, until, with_cost):
        raise RuntimeError("o Vendus devolveu lixo")

    monkeypatch.setattr(server, "_fin_vendus_run_account_sem_registo", rebenta)
    with pytest.raises(RuntimeError):
        _corre(server._fin_vendus_run_account({}, "2026-08-18", "2026-08-20", False))

    assert len(registos) == 1, "uma corrida que rebentou tem de ficar escrita à mesma"
    assert registos[0]["completa"] is False
    assert "rebentou" in registos[0]["erros"][0]


def test_o_moloni_regista_pela_mesma_porta(monkeypatch, registos):
    async def falso(cfg, since, until):
        return {"written": 3, "errors": []}

    monkeypatch.setattr(server, "_fin_moloni_run_sem_registo", falso)
    _corre(server._fin_moloni_run({}, "2026-08-18", "2026-08-20"))

    assert registos[0]["origem"] == "moloni"
    assert registos[0]["escritas"] == 3


def test_um_registo_que_falha_nao_derruba_a_sincronizacao(monkeypatch):
    """A ordem de importância: o dinheiro primeiro. Se a escrita do registo
    falhar (Mongo em baixo), a sincronização que correu bem tem de devolver o
    seu resultado à mesma."""
    class BasePartida:
        class bol_leituras:  # noqa: N801
            @staticmethod
            async def insert_one(doc):
                raise RuntimeError("mongo em baixo")

    async def falso(acc, since, until, with_cost):
        return {"written": 7, "stores": [], "errors": []}

    monkeypatch.setattr(server, "db", BasePartida())
    monkeypatch.setattr(server, "_fin_vendus_run_account_sem_registo", falso)
    out = _corre(server._fin_vendus_run_account({}, "2026-08-18", "2026-08-20", False))

    assert out["written"] == 7
