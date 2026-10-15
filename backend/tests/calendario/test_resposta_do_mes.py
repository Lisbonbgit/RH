"""A resposta do `GET /api/bolso/calendario` (desenho, secção 3): o mês inteiro num pedido.

`idas[]` é de onde o ecrã monta a vista Pessoal e as idas da Lista (não de `dias`): uma ida
numa loja que entretanto perdeu o horário continua a aparecer aqui. Os nomes têm recurso.
"""
import calendario

from . import dados_semana_normal as sn


def _resposta(eu=sn.DEBORA, pode_marcar=True):
    dados = sn.semana_normal()
    dados["ausencias"] += [sn.ausencia("Weber", "2026-10-21", "2026-10-25"),
                           sn.ausencia("Joana", "2026-10-28", "2026-10-28", status="pendente"),
                           sn.ausencia("Rafaela", "2026-09-01", "2026-09-30")]
    dados["idas"] += [sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                      sn.ida("2026-10-06", sn.PIZZARIA, "u-apagada", "10:00", "12:00"),
                      dict(sn.ida("2026-10-06", "loja-apagada", sn.CAROL, "10:00", "12:00"), id="i-orfa"),
                      sn.ida("2026-11-03", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")]
    return calendario.resposta_do_mes(2026, 10, dados, eu, pode_marcar)


def test_o_cabecalho_e_os_dias_do_mes():
    r = _resposta()
    assert (r["ano"], r["mes"], r["eu"], r["pode_marcar"]) == (2026, 10, sn.DEBORA, True)
    assert len(r["dias"]) == 31 and r["dias"][0]["data"] == "2026-10-01"
    assert calendario.limites_do_mes(2026, 2) == ("2026-02-01", "2026-02-28")


def test_as_idas_do_mes_com_os_nomes_e_o_recurso_para_o_que_foi_apagado():
    idas = _resposta()["idas"]
    assert [(i["data"], i["nome"], i["loja"]) for i in idas] == [
        ("2026-10-06", "(conta removida)", "Pizzaria"),
        ("2026-10-06", "Carol Santos", "(loja removida)"),
        ("2026-10-27", "Débora Ferreira", "Oeiras"),
    ]
    assert set(idas[2]) == {"id", "data", "location_id", "user_id", "inicio", "fim", "nome", "loja"}


def test_as_ausencias_sao_so_as_aprovadas_que_tocam_o_mes():
    assert _resposta()["ausencias"] == [
        {"nome": "Weber", "tipo": "ferias", "inicio": "2026-10-21", "fim": "2026-10-25", "loja": "Amadora"}]


def test_as_lojas_sao_so_as_com_horario_por_nome():
    assert _resposta()["lojas"] == [
        {"id": sn.ALFRAGIDE, "nome": "Alfragide"}, {"id": sn.ALGUEIRAO, "nome": "Algueirão"},
        {"id": sn.AMADORA, "nome": "Amadora"}, {"id": sn.BELEM, "nome": "Belém"},
        {"id": sn.BENFICA, "nome": "Benfica"}, {"id": sn.OEIRAS, "nome": "Oeiras"}]


def test_as_pessoas_gestores_primeiro_depois_colaboradores_sem_o_contabilista():
    assert [(p["nome"], p["tipo"]) for p in _resposta()["pessoas"]] == [
        ("Carol Santos", "gestor"), ("Débora Ferreira", "gestor"), ("Guilherme Gestor", "gestor"),
        ("Beatrice", "colaborador"), ("Emanuela", "colaborador"), ("Emily", "colaborador"),
        ("Joana", "colaborador"), ("Rafaela", "colaborador"), ("Walisson", "colaborador"), ("Weber", "colaborador")]


def test_o_contabilista_le_sem_poder_marcar():
    r = _resposta(eu=sn.CONTABILISTA, pode_marcar=False)
    assert (r["eu"], r["pode_marcar"]) == (sn.CONTABILISTA, False)
