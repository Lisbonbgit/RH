"""No feriado a escala não põe ninguém (decisão do dono, 2026-10-16).

«No feriado não se pode pôr as pessoas automaticamente, porque não se sabe quem vai
trabalhar; no feriado coloca-se à mão.» Num dia que é feriado PARA A LOJA (nacional, do
grupo, da empresa dela ou dela — a regra «OU» de `feriados_da_loja`), a escala não põe lá
ninguém; a loja continua aberta e fica com buraco até um gestor marcar idas. As idas contam
como sempre, e o «extra» de uma ida de colaborador mede-se contra a escala NORMAL dele.
"""
from datetime import date

import calendario

from . import dados_semana_normal as sn

HORARIO_DE_SEGUNDA = {"Alfragide": ["10:00-23:00"], "Algueirão": ["13:00-22:00"], "Amadora": ["14:00-23:00"],
                      "Belém": ["11:30-19:00"], "Oeiras": ["13:00-22:00"]}


def _dia(dados, iso):
    return calendario.dia_do_calendario(date.fromisoformat(iso), dados)


def _buracos(dia):
    return {l["nome"]: (l["estado"] if l["estado"] != "aberta"
                        else ["%s-%s" % (b["inicio"], b["fim"]) for b in l["buracos"]])
            for l in dia["lojas"]}


def _loja(dia, nome):
    return next(l for l in dia["lojas"] if l["nome"] == nome)


def _quem(dia, nome):
    return [(p["nome"], p["inicio"], p["fim"], p["origem"], p["extra"]) for p in _loja(dia, nome)["pessoas"]]


def _feriado(nome, iso, empresa=None, loja=None):
    return {"name": nome, "month": int(iso[5:7]), "day": int(iso[8:10]), "company_id": empresa, "location_id": loja}


def test_a_05_10_a_escala_nao_poe_ninguem_e_as_lojas_ficam_abertas_com_buraco():
    # Segunda: pela escala estariam a Emily, o Walisson, a Joana (Amadora), a Rafaela e a
    # Emanuela. Benfica ainda não abriu (24/10) e a Pizzaria não tem horário: não aparecem.
    dia = _dia(sn.semana_normal(), "2026-10-05")
    assert dia["feriados"] == ["Implantação da República"]
    assert [p for l in dia["lojas"] for p in l["pessoas"]] == []
    assert {l["nome"]: l["estado"] for l in dia["lojas"]} == dict.fromkeys(HORARIO_DE_SEGUNDA, "aberta")
    assert _buracos(dia) == HORARIO_DE_SEGUNDA        # Belém (seg) abre 11h30–19h e fica sem ninguém


def test_no_feriado_as_idas_aparecem_e_tapam_as_horas_delas():
    dados = sn.semana_normal()
    dados["idas"] = [sn.ida("2026-10-05", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                     sn.ida("2026-10-05", sn.ALFRAGIDE, sn.user("Emily"), "14:00", "23:00")]
    dia = _dia(dados, "2026-10-05")
    assert _quem(dia, "Oeiras") == [("Débora Ferreira", "13:00", "22:00", "ida", False)]
    assert _quem(dia, "Alfragide") == [("Emily", "14:00", "23:00", "ida", False)]
    assert _buracos(dia) == dict(HORARIO_DE_SEGUNDA, Oeiras=[], Alfragide=["10:00-14:00"])


def test_o_feriado_de_uma_loja_tira_a_escala_so_nessa_loja():
    dados = sn.semana_normal()
    dados["feriados"] = [_feriado("Feriado de Oeiras", "2026-10-26", loja=sn.OEIRAS)]
    dia = _dia(dados, "2026-10-26")
    assert _loja(dia, "Oeiras")["feriados"] == ["Feriado de Oeiras"]
    assert _quem(dia, "Oeiras") == []
    # As outras como na semana normal (segunda, 26/10).
    assert _buracos(dia) == {"Alfragide": ["10:00-14:00"], "Algueirão": [], "Amadora": [], "Belém": [],
                             "Benfica": ["13:00-22:00"], "Oeiras": ["13:00-22:00"]}


def test_a_ida_num_feriado_de_loja_tira_as_horas_a_escala_da_outra_loja():
    # Quarta, 28/10, feriado só em Benfica. A escala da Joana é Oeiras 13h–22h (sem feriado):
    # a ida dela a Benfica das 13h às 15h deixa Oeiras sem ninguém nessas 2 horas, como hoje,
    # e não é «extra» (cabe na escala dela).
    dados = sn.semana_normal()
    dados["feriados"] = [_feriado("Feriado de Benfica", "2026-10-28", loja=sn.BENFICA)]
    dados["idas"] = [sn.ida("2026-10-28", sn.BENFICA, sn.user("Joana"), "13:00", "15:00")]
    dia = _dia(dados, "2026-10-28")
    assert _quem(dia, "Benfica") == [("Joana", "13:00", "15:00", "ida", False)]
    assert _quem(dia, "Oeiras") == [("Joana", "15:00", "22:00", "escala", False)]
    assert _buracos(dia)["Oeiras"] == ["13:00-15:00"]


def test_o_feriado_de_empresa_tira_a_escala_nas_lojas_dessa_empresa():
    dados = sn.semana_normal()
    next(l for l in dados["lojas"] if l["id"] == sn.OEIRAS)["company_id"] = "emp-outra"
    dados["feriados"] = [_feriado("Dia da Fordaimon", "2026-10-26", empresa=sn.FORDAIMON)]
    dia = _dia(dados, "2026-10-26")
    assert _buracos(dia) == dict(HORARIO_DE_SEGUNDA, Benfica=["13:00-22:00"], Oeiras=[])
    assert _quem(dia, "Oeiras") == [("Emanuela", "13:00", "22:00", "escala", False)]   # outra empresa


def test_o_feriado_do_grupo_tira_a_escala_em_todas_as_lojas():
    dados = sn.semana_normal()
    dados["feriados"] = [_feriado("Dia do grupo", "2026-10-26")]
    dia = _dia(dados, "2026-10-26")
    assert dia["feriados"] == ["Dia do grupo"]
    assert _buracos(dia) == dict(HORARIO_DE_SEGUNDA, Benfica=["13:00-22:00"])


def test_no_feriado_o_extra_mede_se_contra_a_escala_normal():
    # Segunda, 05/10: a Emily trabalha à segunda (Alfragide 14h–23h) — a ida no dia dela não é
    # «extra»; a Beatrice folga à segunda — a ida dela é «extra».
    dados = sn.semana_normal()
    dados["idas"] = [sn.ida("2026-10-05", sn.ALFRAGIDE, sn.user("Emily"), "14:00", "23:00"),
                     sn.ida("2026-10-05", sn.ALFRAGIDE, sn.user("Beatrice"), "10:00", "14:00")]
    dia = _dia(dados, "2026-10-05")
    assert _quem(dia, "Alfragide") == [("Beatrice", "10:00", "14:00", "ida", True),
                                       ("Emily", "14:00", "23:00", "ida", False)]
    assert _buracos(dia)["Alfragide"] == []
