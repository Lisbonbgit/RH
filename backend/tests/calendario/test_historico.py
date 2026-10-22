"""O histórico do calendário contra um mongod REAL (desenho `2026-10-20-calendario-trocas-historico-design.md`,
§2 e §5 5): cada uma das seis rotas de escrita deixa UMA entrada com o antes e o depois certos (nomes
já escritos); um PUT sem diferenças não deixa; uma falha do histórico não desfaz a mudança; o GET do
mês só devolve o mês pedido, do mais recente para o mais antigo, no máximo 300."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import logging  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorCollection  # noqa: E402

import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402
from .apoio import corre  # noqa: E402
from .test_rotas_das_trocas import BEATRICE, EMILY, JOANA, TERCA, semana  # noqa: E402,F401
from .test_rotas_de_escrita import _dependencias, _rota  # noqa: E402

# O nome é o que o `admin_manager_required` põe em `current_user` antes de qualquer rota.
DEBORA = {"user_id": sn.DEBORA, "role": "admin", "name": "Débora Ferreira"}


def _entradas(db):
    return corre(db.bolso_historico.find({}, {"_id": 0}).sort("quando", 1).to_list(1000))


def _criar(**corpo):
    return corre(server.bolso_criar_idas(server.BolsoIdasIn(**corpo), current_user=DEBORA))


def _mudar(ida_id, **corpo):
    return corre(server.bolso_mudar_ida(ida_id, server.BolsoIdaIn(**corpo), current_user=DEBORA))


def _retrato(data, loja, nome, inicio, fim, no_lugar_de=None):
    return {"data": data, "loja": loja, "nome": nome, "inicio": inicio, "fim": fim, "no_lugar_de": no_lugar_de}


def _sem_id_nem_quando(entrada):
    assert entrada["id"] and entrada["quando"].endswith("+00:00")
    return {k: v for k, v in entrada.items() if k not in ("id", "quando")}


def _quem(acao, datas, antes, depois):
    return {"quem_id": sn.DEBORA, "quem_nome": "Débora Ferreira", "acao": acao, "datas": datas,
            "antes": antes, "depois": depois}


# --- As seis rotas -----------------------------------------------------------------------------


def test_marcar_deixa_uma_entrada_com_as_idas_novas(semana):
    _criar(datas=["2026-10-13", "2026-10-06"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA, sn.CAROL],
           inicio="13:00", fim="22:00")
    [entrada] = _entradas(semana)
    assert _sem_id_nem_quando(entrada) == _quem("marcou", ["2026-10-06", "2026-10-13"], [], [
        _retrato(d, "Oeiras", n, "13:00", "22:00")
        for d in ("2026-10-06", "2026-10-13") for n in ("Débora Ferreira", "Carol Santos")])


def test_mudar_deixa_o_antes_e_o_depois(semana):
    [ida_id] = _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA],
                      inicio="10:00", fim="14:00")["ids"]
    _mudar(ida_id, data="2026-10-28", location_id=sn.OEIRAS, user_id=sn.CAROL, inicio="13:00", fim="22:00")
    [_, entrada] = _entradas(semana)
    assert _sem_id_nem_quando(entrada) == _quem(
        "alterou", ["2026-10-27", "2026-10-28"],
        [_retrato("2026-10-27", "Alfragide", "Débora Ferreira", "10:00", "14:00")],
        [_retrato("2026-10-28", "Oeiras", "Carol Santos", "13:00", "22:00")])


def test_mudar_sem_diferencas_nao_deixa_entrada(semana):
    [ida_id] = _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA],
                      inicio="10:00", fim="14:00")["ids"]
    _mudar(ida_id, data="2026-10-27", location_id=sn.ALFRAGIDE, user_id=sn.DEBORA, inicio="10:00", fim="14:00")
    assert [e["acao"] for e in _entradas(semana)] == ["marcou"]


def test_mudar_uma_ida_apagada_entretanto_da_404_e_nao_deixa_entrada(semana, monkeypatch):
    """Outra gestora apaga a ida entre a leitura e o `update_one` do PUT: o update não casa com
    nada, e um «alterou» de uma ida que já não existe seria mentira."""
    [ida_id] = _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA],
                      inicio="10:00", fim="14:00")["ids"]
    validar = server._bolso_validar_idas

    async def _valida_e_outra_apaga(*args, **kwargs):
        await validar(*args, **kwargs)
        await semana.bolso_idas.delete_one({"id": ida_id})

    monkeypatch.setattr(server, "_bolso_validar_idas", _valida_e_outra_apaga)
    with pytest.raises(HTTPException) as erro:
        _mudar(ida_id, data="2026-10-27", location_id=sn.ALFRAGIDE, user_id=sn.DEBORA, inicio="11:00", fim="14:00")
    assert (erro.value.status_code, erro.value.detail) == (404, "Esta ida já não existe — volte a abrir o dia.")
    assert [e["acao"] for e in _entradas(semana)] == ["marcou"]


def test_apagar_deixa_a_ida_que_havia(semana):
    [ida_id] = _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA],
                      inicio="10:00", fim="14:00")["ids"]
    corre(server.bolso_apagar_ida(ida_id, current_user=DEBORA))
    [_, entrada] = _entradas(semana)
    assert _sem_id_nem_quando(entrada) == _quem(
        "apagou", ["2026-10-27"], [_retrato("2026-10-27", "Alfragide", "Débora Ferreira", "10:00", "14:00")], [])


def test_trocar_deixa_quem_entra_no_lugar_de_quem_sai(semana):
    corre(server.bolso_trocar(server.BolsoTrocaIn(
        data=TERCA, sai=EMILY, entra=BEATRICE, inicio="14:00", fim="18:00"), current_user=DEBORA))
    [entrada] = _entradas(semana)
    assert _sem_id_nem_quando(entrada) == _quem(
        "trocou", [TERCA], [], [_retrato(TERCA, "Alfragide", "Beatrice", "14:00", "18:00", "Emily")])


def test_trocar_entre_si_deixa_as_duas_idas(semana):
    corre(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(data=TERCA, uma=EMILY, outra=JOANA),
                                       current_user=DEBORA))
    [entrada] = _entradas(semana)
    entrada["depois"].sort(key=lambda r: r["nome"])
    assert _sem_id_nem_quando(entrada) == _quem("trocou entre si", [TERCA], [], [
        _retrato(TERCA, "Amadora", "Emily", "14:00", "23:00", "Joana"),
        _retrato(TERCA, "Alfragide", "Joana", "14:00", "23:00", "Emily")])


def test_desfazer_a_troca_deixa_as_idas_que_havia(semana):
    troca_id = corre(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data=TERCA, uma=EMILY, outra=JOANA), current_user=DEBORA))["troca_id"]
    corre(server.bolso_desfazer_troca(troca_id, current_user=DEBORA))
    [_, entrada] = _entradas(semana)
    entrada["antes"].sort(key=lambda r: r["nome"])
    assert _sem_id_nem_quando(entrada) == _quem("desfez a troca", [TERCA], [
        _retrato(TERCA, "Amadora", "Emily", "14:00", "23:00", "Joana"),
        _retrato(TERCA, "Alfragide", "Joana", "14:00", "23:00", "Emily")], [])


def test_uma_falha_do_historico_nao_desfaz_a_ida(semana, monkeypatch, caplog):
    original = AsyncIOMotorCollection.insert_one

    def _rebenta_no_historico(self, *args, **kwargs):
        if self.name == "bolso_historico":
            raise RuntimeError("o histórico rebentou")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncIOMotorCollection, "insert_one", _rebenta_no_historico)
    with caplog.at_level(logging.ERROR):
        r = _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA],
                   inicio="10:00", fim="14:00")
    assert r["criadas"] == 1
    assert [i["id"] for i in corre(semana.bolso_idas.find({}, {"_id": 0}).to_list(10))] == r["ids"]
    assert _entradas(semana) == []
    assert any(reg.exc_info and "o histórico rebentou" in str(reg.exc_info[1]) for reg in caplog.records)


# --- A leitura do mês ---------------------------------------------------------------------------


def _historico(ano, mes):
    return corre(server.bolso_historico(ano=ano, mes=mes, current_user=DEBORA))["entradas"]


def test_o_mes_apanha_o_dia_de_antes_e_o_de_depois_e_nada_mais(semana):
    # Um PUT de 30/09 para 02/11 é de setembro e de novembro; um `$gte`/`$lte` solto sobre o array
    # apanhava-o também em outubro.
    [ida_id] = _criar(datas=["2026-09-30"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA],
                      inicio="13:00", fim="22:00")["ids"]
    _mudar(ida_id, data="2026-11-02", location_id=sn.OEIRAS, user_id=sn.DEBORA, inicio="13:00", fim="22:00")
    assert [e["acao"] for e in _historico(2026, 9)] == ["alterou", "marcou"]
    assert _historico(2026, 10) == []
    assert [e["acao"] for e in _historico(2026, 11)] == ["alterou"]
    assert all("_id" not in e for e in _historico(2026, 9))


def test_o_mes_vem_do_mais_recente_e_no_maximo_300(semana):
    corre(semana.bolso_historico.insert_many([
        {"id": "h-%03d" % n, "quando": "2026-10-20T10:%02d:%02d+00:00" % (n // 60, n % 60), "acao": "marcou",
         "datas": ["2026-10-27"], "antes": [], "depois": []} for n in range(301)]))
    entradas = _historico(2026, 10)
    assert [e["id"] for e in entradas] == ["h-%03d" % n for n in range(300, 0, -1)]
    assert all("_id" not in e for e in entradas)


def test_os_indices_do_historico(semana):
    chaves = [i["key"] for i in corre(semana.bolso_historico.index_information()).values()]
    assert [("datas", 1)] in chaves
    assert [("quando", -1)] in chaves


def test_ler_o_historico_e_para_quem_ve_o_calendario():
    deps = _dependencias(_rota("/api/bolso/calendario/historico", "GET"))
    assert server.admin_manager_required in deps
    assert server.bolso_quem_marca not in deps
