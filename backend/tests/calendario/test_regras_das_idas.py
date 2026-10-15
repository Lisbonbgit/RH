"""As regras de uma ida (desenho, secção 1 «Idas» e secção 3): o que o servidor recusa e com
que palavras. As rotas (Tarefa 7) só juntam estas respostas às consultas."""
from datetime import date

import calendario

from . import dados_semana_normal as sn

LOJAS = {l["id"]: l for l in sn.LOJAS}
UTILIZADORES = {u["id"]: u for u in sn.semana_normal()["utilizadores"]}
HH_MM = "As horas escrevem-se HH:MM (por exemplo 13:00)."
FIM_ANTES = "A hora de fim tem de ser depois da hora de início."


def _ida(data, loja, inicio, fim):
    return calendario.validar_ida(date.fromisoformat(data), LOJAS.get(loja), inicio, fim)


def test_horas_validas():
    assert calendario.validar_horas("13:00", "22:00") is None
    assert calendario.validar_horas("9:00", "22:00") == HH_MM
    assert calendario.validar_horas("13:00", "24:00") == HH_MM
    # O `$` de um `re.match` aceita uma quebra de linha no fim: gravava-se «13:00\n», que
    # escapa ao índice único (data, pessoa, loja, início).
    assert calendario.validar_horas("13:00\n", "22:00") == HH_MM
    assert calendario.validar_horas("13:00", "22:00\n") == HH_MM
    assert calendario.validar_horas(None, "22:00") == HH_MM
    assert calendario.validar_horas("22:00", "13:00") == FIM_ANTES
    assert calendario.validar_horas("13:00", "13:00") == FIM_ANTES


def test_so_em_lojas_com_horario_e_abertas_nesse_dia():
    assert _ida("2026-10-27", sn.OEIRAS, "13:00", "22:00") is None
    assert _ida("2026-10-27", sn.BELEM, "11:30", "19:00") == "Belém está fechada a 27/10. Escolha outro dia."
    assert _ida("2026-10-21", sn.BENFICA, "13:00", "22:00") == "Benfica só abre a 24/10."
    assert _ida("2026-10-27", sn.PIZZARIA, "13:00", "22:00") == "Pizzaria não tem horário e não entra no calendário."
    assert _ida("2026-10-27", "loja-apagada", "13:00", "22:00") == "Essa loja não existe."
    assert _ida("2026-10-27", sn.OEIRAS, "22:00", "13:00") == FIM_ANTES


def test_as_horas_tem_de_tocar_no_horario_e_as_que_saem_aceitam_se():
    fora = "Oeiras abre das 13h às 22h a 27/10: as horas da ida têm de tocar nesse horário."
    assert _ida("2026-10-27", sn.OEIRAS, "08:00", "12:00") == fora
    assert _ida("2026-10-27", sn.OEIRAS, "12:00", "13:00") == fora        # encostar não é tocar
    assert _ida("2026-10-27", sn.OEIRAS, "12:30", "14:00") is None        # recorta-se no cálculo


def test_o_pedido_sem_repetidos_e_com_limites():
    assert calendario.validar_pedido(["2026-10-06", "2026-10-13"], [sn.DEBORA, sn.CAROL]) is None
    trinta_e_dois = ["2026-10-%02d" % d for d in range(1, 32)] + ["2026-11-01"]
    assert calendario.validar_pedido([], [sn.DEBORA]) == "Escolha entre 1 e 31 dias."
    assert calendario.validar_pedido(trinta_e_dois, [sn.DEBORA]) == "Escolha entre 1 e 31 dias."
    assert calendario.validar_pedido(["2026-10-06"], []) == "Escolha uma ou duas pessoas."
    assert calendario.validar_pedido(["2026-10-06"], [sn.DEBORA, sn.CAROL, sn.GERENTE]) == "Escolha uma ou duas pessoas."
    assert calendario.validar_pedido(["2026-10-06", "2026-10-06"], [sn.DEBORA]) == "Há dias repetidos no pedido."
    assert calendario.validar_pedido(["2026-10-06"], [sn.DEBORA, sn.DEBORA]) == "Há pessoas repetidas no pedido."


def test_a_mesma_pessoa_nao_esta_em_dois_sitios_ao_mesmo_tempo():
    alfragide = dict(sn.ida("2026-10-27", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00"), id="a")
    nova = sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")
    assert calendario.choques([nova], [alfragide]) == [(nova, alfragide)]
    assert calendario.choques([dict(nova, inicio="14:00")], [alfragide]) == []        # encostadas
    assert calendario.choques([dict(nova, user_id=sn.CAROL)], [alfragide]) == []      # outra pessoa
    assert calendario.choques([dict(nova, data="2026-10-28")], [alfragide]) == []     # outro dia
    assert calendario.choques([dict(alfragide, inicio="11:00")], [alfragide], ignorar_id="a") == []   # o PUT


def test_a_mensagem_do_choque_diz_quem_onde_e_quando():
    alfragide = sn.ida("2026-10-21", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00")
    nova = sn.ida("2026-10-21", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")
    assert calendario.mensagem_de_choque(nova, alfragide, UTILIZADORES, {sn.ALFRAGIDE: "Alfragide"}) == \
        "Débora já está em Alfragide das 10h às 14h a 21/10."
    assert calendario.mensagem_de_choque(nova, alfragide, UTILIZADORES, {}) == \
        "Débora já está em (loja removida) das 10h às 14h a 21/10."


def test_um_colaborador_com_ausencia_aprovada_nao_se_marca():
    ausencias = [sn.ausencia("Weber", "2026-10-21", "2026-10-25"),
                 sn.ausencia("Joana", "2026-10-27", "2026-10-27", status="pendente"),
                 sn.ausencia("Emily", "2026-10-26", "2026-10-26", tipo="folga")]
    novas = [sn.ida(d, sn.AMADORA, sn.user("Weber"), "14:00", "23:00") for d in ("2026-10-20", "2026-10-22", "2026-10-23")]
    novas += [sn.ida("2026-10-27", sn.OEIRAS, sn.user("Joana"), "13:00", "22:00"),
              sn.ida("2026-10-26", sn.OEIRAS, sn.user("Emily"), "13:00", "22:00"),
              sn.ida("2026-10-22", sn.AMADORA, sn.DEBORA, "14:00", "23:00")]
    assert calendario.ausencias_que_impedem(novas, UTILIZADORES, ausencias) == [
        "Weber está de férias a 22/10.", "Weber está de férias a 23/10.", "Emily está de folga a 26/10."]
