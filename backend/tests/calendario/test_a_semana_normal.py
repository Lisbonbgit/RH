"""A semana normal — o teste que dá nome ao trabalho (desenho, «Testes» 1) — e a escala.

Com os dados da tabela do dono, numa semana DEPOIS da abertura de Benfica (26/10–01/11), o
cálculo dá EXACTAMENTE a grelha dos buracos: Oeiras sem ninguém à terça; Alfragide 10–14 à
segunda e terça e 19–23 à quarta e quinta; Benfica todos os dias; Belém fechada à terça; o
resto coberto. Os outros testes prendem as regras da escala (desenho, secção 2, passo 2).
"""
import calendario

from . import dados_semana_normal as sn


def _mes(dados, ano=2026, mes=10):
    return calendario.calendario_do_mes(ano, mes, dados)


def _grelha(dias, de, ate):
    """{data: {loja: estado ou ["HH:MM-HH:MM", …]}} entre `de` e `ate`."""
    return {
        d["data"]: {l["nome"]: (l["estado"] if l["estado"] != "aberta"
                                else ["%s-%s" % (b["inicio"], b["fim"]) for b in l["buracos"]])
                    for l in d["lojas"]}
        for d in dias if de <= d["data"] <= ate
    }


def _loja(dias, data, nome):
    dia = next(d for d in dias if d["data"] == data)
    return next(l for l in dia["lojas"] if l["nome"] == nome)


def _quem(dias, data, nome):
    return [(p["nome"], p["inicio"], p["fim"], p["origem"]) for p in _loja(dias, data, nome)["pessoas"]]


def _semana(mudancas=None):
    linha = {"Alfragide": [], "Algueirão": [], "Amadora": [], "Belém": [], "Benfica": ["13:00-22:00"], "Oeiras": []}
    linha.update(mudancas or {})
    return linha


def test_a_semana_normal_da_exactamente_a_grelha_dos_buracos():
    dados = sn.semana_normal()
    dias = _mes(dados, 2026, 10) + _mes(dados, 2026, 11)
    assert _grelha(dias, "2026-10-26", "2026-11-01") == {
        "2026-10-26": _semana({"Alfragide": ["10:00-14:00"]}),
        "2026-10-27": _semana({"Alfragide": ["10:00-14:00"], "Belém": "fechada", "Oeiras": ["13:00-22:00"]}),
        "2026-10-28": _semana({"Alfragide": ["19:00-23:00"]}),
        "2026-10-29": _semana({"Alfragide": ["19:00-23:00"]}),
        "2026-10-30": _semana(),
        "2026-10-31": _semana(),
        "2026-11-01": _semana(),
    }


def test_os_horarios_destes_testes_sao_os_que_o_arranque_da_fase_1_carrega():
    import arranque_calendario
    assert {l["name"]: l["horario"] for l in sn.LOJAS if l["horario"]} == arranque_calendario.HORARIOS


def test_antes_de_abrir_benfica_nao_aparece_e_a_pizzaria_nunca():
    dia = _grelha(_mes(sn.semana_normal()), "2026-10-23", "2026-10-23")["2026-10-23"]
    assert sorted(dia) == ["Alfragide", "Algueirão", "Amadora", "Belém", "Oeiras"]


def test_quem_esta_em_cada_loja_e_com_que_horas():
    dias = _mes(sn.semana_normal())
    assert _quem(dias, "2026-10-26", "Alfragide") == [("Emily", "14:00", "23:00", "escala")]      # horas da escala
    assert _quem(dias, "2026-10-26", "Amadora") == [("Joana", "14:00", "23:00", "escala")]       # loja do dia
    assert _quem(dias, "2026-10-26", "Algueirão") == [("Walisson", "13:00", "22:00", "escala")]  # escala antiga
    assert _quem(dias, "2026-10-26", "Oeiras") == [("Emanuela", "13:00", "22:00", "escala")]     # `dias` sem loja/horas
    assert _quem(dias, "2026-10-28", "Alfragide") == [("Beatrice", "10:00", "19:00", "escala")]
    assert _loja(dias, "2026-10-26", "Alfragide")["pessoas"][0]["user_id"] == sn.user("Emily")


def test_duas_atribuicoes_no_mes():
    dados = sn.semana_normal()
    weber = next(a for a in dados["atribuicoes"] if a["employee_id"] == sn.emp("Weber"))
    weber["end_date"] = "2026-10-15"
    dados["modelos"].append({"id": "m-weber-2", "name": "Escala Weber (nova)", "work_days": [0, 1, 2, 3, 4]})
    dados["atribuicoes"].append({"id": "a-weber-2", "employee_id": sn.emp("Weber"), "template_id": "m-weber-2",
                                 "work_days": [0, 1, 2, 3, 4], "start_date": "2026-10-16", "end_date": None})
    grelha = _grelha(_mes(dados), "2026-10-10", "2026-10-19")
    assert grelha["2026-10-10"]["Amadora"] == []                 # sábado, ainda a primeira
    assert grelha["2026-10-17"]["Amadora"] == ["14:00-23:00"]    # sábado, já a segunda (folga)
    assert grelha["2026-10-19"]["Amadora"] == []                 # segunda: Weber e Joana


def test_uma_atribuicao_orfa_nao_aparece():
    dados = sn.semana_normal()
    dados["modelos"].append({"id": "m-fantasma", "work_days": [0, 1, 2, 3, 4, 5, 6],
                             "dias": [{"dia": d, "location_id": sn.BENFICA, "inicio": None, "fim": None}
                                      for d in range(7)]})
    dados["atribuicoes"].append({"id": "a-fantasma", "employee_id": "e-apagada", "template_id": "m-fantasma",
                                 "work_days": [0, 1, 2, 3, 4, 5, 6], "start_date": "2026-01-01", "end_date": None})
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Benfica"] == ["13:00-22:00"]


def test_so_a_ausencia_aprovada_tira_alguem():
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Emanuela", "2026-10-26", "2026-10-30", status="pendente"))
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Oeiras"] == []
    dados["ausencias"].append(sn.ausencia("Emanuela", "2026-10-26", "2026-10-26", tipo="doenca"))
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Oeiras"] == ["13:00-22:00"]


def test_uma_entrada_numa_loja_fechada_ignora_se():
    dados = sn.semana_normal()
    joana = next(m for m in dados["modelos"] if m["id"] == "m-joana")
    next(d for d in joana["dias"] if d["dia"] == 1)["location_id"] = sn.BELEM   # terça em Belém, que fecha à terça
    dias = _mes(dados)
    assert _grelha(dias, "2026-10-27", "2026-10-27")["2026-10-27"]["Amadora"] == ["14:00-23:00"]
    assert _loja(dias, "2026-10-27", "Belém") == {
        "location_id": sn.BELEM, "nome": "Belém", "estado": "fechada", "abre": None, "fecha": None,
        "feriados": [], "pessoas": [], "buracos": []}


def test_as_horas_da_escala_recortam_se_ao_horario_da_loja():
    dados = sn.semana_normal()
    for d in next(m for m in dados["modelos"] if m["id"] == "m-emily")["dias"]:
        d["inicio"], d["fim"] = "09:00", "23:30"
    dias = _mes(dados)
    assert _quem(dias, "2026-10-26", "Alfragide") == [("Emily", "10:00", "23:00", "escala")]
    assert _loja(dias, "2026-10-26", "Alfragide")["buracos"] == []


def test_sem_copia_dos_dias_na_atribuicao_vale_a_do_modelo():
    dados = sn.semana_normal()
    next(a for a in dados["atribuicoes"] if a["employee_id"] == sn.emp("Rafaela"))["work_days"] = []
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Belém"] == []
