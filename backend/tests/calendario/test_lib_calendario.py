"""As contas do ecrã do calendário (`frontend/src/lib/calendario.js`), corridas em Node
contra a resposta REAL do mês (`calendario.resposta_do_mes` sobre a semana normal) — se o
servidor mudar a forma da resposta, é aqui que se vê, e não no telemóvel do dono."""
import json

import calendario
from tests.bolso_js import correr_js

from . import dados_semana_normal as sn


def _outubro(idas=(), ausencias=(), eu=sn.DEBORA):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    dados["ausencias"] = list(ausencias)
    return calendario.resposta_do_mes(2026, 10, dados, eu, eu != sn.CONTABILISTA)


def _cal(tmp_path, expressao, dados=None):
    """Corre `expressao` com `cal` = lib/calendario.js e `D` = a resposta do mês."""
    return correr_js("const cal = importar('lib/calendario');\nconst D = %s;\ndevolve(%s);"
                     % (json.dumps(dados, ensure_ascii=False), expressao), tmp_path)


def test_o_hoje_e_o_dia_do_telemovel_e_nao_o_de_utc(tmp_path):
    # 16/10 às 00:30 em Lisboa (o TZ do Node é Europe/Lisbon) ainda é 15/10 em UTC.
    r = _cal(tmp_path, "[cal.hojeIso(new Date(2026, 9, 16, 0, 30)), "
                       "new Date(2026, 9, 16, 0, 30).toISOString().slice(0, 10)]")
    assert r == ["2026-10-16", "2026-10-15"]


def test_as_semanas_do_mes_comecam_a_segunda(tmp_path):
    outubro, novembro, fevereiro = _cal(
        tmp_path, "[cal.semanasDoMes(2026, 10), cal.semanasDoMes(2026, 11).length, cal.semanasDoMes(2027, 2).length]")
    assert outubro[0] == [None, None, None, "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert outubro[-1] == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", None]
    assert (len(outubro), novembro, fevereiro) == (5, 6, 4)


def test_mes_ao_lado_e_titulos(tmp_path):
    r = _cal(tmp_path, "[cal.mesAoLado(2026, 12, 1), cal.mesAoLado(2026, 1, -1), cal.tituloDoMes(2026, 10), "
                       "cal.tituloDoDia('2026-10-27'), cal.dataCurta('2026-10-27'), cal.intervaloCurto('11:30', '19:00'), "
                       "cal.quantosDias(1), cal.quantosDias(0.5), cal.quantosDias(17.5)]")
    assert r == [{"ano": 2027, "mes": 1}, {"ano": 2025, "mes": 12}, "outubro 2026", "terça, 27 de outubro",
                 "27/10", "11h30–19h", "1 dia", "0,5 dias", "17,5 dias"]


def test_os_pontos_de_cada_filtro_e_os_feriados(tmp_path):
    dados = _outubro(idas=[sn.ida("2026-10-06", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                           sn.ida("2026-10-20", sn.OEIRAS, sn.CAROL, "13:00", "22:00")],
                     ausencias=[sn.ausencia("Weber", "2026-10-21", "2026-10-25")])
    geral, pessoal, ferias, feriados = _cal(
        tmp_path, "['geral', 'pessoal', 'ferias'].map((f) => cal.diasComPonto(D, f)).concat([cal.feriadosDoMes(D)])", dados)
    assert geral == [d["data"] for d in dados["dias"] if any(l["buracos"] for l in d["lojas"])]
    assert "2026-10-05" in geral and "2026-10-02" not in geral and "2026-10-31" in geral
    assert pessoal == ["2026-10-06"]
    assert ferias == ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"]
    assert feriados == ["2026-10-05"]


def test_a_lista_comeca_hoje_no_mes_corrente_e_salta_os_dias_vazios(tmp_path):
    dados = _outubro(idas=[sn.ida("2026-10-27", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00")],
                     ausencias=[sn.ausencia("Weber", "2026-10-21", "2026-10-25")])
    r = _cal(tmp_path, "{ hoje: cal.lista(D, 'geral', '2026-10-27'), "
                       "outro: cal.lista(D, 'geral', '2026-11-15').map((d) => d.data), "
                       "pessoal: cal.lista(D, 'pessoal', '2026-10-01'), ferias: cal.lista(D, 'ferias', '2026-10-23') }", dados)
    assert r["hoje"][0]["data"] == "2026-10-27"
    assert [l["nome"] for l in r["hoje"][0]["buracos"]] == ["Benfica", "Oeiras"]
    assert [i["nome"] for i in r["hoje"][0]["idas"]] == ["Débora Ferreira"]
    assert r["outro"][:3] == ["2026-10-01", "2026-10-05", "2026-10-06"]        # 02, 03 e 04/10 sem nada
    assert [(d["data"], len(d["idas"])) for d in r["pessoal"]] == [("2026-10-27", 1)]
    assert [(d["data"], [a["nome"] for a in d["ausencias"]]) for d in r["ferias"]] == [("2026-10-23", ["Weber"])]


def test_o_atalho_marca_as_outras_tercas_cujo_buraco_contem_as_horas(tmp_path):
    dados = _outubro(idas=[sn.ida("2026-10-20", sn.OEIRAS, sn.DEBORA, "13:00", "17:00")])
    r = _cal(tmp_path, "[cal.outrosDiasComBuraco(D, '2026-10-06', 'loja-oeiras', '13:00', '22:00'), "
                       "cal.outrosDiasComBuraco(D, '2026-10-06', 'loja-oeiras', '18:00', '22:00'), "
                       "cal.outrosDiasComBuraco(D, '2026-10-05', 'loja-alfragide', '10:00', '14:00'), "
                       "cal.outrosDiasComBuraco(D, '2026-10-06', '', '13:00', '22:00'), "
                       "cal.textoDoAtalho('2026-10-06', 'Oeiras'), cal.textoDoAtalho('2026-10-03', 'Belém')]", dados)
    assert r == [["2026-10-13", "2026-10-27"],                 # a 20/10 o buraco é só 17–22
                 ["2026-10-13", "2026-10-20", "2026-10-27"],
                 ["2026-10-12", "2026-10-19", "2026-10-26"], [],
                 "Também nas outras terças deste mês com buraco em Oeiras",
                 "Também nos outros sábados deste mês com buraco em Belém"]


def test_o_painel_comeca_em_mim_se_eu_puder_ser_escalado(tmp_path):
    assert _cal(tmp_path, "cal.pessoasIniciais(D)", _outubro()) == [sn.DEBORA]
    assert _cal(tmp_path, "cal.pessoasIniciais(D)", _outubro(eu=sn.CONTABILISTA)) == []


def test_a_linha_da_contagem_e_os_erros_do_servidor(tmp_path):
    r = _cal(tmp_path, "[cal.linhaDaContagem({ nome: 'Débora Ferreira', meses: [0,0,0,0,0,0,0,0,0,18,0,0], total: 60 }, 2026, 10), "
                       "cal.mensagemDeErro({ response: { status: 409, data: { detail: 'Débora já está em Alfragide.' } } }), "
                       "cal.mensagemDeErro({ response: { status: 422, data: { detail: [{ msg: 'Field required' }, { msg: 'Outro' }] } } }), "
                       "cal.mensagemDeErro({ response: { status: 500, data: {} } }), "
                       "cal.mensagemDeErro(new Error('Network Error'))]")
    assert r == ["Débora · outubro 18 dias · 2026 60 dias", "Débora já está em Alfragide.", "Field required\nOutro",
                 "O servidor recusou este pedido.", "Sem resposta do servidor. Verifique a rede e tente outra vez."]
