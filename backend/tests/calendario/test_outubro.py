"""Outubro (desenho, «Testes» 2): as férias abrem buracos e as idas tapam-nos.

O Weber está de férias de 21 a 25/10 e a Carol cobre a Amadora a 22, 23 e 25 (é o que a
mensagem de WhatsApp diz). A ida de um colaborador TIRA à escala dele as horas da ida: a
Joana em Benfica numa quarta abre Oeiras; 2 horas dela abrem só essas 2 horas; numa folga
dela a ida é «extra». (O 409 de a marcar num dia de férias prova-se nas rotas.)
"""
import calendario

from . import dados_semana_normal as sn

JOANA = sn.user("Joana")


def _dias(dados):
    return calendario.calendario_do_mes(2026, 10, dados)


def _loja(dias, data, nome):
    dia = next(d for d in dias if d["data"] == data)
    return next(l for l in dia["lojas"] if l["nome"] == nome)


def _buracos(dias, data, nome):
    return ["%s-%s" % (b["inicio"], b["fim"]) for b in _loja(dias, data, nome)["buracos"]]


def _com_ida(*idas):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    return _dias(dados)


def test_as_ferias_do_weber_abrem_a_amadora_de_21_a_25():
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    dias = _dias(dados)
    assert {d: _buracos(dias, d, "Amadora") for d in
            ("2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26")} == {
        "2026-10-20": [], "2026-10-21": ["14:00-23:00"], "2026-10-22": ["14:00-23:00"],
        "2026-10-23": ["14:00-23:00"], "2026-10-24": ["14:00-23:00"], "2026-10-25": ["14:00-23:00"],
        "2026-10-26": []}


def test_a_carol_tapa_a_amadora_a_22_23_e_25():
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    dados["idas"] = [sn.ida(d, sn.AMADORA, sn.CAROL, "14:00", "23:00") for d in ("2026-10-22", "2026-10-23", "2026-10-25")]
    dias = _dias(dados)
    assert [_buracos(dias, d, "Amadora") for d in ("2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25")] == [
        ["14:00-23:00"], [], [], ["14:00-23:00"], []]
    assert _loja(dias, "2026-10-22", "Amadora")["pessoas"] == [{
        "user_id": sn.CAROL, "nome": "Carol Santos", "inicio": "14:00", "fim": "23:00",
        "origem": "ida", "extra": False, "ida_id": dados["idas"][0]["id"]}]


def test_a_joana_em_benfica_numa_quarta_abre_oeiras():
    dias = _com_ida(sn.ida("2026-10-28", sn.BENFICA, JOANA, "13:00", "22:00"))
    assert _buracos(dias, "2026-10-28", "Oeiras") == ["13:00-22:00"]
    assert _buracos(dias, "2026-10-28", "Benfica") == []
    [joana] = _loja(dias, "2026-10-28", "Benfica")["pessoas"]
    assert (joana["nome"], joana["origem"], joana["extra"]) == ("Joana", "ida", False)


def test_duas_horas_dela_em_benfica_abrem_so_essas_duas_horas():
    dias = _com_ida(sn.ida("2026-10-28", sn.BENFICA, JOANA, "13:00", "15:00"))
    assert _buracos(dias, "2026-10-28", "Oeiras") == ["13:00-15:00"]
    assert [(p["nome"], p["inicio"], p["fim"], p["origem"]) for p in _loja(dias, "2026-10-28", "Oeiras")["pessoas"]] == [
        ("Joana", "15:00", "22:00", "escala")]
    assert _buracos(dias, "2026-10-28", "Benfica") == ["15:00-22:00"]


def test_numa_folga_dela_a_ida_e_extra():
    dias = _com_ida(sn.ida("2026-10-31", sn.BENFICA, JOANA, "13:00", "22:00"))   # sábado
    [joana] = _loja(dias, "2026-10-31", "Benfica")["pessoas"]
    assert (joana["origem"], joana["extra"]) == ("ida", True)


def test_chegar_antes_de_abrir_nao_faz_a_ida_extra():
    # Quarta: a escala dela é Oeiras 13h–22h. A ida a Benfica das 12h30 mostra-se 13h–22h
    # (recortada ao horário) e cabe toda na escala dela — não é «extra».
    dias = _com_ida(sn.ida("2026-10-28", sn.BENFICA, JOANA, "12:30", "22:00"))
    [joana] = _loja(dias, "2026-10-28", "Benfica")["pessoas"]
    assert (joana["inicio"], joana["fim"], joana["extra"]) == ("13:00", "22:00", False)


def test_a_ida_de_quem_ficou_de_ferias_depois_nao_tapa_o_buraco():
    # A ida foi marcada e as férias aprovadas depois (marcá-la já de férias dava 409). Ela não
    # está lá: Benfica e Oeiras ficam sem ninguém — nunca «coberta» numa loja vazia.
    dados = sn.semana_normal()
    dados["idas"] = [sn.ida("2026-10-28", sn.BENFICA, JOANA, "13:00", "22:00")]
    dados["ausencias"].append(sn.ausencia("Joana", "2026-10-28", "2026-10-28"))
    dias = _dias(dados)
    assert _buracos(dias, "2026-10-28", "Benfica") == ["13:00-22:00"]
    assert _buracos(dias, "2026-10-28", "Oeiras") == ["13:00-22:00"]


def test_a_ida_de_uma_gestora_soma_se_e_recorta_se_ao_horario():
    dias = _com_ida(sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "12:30", "22:00"))
    assert _buracos(dias, "2026-10-27", "Oeiras") == []
    [debora] = _loja(dias, "2026-10-27", "Oeiras")["pessoas"]
    assert (debora["nome"], debora["inicio"], debora["fim"], debora["extra"]) == ("Débora Ferreira", "13:00", "22:00", False)


def test_uma_ida_numa_loja_sem_horario_ou_fechada_nao_entra_nos_dias():
    dias = _com_ida(sn.ida("2026-10-27", sn.PIZZARIA, sn.DEBORA, "13:00", "22:00"),
                    sn.ida("2026-10-27", sn.BELEM, sn.CAROL, "11:30", "19:00"))
    dia = next(d for d in dias if d["data"] == "2026-10-27")
    assert [p["nome"] for l in dia["lojas"] for p in l["pessoas"] if p["origem"] == "ida"] == []


def test_uma_conta_apagada_aparece_com_recurso():
    dias = _com_ida(sn.ida("2026-10-27", sn.OEIRAS, "u-apagada", "13:00", "22:00"))
    assert _loja(dias, "2026-10-27", "Oeiras")["pessoas"][0]["nome"] == calendario.NOME_SEM_CONTA


def test_o_feriado_aparece_e_as_lojas_continuam_abertas():
    dia = next(d for d in _dias(sn.semana_normal()) if d["data"] == "2026-10-05")
    assert dia["feriados"] == ["Implantação da República"]
    assert {l["nome"]: l["estado"] for l in dia["lojas"]}["Alfragide"] == "aberta"
