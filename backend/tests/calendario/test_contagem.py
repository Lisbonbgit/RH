"""A contagem (desenho, «Contagem» e Testes 6): quantos dias cada pessoa fez no ano.

Uma ida vale 1 dia se as horas DENTRO do horário da loja nesse dia forem pelo menos metade
das horas de abertura, e 0,5 se forem menos; por pessoa e dia soma-se e corta-se em 1. Conta
as idas marcadas, futuras incluídas — é o que as gestoras usam para se equilibrarem.
"""
import calendario

from . import dados_semana_normal as sn

LOJAS = {l["id"]: l for l in sn.LOJAS}
NOMES = {sn.DEBORA: "Débora Ferreira", sn.CAROL: "Carol Santos"}


def _valor(loja, inicio, fim, data="2026-10-27"):
    return calendario.valor_da_ida(sn.ida(data, loja, sn.DEBORA, inicio, fim), LOJAS.get(loja))


def test_metade_ou_mais_do_horario_vale_um_dia():
    assert _valor(sn.OEIRAS, "13:00", "22:00") == 1.0
    assert _valor(sn.OEIRAS, "13:00", "17:30") == 1.0      # 4h30 de 9h: exactamente metade
    assert _valor(sn.OEIRAS, "13:00", "17:29") == 0.5
    assert _valor(sn.ALFRAGIDE, "10:00", "14:00") == 0.5   # 4h de 13h


def test_so_contam_as_horas_dentro_do_horario():
    assert _valor(sn.OEIRAS, "08:00", "17:00") == 0.5       # 9h de ida, só 4h dentro


def test_a_metade_e_a_do_horario_desse_dia():
    assert _valor(sn.BELEM, "11:30", "15:30", data="2026-10-31") == 1.0   # sábado: 4h de 7h30
    assert _valor(sn.BELEM, "11:30", "15:30", data="2026-11-01") == 0.5   # domingo: 4h de 8h30


def test_numa_loja_sem_horario_fechada_ou_apagada_vale_um_dia():
    assert _valor(sn.PIZZARIA, "10:00", "11:00") == 1.0
    assert _valor(sn.BELEM, "11:30", "12:00", data="2026-10-27") == 1.0   # terça: fechada
    assert calendario.valor_da_ida(sn.ida("2026-10-27", "loja-apagada", sn.DEBORA, "10:00", "11:00"), None) == 1.0


def test_duas_meias_no_mesmo_dia_sao_um_dia_e_nunca_mais_de_um():
    idas = [sn.ida("2026-10-27", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00"),   # 0,5
            sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "18:00", "22:00"),      # 0,5
            sn.ida("2026-10-28", sn.ALFRAGIDE, sn.DEBORA, "10:00", "17:00"),   # 1
            sn.ida("2026-10-28", sn.OEIRAS, sn.DEBORA, "17:00", "22:00")]      # 1, mas o dia corta em 1
    [linha] = calendario.contagem(idas, LOJAS, NOMES)
    assert (linha["meses"][9], linha["total"]) == (2.0, 2.0)


def test_os_meses_o_total_o_nome_e_a_ordem():
    idas = [sn.ida("2026-10-06", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
            sn.ida("2026-11-03", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00"),
            sn.ida("2026-12-08", sn.ALFRAGIDE, sn.CAROL, "10:00", "23:00"),
            sn.ida("2026-12-09", sn.ALFRAGIDE, sn.CAROL, "10:00", "23:00"),
            sn.ida("2026-12-10", sn.ALFRAGIDE, "u-apagada", "10:00", "23:00")]
    linhas = calendario.contagem(idas, LOJAS, NOMES)
    assert [(l["user_id"], l["nome"], l["total"]) for l in linhas] == [
        (sn.CAROL, "Carol Santos", 2.0), (sn.DEBORA, "Débora Ferreira", 1.5), ("u-apagada", "(conta removida)", 1.0)]
    assert linhas[1]["meses"] == [0.0] * 9 + [1.0, 0.5, 0.0]
