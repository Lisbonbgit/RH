"""Marcar, mudar e apagar idas contra um mongod REAL (desenho, secção 3, e Testes 7 e 8):
as regras, o «tudo ou nada» e a porta. O índice único e a compensação só se medem aqui."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import calendario  # noqa: E402
import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402
from .apoio import corre  # noqa: E402

DEBORA = {"user_id": sn.DEBORA, "role": "admin"}
GERENTE = {"user_id": sn.GERENTE, "role": "gerente"}
CONTABILISTA = {"user_id": sn.CONTABILISTA, "role": "contabilista"}
COLABORADORA = {"user_id": sn.user("Joana"), "role": "colaborador"}


@pytest.fixture
def semana(base):
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    corre(sn.gravar(base, dados))
    corre(server._bolso_criar_indices())
    return base


def _criar(quem=DEBORA, **corpo):
    return corre(server.bolso_criar_idas(server.BolsoIdasIn(**corpo), current_user=quem))


def _recusa(coro):
    with pytest.raises(HTTPException) as erro:
        corre(coro)
    return erro.value.status_code, erro.value.detail


def _idas(db):
    return corre(db.bolso_idas.find({}, {"_id": 0}).sort([("data", 1), ("user_id", 1)]).to_list(100))


def test_varias_datas_e_duas_pessoas_criam_uma_ida_por_data_e_por_pessoa(semana):
    r = _criar(datas=["2026-10-13", "2026-10-06", "2026-10-20"], location_id=sn.OEIRAS,
               user_ids=[sn.DEBORA, sn.CAROL], inicio="13:00", fim="22:00")
    assert r["criadas"] == 6
    idas = _idas(semana)
    assert [(i["data"], i["user_id"]) for i in idas] == [
        (d, u) for d in ("2026-10-06", "2026-10-13", "2026-10-20") for u in (sn.CAROL, sn.DEBORA)]
    assert {(i["location_id"], i["inicio"], i["fim"], i["criado_por"]) for i in idas} == {
        (sn.OEIRAS, "13:00", "22:00", sn.DEBORA)}
    assert sorted(r["ids"]) == sorted(i["id"] for i in idas)


def test_o_gerente_tambem_marca_e_pode_escalar_um_colaborador(semana):
    assert _criar(GERENTE, datas=["2026-10-31"], location_id=sn.BENFICA, user_ids=[sn.user("Joana")],
                  inicio="13:00", fim="22:00")["criadas"] == 1


def test_um_choque_so_na_ultima_data_nao_grava_nenhuma(semana):
    _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA], inicio="10:00", fim="14:00")
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(
        datas=["2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27"], location_id=sn.OEIRAS,
        user_ids=[sn.DEBORA], inicio="13:00", fim="22:00"), current_user=DEBORA))
    assert estado == 409
    assert texto.splitlines() == ["Débora já está em Alfragide das 10h às 14h a 27/10.",
                                  "Mude as horas ou apague primeiro a outra ida."]
    assert len(_idas(semana)) == 1


def test_horas_encostadas_nao_chocam(semana):
    _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA], inicio="10:00", fim="14:00")
    assert _criar(datas=["2026-10-27"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA],
                  inicio="14:00", fim="22:00")["criadas"] == 1


def test_um_colaborador_de_ferias_nao_se_marca(semana):
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(
        datas=["2026-10-20", "2026-10-22"], location_id=sn.AMADORA, user_ids=[sn.user("Weber")],
        inicio="14:00", fim="23:00"), current_user=DEBORA))
    assert estado == 409
    assert texto.splitlines()[0] == "Weber está de férias a 22/10."
    assert _idas(semana) == []


@pytest.mark.parametrize("corpo, pedaco", [
    ({"user_ids": [sn.CONTABILISTA]}, "podem ser escalados"),
    ({"user_ids": ["nao-existe"]}, "podem ser escalados"),
    ({"location_id": "loja-que-nao-existe"}, "Essa loja não existe."),
    ({"location_id": sn.PIZZARIA}, "não tem horário"),
    ({"location_id": sn.BELEM}, "Belém está fechada a 27/10."),
    ({"datas": ["2026-10-21"], "location_id": sn.BENFICA}, "Benfica só abre a 24/10."),
    ({"inicio": "08:00", "fim": "12:00"}, "têm de tocar nesse horário"),
    ({"inicio": "9:00"}, "HH:MM"),
    ({"inicio": "22:00", "fim": "13:00"}, "depois da hora de início"),
    ({"datas": ["2026-10-27", "2026-10-27"]}, "dias repetidos"),
    ({"user_ids": [sn.DEBORA, sn.DEBORA]}, "pessoas repetidas"),
    ({"user_ids": [sn.DEBORA, sn.CAROL, sn.GERENTE]}, "uma ou duas pessoas"),
    ({"datas": []}, "entre 1 e 31 dias"),
])
def test_pedidos_errados_dao_400_e_nao_gravam(semana, corpo, pedaco):
    pedido = dict(datas=["2026-10-27"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA], inicio="13:00", fim="22:00")
    pedido.update(corpo)
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(**pedido), current_user=DEBORA))
    assert estado == 400
    assert pedaco in texto
    assert _idas(semana) == []


def test_o_tudo_ou_nada_compensa_quando_o_indice_unico_dispara(semana, monkeypatch):
    """A janela entre verificar e gravar: outra gestora grava a MESMA ida no mesmo segundo.
    Simula-se desligando a verificação; quem apanha é o índice único, e o pedido tem de
    apagar o que já tinha gravado."""
    corre(semana.bolso_idas.insert_one(
        dict(sn.ida("2026-10-20", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"), id="da-outra-gestora")))
    monkeypatch.setattr(calendario, "choques", lambda *a, **k: [])
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(
        datas=["2026-10-06", "2026-10-13", "2026-10-20"], location_id=sn.OEIRAS,
        user_ids=[sn.DEBORA], inicio="13:00", fim="22:00"), current_user=DEBORA))
    assert estado == 409
    assert "Nada foi gravado" in texto
    assert [i["id"] for i in _idas(semana)] == ["da-outra-gestora"]


def test_mudar_uma_ida_que_choca_da_409_mas_nao_choca_consigo(semana):
    _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA], inicio="10:00", fim="14:00")
    [oeiras] = _criar(datas=["2026-10-27"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA],
                      inicio="14:00", fim="22:00")["ids"]
    estado, texto = _recusa(server.bolso_mudar_ida(oeiras, server.BolsoIdaIn(
        data="2026-10-27", location_id=sn.OEIRAS, user_id=sn.DEBORA, inicio="13:00", fim="22:00"),
        current_user=DEBORA))
    assert (estado, texto.splitlines()[0]) == (409, "Débora já está em Alfragide das 10h às 14h a 27/10.")
    r = corre(server.bolso_mudar_ida(oeiras, server.BolsoIdaIn(
        data="2026-10-27", location_id=sn.OEIRAS, user_id=sn.DEBORA, inicio="15:00", fim="22:00"),
        current_user=GERENTE))
    assert (r["inicio"], r["alterado_por"]) == ("15:00", sn.GERENTE)


def test_mudar_e_apagar_mexem_so_na_ida_certa(semana):
    ids = _criar(datas=["2026-10-06", "2026-10-13"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA],
                 inicio="13:00", fim="22:00")["ids"]
    corre(server.bolso_mudar_ida(ids[0], server.BolsoIdaIn(
        data="2026-10-07", location_id=sn.ALFRAGIDE, user_id=sn.CAROL, inicio="19:00", fim="23:00"),
        current_user=DEBORA))
    corre(server.bolso_apagar_ida(ids[1], current_user=DEBORA))
    assert [(i["id"], i["data"], i["location_id"], i["user_id"], i["inicio"]) for i in _idas(semana)] == [
        (ids[0], "2026-10-07", sn.ALFRAGIDE, sn.CAROL, "19:00")]


def test_mudar_ou_apagar_uma_ida_que_ja_nao_existe_da_404(semana):
    corpo = server.BolsoIdaIn(data="2026-10-27", location_id=sn.OEIRAS, user_id=sn.DEBORA, inicio="13:00", fim="22:00")
    assert _recusa(server.bolso_mudar_ida("nao-existe", corpo, current_user=DEBORA))[0] == 404
    assert _recusa(server.bolso_apagar_ida("nao-existe", current_user=DEBORA))[0] == 404


# --- A porta (Testes 8) --------------------------------------------------------------------


def _rota(caminho, metodo):
    achadas = [r for r in server.app.routes
               if getattr(r, "path", None) == caminho and metodo in getattr(r, "methods", ())]
    assert len(achadas) == 1, "%s %s: %d rotas" % (metodo, caminho, len(achadas))
    return achadas[0]


def _dependencias(rota):
    encontradas = []

    def _procura(dependente):
        for d in dependente.dependencies:
            encontradas.append(d.call)
            _procura(d)

    _procura(rota.dependant)
    return encontradas


@pytest.mark.parametrize("metodo, caminho", [
    ("GET", "/api/bolso/calendario"), ("GET", "/api/bolso/calendario/contagem")])
def test_ler_e_para_gestores_e_contabilista(metodo, caminho):
    deps = _dependencias(_rota(caminho, metodo))
    assert server.admin_manager_required in deps
    assert server.bolso_quem_marca not in deps


@pytest.mark.parametrize("metodo, caminho", [
    ("POST", "/api/bolso/calendario/idas"), ("PUT", "/api/bolso/calendario/idas/{ida_id}"),
    ("DELETE", "/api/bolso/calendario/idas/{ida_id}")])
def test_escrever_e_so_para_admin_e_gerente(metodo, caminho):
    deps = _dependencias(_rota(caminho, metodo))
    assert server.bolso_quem_marca in deps
    assert server.admin_manager_required in deps


def test_o_contabilista_leva_403_a_escrever_e_o_colaborador_a_tudo(semana):
    assert _recusa(server.bolso_quem_marca(current_user=dict(CONTABILISTA)))[0] == 403
    assert _recusa(server.admin_manager_required(current_user=dict(COLABORADORA)))[0] == 403
    assert corre(server.bolso_quem_marca(current_user=dict(DEBORA)))["role"] == "admin"
    assert corre(server.bolso_quem_marca(current_user=dict(GERENTE)))["role"] == "gerente"
