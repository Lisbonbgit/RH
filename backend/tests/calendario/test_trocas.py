"""As trocas no cálculo (desenho `2026-10-20-calendario-trocas-historico-design.md`, §1 e §5 1–3).

Uma troca é uma ida com `troca_id` e `no_lugar_de_emp`: tira à escala de quem sai as horas da
troca, só se nesse dia a escala dele é na loja da troca. Semana normal: a 27/10 (terça) a Emily
está em Alfragide 14h–23h e a Joana na Amadora 14h–23h, a Beatrice e o Weber de folga; a 30/10
(sexta) a Emily 14h–23h e a Beatrice 10h–19h, ambas em Alfragide.
"""
from datetime import date

import calendario

from . import dados_semana_normal as sn

EMILY, BEATRICE, JOANA, WEBER = (sn.user(n) for n in ("Emily", "Beatrice", "Joana", "Weber"))
TERCA, SEXTA = date(2026, 10, 27), date(2026, 10, 30)


def troca(data, loja, user_id, inicio, fim, sai, troca_id="t-1"):
    return dict(sn.ida(data, loja, user_id, inicio, fim), troca_id=troca_id, no_lugar_de_emp=sn.emp(sai))


def _quem(dados, dia, nome_loja):
    loja = next(l for l in calendario.dia_do_calendario(dia, dados)["lojas"] if l["nome"] == nome_loja)
    return [(p["nome"], p["inicio"], p["fim"], p["origem"], p["extra"], p["no_lugar_de"]) for p in loja["pessoas"]]


def _com(*idas):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    return dados


def _feriado(iso, loja=None):
    return {"name": "Feriado de teste", "month": int(iso[5:7]), "day": int(iso[8:10]),
            "company_id": None, "location_id": loja}


# --- §5 1: o cálculo ----------------------------------------------------------------------


def test_troca_simples_a_beatrice_no_lugar_da_emily():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "23:00", "Emily"))
    assert _quem(dados, TERCA, "Alfragide") == [("Beatrice", "14:00", "23:00", "ida", False, "Emily")]
    [beatrice] = next(l for l in calendario.dia_do_calendario(TERCA, dados)["lojas"]
                      if l["nome"] == "Alfragide")["pessoas"]
    assert (beatrice["troca_id"], beatrice["ida_id"]) == ("t-1", dados["idas"][0]["id"])


def test_meio_dia_a_emily_fica_no_resto():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "18:00", "Emily"))
    assert _quem(dados, TERCA, "Alfragide") == [
        ("Beatrice", "14:00", "18:00", "ida", False, "Emily"), ("Emily", "18:00", "23:00", "escala", False, None)]


def test_cada_linha_diz_se_e_o_turno_inteiro_da_escala():
    # A metade que sobra de uma troca de meio dia não é o turno inteiro (trocar os turnos dava
    # sempre 409); uma ida não é da escala (None).
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "18:00", "Emily"))
    lojas = {l["nome"]: l for l in calendario.dia_do_calendario(TERCA, dados)["lojas"]}
    assert [(p["nome"], p["turno_inteiro"]) for p in lojas["Alfragide"]["pessoas"]] == [
        ("Beatrice", None), ("Emily", False)]
    assert [(p["nome"], p["turno_inteiro"]) for p in lojas["Amadora"]["pessoas"]] == [("Joana", True)]


def test_troca_entre_si_com_lojas_diferentes():
    dados = _com(troca("2026-10-27", sn.AMADORA, EMILY, "14:00", "23:00", "Joana"),
                 troca("2026-10-27", sn.ALFRAGIDE, JOANA, "14:00", "23:00", "Emily"))
    assert _quem(dados, TERCA, "Alfragide") == [("Joana", "14:00", "23:00", "ida", False, "Emily")]
    assert _quem(dados, TERCA, "Amadora") == [("Emily", "14:00", "23:00", "ida", False, "Joana")]


def test_troca_entre_si_com_turnos_diferentes_na_mesma_loja():
    dados = _com(troca("2026-10-30", sn.ALFRAGIDE, EMILY, "10:00", "19:00", "Beatrice"),
                 troca("2026-10-30", sn.ALFRAGIDE, BEATRICE, "14:00", "23:00", "Emily"))
    assert _quem(dados, SEXTA, "Alfragide") == [
        ("Emily", "10:00", "19:00", "ida", False, "Beatrice"), ("Beatrice", "14:00", "23:00", "ida", False, "Emily")]


def test_um_gestor_no_lugar_de_um_colaborador():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, sn.CAROL, "14:00", "23:00", "Emily"))
    assert _quem(dados, TERCA, "Alfragide") == [("Carol Santos", "14:00", "23:00", "ida", False, "Emily")]


def test_a_escala_de_quem_sai_mudou_de_loja_depois_e_a_troca_nao_lhe_tira_nada():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "23:00", "Emily"))
    terca = next(d for d in next(m for m in dados["modelos"] if m["id"] == "m-emily")["dias"] if d["dia"] == 1)
    terca["location_id"] = sn.AMADORA
    assert ("Emily", "14:00", "23:00", "escala", False, None) in _quem(dados, TERCA, "Amadora")
    assert _quem(dados, TERCA, "Alfragide") == [("Beatrice", "14:00", "23:00", "ida", False, "Emily")]


def test_a_ausencia_aprovada_de_quem_entra_depois_da_troca_nao_a_apaga_regra_b():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "23:00", "Emily"))
    dados["ausencias"].append(sn.ausencia("Beatrice", "2026-10-27", "2026-10-27"))
    assert _quem(dados, TERCA, "Alfragide") == [("Beatrice", "14:00", "23:00", "ida", True, "Emily")]


def test_a_ausencia_de_quem_sai_tira_a_escala_e_a_troca_fica():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "18:00", "Emily"))
    dados["ausencias"].append(sn.ausencia("Emily", "2026-10-27", "2026-10-27"))
    assert _quem(dados, TERCA, "Alfragide") == [("Beatrice", "14:00", "18:00", "ida", False, "Emily")]


def test_o_ajudante_do_feriado_nacional_e_da_loja():
    alfragide = next(l for l in sn.LOJAS if l["id"] == sn.ALFRAGIDE)
    amadora = next(l for l in sn.LOJAS if l["id"] == sn.AMADORA)
    assert calendario.escala_vazia_no_feriado(date(2026, 10, 5), [], alfragide) is True
    so_alfragide = [_feriado("2026-10-27", loja=sn.ALFRAGIDE)]
    assert calendario.escala_vazia_no_feriado(TERCA, so_alfragide, alfragide) is True
    assert calendario.escala_vazia_no_feriado(TERCA, so_alfragide, amadora) is False
    dados = sn.semana_normal()
    dados["feriados"] = so_alfragide
    assert _quem(dados, TERCA, "Alfragide") == []
    assert _quem(dados, TERCA, "Amadora") == [("Joana", "14:00", "23:00", "escala", False, None)]


def test_quem_esta_na_escala_sem_conta_continua_a_aparecer_e_a_troca_sobrevive():
    dados = _com(troca("2026-10-30", sn.ALFRAGIDE, sn.CAROL, "10:00", "14:00", "Beatrice"))
    dados["utilizadores"] = [u for u in dados["utilizadores"] if u["id"] not in (EMILY, BEATRICE)]
    loja = next(l for l in calendario.dia_do_calendario(SEXTA, dados)["lojas"] if l["nome"] == "Alfragide")
    assert [(p["user_id"], p["nome"], p["inicio"], p["fim"], p["troca_id"], p["no_lugar_de"]) for p in loja["pessoas"]] == [
        (sn.CAROL, "Carol Santos", "10:00", "14:00", "t-1", "Beatrice"),
        (None, "Beatrice", "14:00", "19:00", None, None),
        (None, "Emily", "14:00", "23:00", None, None)]


def test_a_resposta_do_mes_leva_a_troca_nas_idas_e_o_pode_trocar():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "23:00", "Emily"),
                 sn.ida("2026-10-28", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"))
    r = calendario.resposta_do_mes(2026, 10, dados, sn.DEBORA, True, pode_trocar=True)
    assert r["pode_trocar"] is True
    assert [(i["nome"], i["troca_id"], i["no_lugar_de"]) for i in r["idas"]] == [
        ("Beatrice", "t-1", "Emily"), ("Débora Ferreira", None, None)]
    assert calendario.resposta_do_mes(2026, 10, dados, sn.GERENTE, True)["pode_trocar"] is False


# --- §5 2: escala_de ----------------------------------------------------------------------


def test_escala_de_da_a_loja_e_as_horas():
    dados = sn.semana_normal()
    assert calendario.escala_de(TERCA, dados, sn.emp("Emily")) == (sn.ALFRAGIDE, (14 * 60, 23 * 60))
    assert calendario.escala_de(TERCA, dados, sn.emp("Joana")) == (sn.AMADORA, (14 * 60, 23 * 60))


def test_escala_de_folga_ausencia_e_feriado_nao_esta_na_escala():
    dados = sn.semana_normal()
    assert calendario.escala_de(TERCA, dados, sn.emp("Beatrice")) is None          # folga
    dados["ausencias"].append(sn.ausencia("Emily", "2026-10-27", "2026-10-27"))
    assert calendario.escala_de(TERCA, dados, sn.emp("Emily")) is None             # ausência aprovada
    assert calendario.escala_de(date(2026, 10, 5), dados, sn.emp("Emily")) is None  # feriado nacional
    dados["feriados"] = [_feriado("2026-10-27", loja=sn.AMADORA)]
    assert calendario.escala_de(TERCA, dados, sn.emp("Joana")) is None             # feriado da loja


def test_escala_de_nao_olha_a_ausencia_pendente():
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Emily", "2026-10-27", "2026-10-27", status="pendente"))
    assert calendario.escala_de(TERCA, dados, sn.emp("Emily")) == (sn.ALFRAGIDE, (14 * 60, 23 * 60))


# --- §5 3: a contagem ----------------------------------------------------------------------

LOJAS = {l["id"]: l for l in sn.LOJAS}
NOMES = {sn.CAROL: "Carol Santos", BEATRICE: "Beatrice", JOANA: "Joana", EMILY: "Emily", sn.GERENTE: "Guilherme Gestor"}
PAPEIS = {sn.CAROL: "admin", BEATRICE: "colaborador", JOANA: "colaborador", EMILY: "colaborador",
          sn.GERENTE: "gerente"}


def test_a_troca_com_um_gestor_conta():
    idas = [troca("2026-10-27", sn.ALFRAGIDE, sn.CAROL, "14:00", "23:00", "Emily")]
    [linha] = calendario.contagem(idas, LOJAS, NOMES, PAPEIS)
    assert (linha["user_id"], linha["total"]) == (sn.CAROL, 1.0)


def test_a_troca_com_um_gerente_tambem_conta():
    idas = [troca("2026-10-27", sn.AMADORA, sn.GERENTE, "14:00", "23:00", "Joana")]
    [linha] = calendario.contagem(idas, LOJAS, NOMES, PAPEIS)
    assert (linha["user_id"], linha["total"]) == (sn.GERENTE, 1.0)


def test_a_troca_entre_colaboradores_nao_conta_e_a_ida_normal_conta_como_hoje():
    idas = [troca("2026-10-27", sn.AMADORA, EMILY, "14:00", "23:00", "Joana"),
            troca("2026-10-27", sn.ALFRAGIDE, JOANA, "14:00", "23:00", "Emily"),
            sn.ida("2026-10-28", sn.BENFICA, JOANA, "13:00", "22:00")]
    assert [(l["user_id"], l["total"]) for l in calendario.contagem(idas, LOJAS, NOMES, PAPEIS)] == [(JOANA, 1.0)]


# --- As recusas puras (desenho, «Recusas») -------------------------------------------------


def _recusa(sai, entra, inicio, fim, dados=None, dia=TERCA):
    dados = dados or sn.semana_normal()
    return calendario.recusa_da_troca(dia, dados, sn.emp(sai), sai, entra, inicio, fim,
                                      [i for i in dados["idas"] if i["data"] == dia.isoformat()])


def test_a_troca_valida_nao_tem_recusa():
    assert _recusa("Emily", BEATRICE, "14:00", "23:00") is None
    assert _recusa("Emily", sn.CAROL, "15:00", "18:00") is None


def test_quem_sai_nao_esta_na_escala():
    assert _recusa("Beatrice", EMILY, "10:00", "19:00") == (409, "Beatrice não está na escala a 27/10.")
    assert _recusa("Emily", BEATRICE, "14:00", "23:00", dia=date(2026, 10, 5)) == (
        409, "Emily não está na escala a 05/10.")


def test_as_horas_da_troca_saem_das_de_quem_sai():
    assert _recusa("Emily", BEATRICE, "13:00", "23:00") == (
        409, "As horas da troca têm de estar dentro das de Emily (14h–23h).")
    assert _recusa("Emily", BEATRICE, "14:00", "23:30") == (
        409, "As horas da troca têm de estar dentro das de Emily (14h–23h).")


def test_sai_igual_a_entra():
    assert _recusa("Emily", EMILY, "14:00", "23:00") == (400, "Escolha outra pessoa.")


def test_horas_mal_escritas_sao_400_como_nas_idas():
    assert _recusa("Emily", BEATRICE, "14h", "23:00") == (400, "As horas escrevem-se HH:MM (por exemplo 13:00).")


def test_ja_ha_troca_para_quem_sai_com_horas_que_se_sobrepoem():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "18:00", "Emily"))
    assert _recusa("Emily", WEBER, "17:00", "23:00", dados) == (409, "Já há uma troca para Emily a 27/10 (Beatrice).")
    # Horas encostadas não se sobrepõem: a outra metade do turno troca-se à parte.
    assert _recusa("Emily", WEBER, "18:00", "23:00", dados) is None


def test_ja_ha_troca_feita_por_uma_conta_que_ja_nao_existe():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, "u-apagada", "14:00", "18:00", "Emily"))
    assert _recusa("Emily", WEBER, "14:00", "23:00", dados) == (
        409, "Já há uma troca para Emily a 27/10 (conta removida).")


def test_turnos_da_troca_entre_si_com_lojas_diferentes():
    ida_emily, ida_joana = calendario.turnos_da_troca_entre_si(TERCA, sn.semana_normal(), sn.emp("Emily"), sn.emp("Joana"))
    assert ida_emily == {"data": "2026-10-27", "location_id": sn.AMADORA, "user_id": EMILY,
                         "inicio": "14:00", "fim": "23:00", "no_lugar_de_emp": sn.emp("Joana")}
    assert ida_joana == {"data": "2026-10-27", "location_id": sn.ALFRAGIDE, "user_id": JOANA,
                         "inicio": "14:00", "fim": "23:00", "no_lugar_de_emp": sn.emp("Emily")}


def test_turnos_da_troca_entre_si_com_turnos_diferentes():
    ida_emily, ida_beatrice = calendario.turnos_da_troca_entre_si(
        SEXTA, sn.semana_normal(), sn.emp("Emily"), sn.emp("Beatrice"))
    assert (ida_emily["location_id"], ida_emily["inicio"], ida_emily["fim"]) == (sn.ALFRAGIDE, "10:00", "19:00")
    assert (ida_beatrice["location_id"], ida_beatrice["inicio"], ida_beatrice["fim"]) == (sn.ALFRAGIDE, "14:00", "23:00")


def test_as_recusas_da_troca_entre_si():
    dados = sn.semana_normal()
    entre = calendario.turnos_da_troca_entre_si
    assert entre(TERCA, dados, sn.emp("Emily"), sn.emp("Beatrice")) == (409, "Beatrice não está na escala a 27/10.")
    assert entre(TERCA, dados, sn.emp("Weber"), sn.emp("Emily")) == (409, "Weber não está na escala a 27/10.")
    assert entre(TERCA, dados, sn.emp("Emily"), sn.emp("Emily")) == (400, "Escolha outra pessoa.")
    # Sexta: o Weber na Amadora 14h–23h e a Joana em Algueirão 13h–22h. Com a Joana também na
    # Amadora, a troca não mudava nada.
    sexta_joana = next(d for d in next(m for m in dados["modelos"] if m["id"] == "m-joana")["dias"] if d["dia"] == 4)
    sexta_joana["location_id"] = sn.AMADORA
    assert entre(SEXTA, dados, sn.emp("Weber"), sn.emp("Joana")) == (400, "Escolha outra pessoa.")


def test_a_troca_entre_si_recusa_quem_ja_tem_troca_nesse_dia():
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "18:00", "Emily"))
    assert calendario.turnos_da_troca_entre_si(TERCA, dados, sn.emp("Joana"), sn.emp("Emily")) == (
        409, "Já há uma troca para Emily a 27/10 (Beatrice).")


def test_a_troca_que_ficou_noutra_loja_nao_impede_trocar_a_escala_nova():
    # A Beatrice no lugar da Emily em Alfragide; depois a escala de terça da Emily passa para a
    # Amadora. O cálculo já não tira nada à linha nova (a troca fica uma ida à vista), por isso
    # as recusas também não a podem contar: a linha nova troca-se.
    dados = _com(troca("2026-10-27", sn.ALFRAGIDE, BEATRICE, "14:00", "23:00", "Emily"))
    terca = next(d for d in next(m for m in dados["modelos"] if m["id"] == "m-emily")["dias"] if d["dia"] == 1)
    terca["location_id"] = sn.AMADORA
    assert _recusa("Emily", WEBER, "14:00", "23:00", dados) is None
    turnos = calendario.turnos_da_troca_entre_si(TERCA, dados, sn.emp("Emily"), sn.emp("Walisson"))
    assert [i["location_id"] if isinstance(i, dict) else i for i in turnos] == [sn.ALGUEIRAO, sn.AMADORA]
