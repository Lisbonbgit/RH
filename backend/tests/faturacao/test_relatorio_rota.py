"""**As portas do relatório diário** — a `CRON_KEY`, a lista de quem recebe, e
o que acontece quando não há ninguém para receber.

Esta é a única peça do relatório que toca no Mongo e na rede, e por isso é a
única onde estas perguntas se podem fazer. As contas do dinheiro têm os seus
testes noutro sítio, sem nada disto pelo meio.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import relatorio_rota as rota_mod
from faturacao.relatorio_rota import (
    DefinicoesEntrada,
    EnvioEntrada,
    cron_relatorio_diario,
    gravar_definicoes,
    ler_definicoes,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, registo, find_one_devolve=None, find_devolve=None):
        self.registo = registo
        self._find_one = find_one_devolve
        self._find = find_devolve or []

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return dict(self._find_one) if self._find_one else None

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", filtro))
        return _Cursor(list(self._find))

    async def update_one(self, filtro, atualizacao, upsert=False):
        self.registo.append(("update_one", filtro, atualizacao, upsert))
        return None


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **kw):
        return self

    async def to_list(self, limite):
        return self._docs[:limite]


class DbFalsa:
    def __init__(self, colecoes):
        self.colecoes = colecoes

    def __getitem__(self, nome):
        return self.colecoes.get(nome) or ColeccaoFalsa([])


def _db(registo, definicoes=None):
    from faturacao.db import COLECOES
    return DbFalsa({COLECOES["definicoes"]: ColeccaoFalsa(
        registo, find_one_devolve=definicoes)})


# --- A porta do cron ---------------------------------------------------------


def test_o_cron_RECUSA_sem_a_chave(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "a-chave-certa")
    with pytest.raises(HTTPException) as e:
        _corre(cron_relatorio_diario(key="outra-coisa"))
    assert e.value.status_code == 403


def test_o_cron_RECUSA_quando_o_servidor_nao_tem_chave_nenhuma(monkeypatch):
    """Sem `CRON_KEY` no servidor, a rota tem de se fechar — nunca abrir-se a
    toda a gente porque a guarda não está configurada. É o mesmo engano que
    um `VENDUS_MODE` por omissão: a falta de configuração escolher o lado
    perigoso, em silêncio."""
    monkeypatch.delenv("CRON_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        _corre(cron_relatorio_diario(key=""))
    assert e.value.status_code == 403


def test_o_cron_com_a_chave_certa_e_a_lista_VAZIA_nao_envia_e_diz_porque(monkeypatch):
    """Não é um erro: é o estado de quem ainda não configurou ninguém. Mas
    tem de aparecer no registo do cron, senão parece que correu bem."""
    monkeypatch.setenv("CRON_KEY", "k")
    registo = []
    monkeypatch.setattr(rota_mod, "obter_db", lambda: _db(registo, {"emails": [], "ativo": True}))
    resultado = _corre(cron_relatorio_diario(key="k"))
    assert resultado == {"enviado": False, "razao": "sem destinatários"}


def test_o_cron_RESPEITA_o_interruptor_de_desligado(monkeypatch):
    """Desligado no backoffice é uma decisão, não uma avaria — e o cron não
    pode passar por cima dela."""
    monkeypatch.setenv("CRON_KEY", "k")
    registo = []
    monkeypatch.setattr(rota_mod, "obter_db",
                        lambda: _db(registo, {"emails": ["a@b.pt"], "ativo": False}))
    resultado = _corre(cron_relatorio_diario(key="k"))
    assert resultado["enviado"] is False
    assert "desligad" in resultado["razao"]


# --- A lista de destinatários ------------------------------------------------


def test_sem_nada_configurado_a_lista_vem_VAZIA_e_ligada(monkeypatch):
    """O estado normal de quem nunca lá foi. O ecrã não pode ter de distinguir
    "nunca configurado" de "configurado a vazio" — são a mesma coisa."""
    registo = []
    monkeypatch.setattr(rota_mod, "obter_db", lambda: _db(registo, None))
    assert _corre(ler_definicoes(_={})) == {"emails": [], "ativo": True}


def test_gravar_TIRA_os_repetidos_e_baixa_as_maiusculas(monkeypatch):
    """`Matheus@X.pt` e `matheus@x.pt` são a mesma pessoa: sem isto recebia o
    relatório duas vezes."""
    registo = []
    monkeypatch.setattr(rota_mod, "obter_db", lambda: _db(registo, None))
    resultado = _corre(gravar_definicoes(
        DefinicoesEntrada(emails=["Matheus@X.pt", "matheus@x.pt", "bruce@x.pt"]),
        _={}))
    assert resultado["emails"] == ["matheus@x.pt", "bruce@x.pt"]


def test_um_email_MAL_ESCRITO_e_recusado_a_porta():
    """Um endereço inválido na lista faz o Resend recusar o envio INTEIRO — o
    relatório da noite não sai para NINGUÉM, não só para quem se enganou.
    Melhor recusá-lo aqui, com o dono à frente do ecrã."""
    with pytest.raises(Exception):
        DefinicoesEntrada(emails=["isto-nao-e-um-email"])


def test_enviar_agora_sem_lista_e_sem_endereco_EXPLICA_se(monkeypatch):
    registo = []
    monkeypatch.setattr(rota_mod, "obter_db", lambda: _db(registo, {"emails": [], "ativo": True}))
    with pytest.raises(HTTPException) as e:
        _corre(rota_mod.enviar_agora(EnvioEntrada(), _={}))
    assert e.value.status_code == 400
    assert "Configuração" in e.value.detail


# --- As rotas existem e estão protegidas -------------------------------------


def test_as_rotas_de_gestao_EXIGEM_gestor_e_a_do_cron_NAO():
    """As duas famílias não se misturam: a do cron não pode exigir um JWT (é
    chamada por um script), e as de gestão não podem aceitar uma chave de
    query em vez de um gestor.

    Perguntado ao router a sério — um prefixo errado responde 404 e o cron das
    23:30 falha todas as noites em silêncio."""
    from faturacao import router
    from faturacao.auth import gestor_atual

    def dependencias(rota):
        encontrados = set()

        def procura(d):
            for filha in d.dependencies:
                encontrados.add(filha.call)
                procura(filha)

        procura(rota.dependant)
        return encontrados

    por_caminho = {r.path: r for r in router.routes if hasattr(r, "dependant")}
    cron = por_caminho.get("/api/faturacao/cron/relatorio-diario")
    assert cron is not None, "A rota do cron não existe."
    assert gestor_atual not in dependencias(cron)

    for caminho in ("/api/faturacao/relatorio-diario/definicoes",
                    "/api/faturacao/relatorio-diario/enviar-agora"):
        assert caminho in por_caminho, caminho
        assert gestor_atual in dependencias(por_caminho[caminho]), caminho
