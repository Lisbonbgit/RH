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


# ---- Tarefa 11: as escalas ----

def _escala(db, nome):
    return db.work_schedule_templates.find_one({"name": nome}, {"_id": 0})


def _atribuicoes(db, employee_id):
    return list(db.work_schedule_assignments.find({"employee_id": employee_id}, {"_id": 0}).sort("start_date", 1))


def test_a_joana_fica_com_uma_loja_por_dia_e_a_escala_antiga_fecha_na_vespera(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    joana = _escala(prod, "Escala Joana")
    assert joana["dias"] == [
        {"dia": 0, "location_id": "l-ama", "inicio": None, "fim": None},
        {"dia": 1, "location_id": "l-ama", "inicio": None, "fim": None},
        {"dia": 2, "location_id": "l-oei", "inicio": None, "fim": None},
        {"dia": 3, "location_id": "l-alg", "inicio": None, "fim": None},
        {"dia": 4, "location_id": "l-alg", "inicio": None, "fim": None},
    ]
    assert joana["work_days"] == [0, 1, 2, 3, 4]
    assert joana["start_time"] == "13:00"          # vem da 5x2: o lembrete do ponto não muda
    antiga, nova = _atribuicoes(prod, "e-joa")
    assert (antiga["id"], antiga["start_date"], antiga["end_date"]) == ("a-joa", "2026-01-01", "2026-09-30")
    assert (nova["template_id"], nova["start_date"], nova["end_date"]) == (joana["id"], "2026-10-01", None)
    assert nova["work_days"] == [0, 1, 2, 3, 4]


def test_as_outras_seis_escalas_batem_com_a_semana_normal(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    esperado = {
        "Emily": ("e-emi", [0, 1, 4, 5, 6], "l-alf", "14:00", "23:00"),
        "Beatrice": ("e-bea", [2, 3, 4, 5, 6], "l-alf", "10:00", "19:00"),
        "Walisson": ("e-wal", [0, 1, 2, 5, 6], "l-alg", None, None),
        "Weber": ("e-web", [2, 3, 4, 5, 6], "l-ama", None, None),
        "Emanuela": ("e-ema", [0, 3, 4, 5, 6], "l-oei", None, None),
        "Rafaela": ("e-raf", [0, 2, 3, 4, 5, 6], "l-bel", None, None),   # Belém fecha à terça
    }
    for nome, (pessoa, dias, loja, inicio, fim) in esperado.items():
        escala = _escala(prod, "Escala " + nome)
        assert escala["work_days"] == dias, nome
        assert escala["dias"] == [{"dia": d, "location_id": loja, "inicio": inicio, "fim": fim} for d in dias], nome
        assert escala["start_time"] is None, nome
        [atribuicao] = _atribuicoes(prod, pessoa)
        assert (atribuicao["template_id"], atribuicao["start_date"], atribuicao["end_date"]) == \
            (escala["id"], "2026-10-01", None), nome
        assert atribuicao["work_days"] == dias, nome
    assert _atribuicoes(prod, "e-car") == []           # a Carolina não está na tabela


def test_desde_muda_o_dia_de_inicio_e_a_vespera(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    monkeypatch.setenv("DESDE", "2026-11-01")
    assert arranque.main() == 0
    antiga, nova = _atribuicoes(prod, "e-joa")
    assert antiga["end_date"] == "2026-10-31" and nova["start_date"] == "2026-11-01"


def test_o_ensaio_diz_o_que_cria_o_que_fecha_e_de_onde_vem_a_hora_de_inicio(prod, capsys):
    assert arranque.main() == 0
    saida = capsys.readouterr().out
    assert "criar «Escala Joana» (hora de início: 13:00, da escala «5x2»)" in saida
    assert "fechar «5x2» (2026-01-01 → em aberto; dias Seg, Ter, Qua, Qui, Sex) a 2026-09-30" in saida
    assert "nova atribuição desde 2026-10-01 (dias Seg, Qua, Qui, Sex, Sáb, Dom)" in saida      # a Rafaela
    assert "Emily Santos: Seg L'Açaí Alfragide 14:00–23:00" in saida


def test_a_ficha_noutra_loja_da_um_aviso_e_nao_para(prod, capsys):
    prod.employees.update_one({"id": "e-web"}, {"$set": {"location_id": "l-oei"}})
    assert arranque.main() == 0
    assert "aviso: a ficha diz «L'Açaí Oeiras»" in capsys.readouterr().out


@pytest.mark.parametrize("estrago, motivo", [
    (lambda db: db.employees.insert_one({"id": "e-joa2", "name": "Joana Martins", "location_id": None}),
     "A pessoa «Joana» casa com 2"),
    (lambda db: db.employees.delete_one({"id": "e-web"}),
     "A pessoa «Weber» casa com 0: nenhum"),
    (lambda db: db.work_schedule_assignments.insert_one({
        "id": "a-web", "employee_id": "e-web", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
        "start_date": "2026-11-01", "end_date": None}),
     "depois de 2026-10-01"),
    # A antiga ainda cobre DESDE e a seguinte já está marcada: sem parar, o script abria
    # uma nova a DESDE, sem fim, por cima da de 2026-11-01 (o servidor recusa sobreposições).
    (lambda db: (
        db.work_schedule_assignments.update_one({"id": "a-joa"}, {"$set": {"end_date": "2026-10-31"}}),
        db.work_schedule_assignments.insert_one({
            "id": "a-joa2", "employee_id": "e-joa", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
            "start_date": "2026-11-01", "end_date": None})),
     "Joana Pereira já tem uma escala a começar a 2026-11-01"),
    (lambda db: db.work_schedule_assignments.insert_one({
        "id": "a-web", "employee_id": "e-web", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
        "start_date": "2026-10-01", "end_date": None}),
     "não se pode fechar na véspera"),
    (lambda db: db.work_schedule_templates.insert_many([
        {"id": "t-x1", "name": "Escala Weber"}, {"id": "t-x2", "name": "Escala Weber"}]),
     "Há 2 escalas chamadas «Escala Weber»"),
])
def test_o_que_pede_uma_decisao_para_tudo_antes_de_escrever(prod, monkeypatch, capsys, estrago, motivo):
    estrago(prod)
    antes = _tudo(prod)
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 1
    saida = capsys.readouterr().out
    assert "PARADO, nada foi escrito" in saida and motivo in saida
    assert _tudo(prod) == antes


def test_procurar_desfaz_a_ambiguidade_de_uma_pessoa(prod, monkeypatch):
    prod.employees.insert_one({"id": "e-joa2", "name": "Joana Martins", "location_id": None})
    monkeypatch.setitem(arranque.PROCURAR, "Joana", "Joana Pereira")
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    assert _atribuicoes(prod, "e-joa2") == []
    assert [a["start_date"] for a in _atribuicoes(prod, "e-joa")] == ["2026-01-01", "2026-10-01"]


def test_as_escalas_do_script_passam_na_validacao_do_servidor(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    escritas = list(prod.work_schedule_templates.find({"name": {"$regex": "^Escala "}}, {"_id": 0}))
    assert len(escritas) == 7
    for doc in escritas:
        corpo = server.WorkScheduleTemplateCreate.model_validate(
            {"name": doc["name"], "workDays": doc["work_days"], "dias": doc["dias"]})
        assert server._dias_de_trabalho(corpo) == doc["work_days"]
        assert server._dias_para_gravar(corpo) == doc["dias"]
