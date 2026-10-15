"""`GET /api/bolso/calendario` e `/contagem` contra um mongod REAL, com os dados da semana
normal (desenho, secção 3). As rotas chamam-se directamente, como no resto da casa."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import pytest  # noqa: E402

import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402
from .apoio import corre  # noqa: E402

DEBORA = {"user_id": sn.DEBORA, "role": "admin"}
CONTABILISTA = {"user_id": sn.CONTABILISTA, "role": "contabilista"}


@pytest.fixture
def semana(base):
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    dados["idas"].append(sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"))
    corre(sn.gravar(base, dados))
    corre(server._bolso_criar_indices())
    return base


def _loja(resposta, data, nome):
    dia = next(d for d in resposta["dias"] if d["data"] == data)
    return next(l for l in dia["lojas"] if l["nome"] == nome)


def test_o_mes_no_servidor_tem_os_buracos_as_ferias_e_as_idas(semana):
    r = corre(server.bolso_calendario(ano=2026, mes=10, current_user=DEBORA))
    assert (r["ano"], r["mes"], r["eu"], r["pode_marcar"]) == (2026, 10, sn.DEBORA, True)
    assert _loja(r, "2026-10-20", "Oeiras")["buracos"] == [{"inicio": "13:00", "fim": "22:00"}]
    assert _loja(r, "2026-10-27", "Oeiras")["buracos"] == []
    assert _loja(r, "2026-10-22", "Amadora")["buracos"] == [{"inicio": "14:00", "fim": "23:00"}]
    assert r["ausencias"] == [{"nome": "Weber", "tipo": "ferias", "inicio": "2026-10-21",
                               "fim": "2026-10-25", "loja": "Amadora"}]
    assert [(i["data"], i["nome"], i["loja"]) for i in r["idas"]] == [("2026-10-27", "Débora Ferreira", "Oeiras")]
    assert [l["nome"] for l in r["lojas"]] == ["Alfragide", "Algueirão", "Amadora", "Belém", "Benfica", "Oeiras"]


def test_o_contabilista_le_o_mes_mas_nao_pode_marcar(semana):
    r = corre(server.bolso_calendario(ano=2026, mes=10, current_user=CONTABILISTA))
    assert r["pode_marcar"] is False
    assert sn.CONTABILISTA not in [p["id"] for p in r["pessoas"]]


def test_a_contagem_e_do_ano_pedido(semana):
    corre(semana.bolso_idas.insert_one(sn.ida("2026-11-03", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00")))
    corre(semana.bolso_idas.insert_one(sn.ida("2025-12-30", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")))
    [linha] = corre(server.bolso_calendario_contagem(ano=2026, current_user=CONTABILISTA))
    assert linha["nome"] == "Débora Ferreira"
    assert linha["meses"][9:] == [1.0, 0.5, 0.0]
    assert linha["total"] == 1.5


def test_os_indices_das_idas(semana):
    indices = corre(semana.bolso_idas.index_information())
    assert [i["key"] for i in indices.values() if i.get("unique")] == [
        [("data", 1), ("user_id", 1), ("location_id", 1), ("inicio", 1)]]
    assert [("data", 1)] in [i["key"] for i in indices.values()]
