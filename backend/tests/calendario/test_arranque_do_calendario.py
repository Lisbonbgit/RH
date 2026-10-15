"""O script de arranque do calendário (backend/arranque_calendario.py), contra um mongod
real com a forma da produção: lojas com o nome da marca à frente, uma pizzaria e um
escritório que não entram, e uma escala antiga atribuída à Joana.

O que se prende: o ensaio não escreve nada; GRAVAR=1 escreve o que o ensaio mostrou;
uma ambiguidade pára tudo ANTES da primeira escrita; nunca se apaga; correr outra vez
não reescreve; e o que o script escreve passa na validação do servidor.
"""
import json
from datetime import date

import pytest
from pymongo import MongoClient

import arranque_calendario as arranque
import server

BASE = "teste_arranque"
COLECOES = ("locations", "employees", "work_schedule_templates", "work_schedule_assignments")
LOJAS = {
    "l-alf": "L'Açaí Alfragide", "l-alg": "L'Açaí Algueirão", "l-ama": "L'Açaí Amadora",
    "l-bel": "L'Açaí Belém", "l-ben": "L'Açaí Benfica", "l-oei": "L'Açaí Oeiras",
    "l-piz": "Pizzaria Lenha e Brasa", "l-esc": "Escritório Central",
}
PESSOAS = {
    "e-emi": ("Emily Santos", "l-alf"), "e-bea": ("Beatrice Lima", "l-alf"),
    "e-wal": ("Walisson Costa", "l-alg"), "e-joa": ("Joana Pereira", "l-oei"),
    "e-web": ("Weber Souza", "l-ama"), "e-ema": ("Emanuela Rocha", "l-oei"),
    "e-raf": ("Rafaela Dias", "l-bel"), "e-car": ("Carolina Mendes", None),
}


@pytest.fixture
def prod(mongod_porta, monkeypatch):
    """Uma base com a forma da produção, e o ambiente do contentor a apontar para ela."""
    url = "mongodb://127.0.0.1:%d" % mongod_porta
    cliente = MongoClient(url)
    cliente.drop_database(BASE)
    db = cliente[BASE]
    db.locations.insert_many([{"id": i, "name": n, "company_id": "c1"} for i, n in LOJAS.items()])
    db.employees.insert_many([{"id": i, "name": n, "location_id": loja} for i, (n, loja) in PESSOAS.items()])
    db.work_schedule_templates.insert_one({
        "id": "t-5x2", "name": "5x2", "work_days": [0, 1, 2, 3, 4], "start_time": "13:00",
        "created_at": "2026-01-01T00:00:00+00:00"})
    db.work_schedule_assignments.insert_one({
        "id": "a-joa", "employee_id": "e-joa", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
        "start_date": "2026-01-01", "end_date": None, "created_at": "2026-01-01T00:00:00+00:00"})
    monkeypatch.setenv("MONGO_URL", url)
    monkeypatch.setenv("DB_NAME", BASE)
    for nome in ("GRAVAR", "DESDE", "BENFICA_DESDE", "PROCURAR_JSON"):
        monkeypatch.delenv(nome, raising=False)
    # Os nomes desta base são os do teste: o PROCURAR real (nomes de produção) fica de fora.
    monkeypatch.setattr(arranque, "PROCURAR", {})
    yield db
    cliente.close()


def _tudo(db):
    return {c: sorted(db[c].find({}, {"_id": 0}), key=lambda d: d["id"]) for c in COLECOES}


def test_o_ensaio_mostra_tudo_e_nao_escreve_nada(prod, capsys):
    antes = _tudo(prod)
    assert arranque.main() == 0
    saida = capsys.readouterr().out
    assert "Loja L'Açaí Belém: sem horário → 11:30–19:00 · Dom 11:30–20:00 · fecha Ter" in saida
    assert "Loja L'Açaí Alfragide: sem horário → 10:00–23:00" in saida
    assert "Loja Benfica: SALTADA — falta BENFICA_DESDE" in saida
    assert "ENSAIO:" in saida and "nada foi escrito" in saida
    assert _tudo(prod) == antes


def test_com_gravar_as_cinco_lojas_ficam_com_horario_e_o_resto_como_estava(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    horario = {d["id"]: d.get("horario") for d in prod.locations.find({}, {"_id": 0})}
    assert horario["l-bel"] == arranque.HORARIOS["Belém"]
    assert horario["l-alf"] == {"abre": "10:00", "fecha": "23:00", "excecoes": [], "fechada": []}
    assert horario["l-ama"]["abre"] == "14:00" and horario["l-oei"]["abre"] == "13:00"
    assert horario["l-ben"] is None                      # sem BENFICA_DESDE
    assert horario["l-piz"] is None and horario["l-esc"] is None


def test_benfica_entra_com_o_dia_em_que_abre(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    monkeypatch.setenv("BENFICA_DESDE", "2026-10-24")
    assert arranque.main() == 0
    benfica = prod.locations.find_one({"id": "l-ben"}, {"_id": 0})
    assert benfica["horario"] == arranque.HORARIOS["Benfica"]
    assert benfica["aberta_desde"] == "2026-10-24"


def test_um_nome_que_casa_com_duas_lojas_para_tudo_antes_de_escrever(prod, monkeypatch, capsys):
    prod.locations.insert_one({"id": "l-oei2", "name": "Oeiras Parque (quiosque)", "company_id": "c1"})
    antes = _tudo(prod)
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 1
    assert "PARADO, nada foi escrito: A loja «Oeiras» casa com 2" in capsys.readouterr().out
    assert _tudo(prod) == antes        # nem Alfragide, que vem antes de Oeiras, foi escrita


def test_procurar_desfaz_a_ambiguidade_de_uma_loja(prod, monkeypatch):
    prod.locations.insert_one({"id": "l-oei2", "name": "Oeiras Parque (quiosque)", "company_id": "c1"})
    # Como o dono o faz em produção, sem mudar o ficheiro: -e PROCURAR_JSON='{"Oeiras": "Acai Oeiras"}'
    monkeypatch.setenv("PROCURAR_JSON", json.dumps({"Oeiras": "Acai Oeiras"}))
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    assert prod.locations.find_one({"id": "l-oei"})["horario"]["abre"] == "13:00"
    assert prod.locations.find_one({"id": "l-oei2"}).get("horario") is None


def test_uma_data_invalida_para(prod, monkeypatch, capsys):
    monkeypatch.setenv("BENFICA_DESDE", "2026-02-30")
    assert arranque.main() == 1
    assert "data inválida" in capsys.readouterr().out


def test_correr_outra_vez_nao_reescreve_nada(prod, monkeypatch, capsys):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    depois_da_primeira = _tudo(prod)
    capsys.readouterr()
    assert arranque.main() == 0
    assert "GRAVADO: 0 escritas." in capsys.readouterr().out
    assert _tudo(prod) == depois_da_primeira


def test_o_script_nunca_apaga(prod):
    _, ops = arranque.planear(prod, date(2026, 10, 1), date(2026, 10, 24))
    assert ops
    assert {op[1] for op in ops} <= {"insert_one", "update_one", "update_many"}


def test_os_horarios_do_script_passam_na_validacao_do_servidor():
    for horario in arranque.HORARIOS.values():
        assert server.HorarioLoja.model_validate(horario).model_dump() == horario
