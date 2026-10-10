"""O CRM está montado no portal a sério: o server.py inclui o router do CRM e
chama o arranque dele (plano T1.9).

Molde: tests/fin/test_a_rota_dos_extratos_existe.py — pergunta-se à app do
portal, não ao que se acha que se escreveu. Os outros testes do CRM montam o
router numa app própria e nunca importam o server.py; este é o único que o faz.

O server.py lê `MONGO_URL`, `DB_NAME` e `JWT_SECRET` ao ser importado. Os três
já vêm do tests/crm/conftest.py (ler o docstring de lá: sem isso o
`JWT_SECRET` congelava no valor por omissão); os dois `setdefault` repetem o
molde e não mudam nada. Nenhum teste aqui abre a base: `TestClient` sem `with`
não corre o arranque, e os testes do arranque trocam as bases por duplos.

As corrotinas correm com `correr` (tests/crm/duplos.py), nunca com o
asyncio.run (correções do plano, linha do §10).
"""
import asyncio
import inspect
import logging
import os
import time
from collections import Counter

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import crm  # noqa: E402
import crm.db  # noqa: E402
import faturacao  # noqa: E402
import plataformas  # noqa: E402
import server  # noqa: E402

from .duplos import BaseFalsa, correr  # noqa: E402


def _rotas(rotas):
    """(método, caminho, função) de cada rota HTTP; cada método conta à parte.

    A função é a do pacote: o `include_router` copia a rota mas guarda o mesmo
    `endpoint`, por isso uma rota com o mesmo caminho escrita no server.py
    conta como outra."""
    return Counter(
        (metodo, r.path, r.endpoint)
        for r in rotas
        if isinstance(r, APIRoute)
        for metodo in r.methods
    )


def _do_crm(contagem):
    return Counter({
        rota: n for rota, n in contagem.items()
        if rota[1] == "/api/crm" or rota[1].startswith("/api/crm/")
    })


def _caminhos_no_app():
    return {r.path for r in server.app.routes}


# ---------------------------------------------------------------- rotas


def test_saude_e_eu_estao_servidas_pelo_portal():
    caminhos = _caminhos_no_app()
    assert "/api/crm/saude" in caminhos
    assert "/api/crm/eu" in caminhos


def test_as_rotas_do_crm_no_portal_sao_exatamente_as_do_router_do_crm():
    """Nenhuma rota `/api/crm/*` foge à classificação do teste de proteção
    (T1.8), que só olha para `crm.router`: uma rota do CRM escrita direto no
    server.py, o router incluído duas vezes ou com outro prefixo falham aqui."""
    no_app = _do_crm(_rotas(server.app.routes))
    do_router = _rotas(crm.router.routes)
    assert do_router, "o router do CRM não tem rotas"
    assert no_app == do_router, (
        "a mais no portal: %s; em falta no portal: %s"
        % (sorted((m, c) for m, c, _f in no_app - do_router),
           sorted((m, c) for m, c, _f in do_router - no_app))
    )


def test_a_faturacao_e_as_plataformas_continuam_montadas():
    no_app = _rotas(server.app.routes)
    for pacote in (faturacao, plataformas):
        em_falta = _rotas(pacote.router.routes) - no_app
        assert not em_falta, "%s: %s" % (pacote.__name__, sorted((m, c) for m, c, _f in em_falta))
    assert "/api/faturacao/saude" in _caminhos_no_app()
    assert "/api/health" in _caminhos_no_app()


def test_saude_responde_pela_app_do_portal():
    resposta = TestClient(server.app).get("/api/crm/saude")
    assert resposta.status_code == 200
    assert resposta.json() == {"estado": "ok", "modulo": "crm"}


def test_eu_e_membros_sem_sessao_dao_403_pela_app_do_portal():
    cliente = TestClient(server.app)
    for caminho in ("/api/crm/eu", "/api/crm/membros"):
        resposta = cliente.get(caminho)
        assert resposta.status_code == 403, caminho
        assert resposta.json() == {"detail": "Not authenticated"}, caminho


# ---------------------------------------------------------------- arranque


def test_o_arranque_do_portal_chama_o_do_crm_a_seguir_ao_da_faturacao():
    fonte = inspect.getsource(server.startup_event)
    assert "crm_arrancar" in fonte
    assert fonte.index("await faturacao_arrancar()") < fonte.index("await crm_arrancar()")


def _arranque_com_duplos(monkeypatch, obter_db_do_crm):
    """Prepara o `startup_event` sem base nenhuma: o admin master e a
    Faturação passam a apontar a ordem, e os índices do Financeiro vão para
    uma `BaseFalsa`. Devolve (ordem, base do portal)."""
    ordem = []
    base_portal = BaseFalsa()

    async def _admin_master():
        ordem.append("admin_master")

    async def _faturacao():
        ordem.append("faturacao")

    def _obter_db():
        ordem.append("crm")
        return obter_db_do_crm()

    monkeypatch.setattr(server, "ensure_master_admin_exists", _admin_master)
    monkeypatch.setattr(faturacao, "arrancar", _faturacao)
    monkeypatch.setattr(server, "db", base_portal)
    monkeypatch.setattr(crm.db, "obter_db", _obter_db)
    return ordem, base_portal


def test_o_arranque_do_portal_cria_os_indices_do_crm_depois_da_faturacao(monkeypatch):
    base_crm = BaseFalsa()
    ordem, base_portal = _arranque_com_duplos(monkeypatch, lambda: base_crm)

    correr(server.startup_event())

    assert ordem == ["admin_master", "faturacao", "crm"]
    assert len(base_crm.crm_membros.chamadas("create_index")) == len(
        [1 for (colecao, _c, _o) in crm.db.INDICES if colecao == "crm_membros"]
    )
    # O resto do arranque continua: os índices do Financeiro vêm depois.
    assert base_portal.fin_sales.chamadas("create_index")
    assert base_portal.fin_movements.chamadas("create_index")


def test_uma_avaria_do_crm_no_arranque_nao_derruba_o_portal(monkeypatch, caplog):
    """O URI mongodb+srv:// da produção pode rebentar ao construir o cliente
    (DNS do Atlas). O portal sobe na mesma e cria os índices do Financeiro."""

    def _obter_db_rebentada():
        raise RuntimeError("falha de configuração simulada (DNS do Atlas)")

    ordem, base_portal = _arranque_com_duplos(monkeypatch, _obter_db_rebentada)

    with caplog.at_level(logging.ERROR, logger="crm"):
        correr(server.startup_event())  # não pode levantar

    assert ordem == ["admin_master", "faturacao", "crm"]
    assert any(r.getMessage().startswith("[crm]") for r in caplog.records)
    assert base_portal.fin_sales.chamadas("create_index")


def test_o_arranque_do_portal_nao_fica_preso_nos_indices_do_crm(monkeypatch):
    """Mongo lento: o CRM desiste dos índices em LIMITE_INDICES_SEGUNDOS e o
    portal acaba de arrancar (o HEALTHCHECK do Dockerfile não espera)."""
    comecou = []

    async def _criar_indices_pendurado(base):
        comecou.append(base)
        await asyncio.sleep(3)

    ordem, base_portal = _arranque_com_duplos(monkeypatch, BaseFalsa)
    monkeypatch.setattr(crm.db, "criar_indices", _criar_indices_pendurado)
    monkeypatch.setattr(crm, "LIMITE_INDICES_SEGUNDOS", 0.05)

    inicio = time.monotonic()
    correr(server.startup_event())

    assert time.monotonic() - inicio < 1.0
    assert ordem == ["admin_master", "faturacao", "crm"]
    assert len(comecou) == 1
    assert base_portal.fin_sales.chamadas("create_index")
