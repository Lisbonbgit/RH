"""As contas do ecrã do calendário (`frontend/src/lib/calendario.js`), corridas em Node
contra a resposta REAL do mês (`calendario.resposta_do_mes` sobre a semana normal) — se o
servidor mudar a forma da resposta, é aqui que se vê, e não no telemóvel do dono."""
import json

import calendario
from tests.bolso_js import correr_js

from . import dados_semana_normal as sn


def _mes(ano, mes, idas=(), ausencias=(), eu=sn.DEBORA, pode_marcar=None):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    dados["ausencias"] = list(ausencias)
    return calendario.resposta_do_mes(ano, mes, dados, eu, eu != sn.CONTABILISTA if pode_marcar is None else pode_marcar)


def _outubro(idas=(), ausencias=(), eu=sn.DEBORA):
    return _mes(2026, 10, idas, ausencias, eu)


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


# --- A vista Semana e o filtro de loja (adenda de 2026-10-15) --------------------------------

SEMANA_DE_29_10 = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]


def test_a_semana_vai_de_segunda_a_domingo_e_e_a_primeira_vista(tmp_path):
    quinta, domingo, segunda, outro_domingo, vistas = _cal(
        tmp_path, "[cal.semanaDe('2026-10-29'), cal.semanaDe('2026-11-01'), cal.semanaDe('2026-10-26'), "
                  "cal.semanaDe('2026-10-04'), cal.VISTAS]")
    assert quinta == SEMANA_DE_29_10
    assert domingo == SEMANA_DE_29_10          # o domingo FECHA a semana, não abre a seguinte
    assert segunda == SEMANA_DE_29_10
    assert outro_domingo == ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02",
                             "2026-10-03", "2026-10-04"]
    assert vistas == ["semana", "mes", "lista", "contagem"]


def test_o_dia_ao_lado_atravessa_o_mes_o_ano_e_a_mudanca_de_hora(tmp_path):
    r = _cal(tmp_path, "[['2026-10-31', 1], ['2026-11-01', -1], ['2026-12-29', 7], ['2027-01-03', -7], "
                       "['2026-10-24', 1], ['2026-10-25', 1], ['2026-10-26', -1], ['2026-10-19', 7], ['2026-11-01', -7]]"
                       ".map(([iso, passo]) => cal.diaAoLado(iso, passo))")
    # 25/10/2026 tem 25 horas (acaba a hora de verão): somar 24 h à meia-noite local não muda o dia.
    assert r == ["2026-11-01", "2026-10-31", "2027-01-05", "2026-12-27",
                 "2026-10-25", "2026-10-26", "2026-10-25", "2026-10-26", "2026-10-25"]


def test_os_meses_e_o_titulo_da_semana(tmp_path):
    r = _cal(tmp_path, "[cal.mesesDaSemana('2026-10-14'), cal.mesesDaSemana('2026-10-29'), cal.mesesDaSemana('2026-12-31'), "
                       "cal.tituloDaSemana('2026-10-29'), cal.tituloDaSemana('2026-10-07'), cal.tituloDaSemana('2026-01-01'), "
                       "cal.tituloDaSemana('2026-02-28')]")
    assert r == [[{"ano": 2026, "mes": 10}],
                 [{"ano": 2026, "mes": 10}, {"ano": 2026, "mes": 11}],
                 [{"ano": 2026, "mes": 12}, {"ano": 2027, "mes": 1}],
                 "26 out – 1 nov", "5 – 11 out", "29 dez – 4 jan", "23 fev – 1 mar"]


def test_o_nome_curto_da_loja_tira_so_o_loja_do_inicio(tmp_path):
    assert _cal(tmp_path, "['Loja Alfragide', 'Escritório', 'Alfragide', 'Lojas Unidas'].map(cal.nomeCurtoDaLoja)") == [
        "Alfragide", "Escritório", "Alfragide", "Lojas Unidas"]


def test_as_celulas_da_semana_no_geral_e_no_pessoal(tmp_path):
    # 27/10 (terça) é a semana normal sem idas. A 29/10 a Débora vai a Alfragide das 20h às 22h
    # (a Beatrice fica até às 19h: faltam 19–20 e 22–23) e a Carol vai duas vezes a Benfica.
    dados = _outubro(idas=[sn.ida("2026-10-29", sn.ALFRAGIDE, sn.DEBORA, "20:00", "22:00"),
                           sn.ida("2026-10-29", sn.BENFICA, sn.CAROL, "15:00", "18:00"),
                           sn.ida("2026-10-29", sn.BENFICA, sn.CAROL, "19:00", "20:00")])
    r = _cal(tmp_path, """(() => {
      const loja = (data, id) => D.dias.find((d) => d.data === data).lojas.find((l) => l.location_id === id);
      const geral = (data, id) => cal.celulaDaSemana(loja(data, id), 'geral', D.eu);
      return {
        alfragide: geral('2026-10-27', 'loja-alfragide'), algueirao: geral('2026-10-27', 'loja-algueirao'),
        belem: geral('2026-10-27', 'loja-belem'), oeiras: geral('2026-10-27', 'loja-oeiras'),
        benficaPorAbrir: geral('2026-10-20', 'loja-benfica'), duas: geral('2026-10-29', 'loja-alfragide'),
        tres: geral('2026-10-29', 'loja-benfica'),
        minha: cal.celulaDaSemana(loja('2026-10-29', 'loja-alfragide'), 'pessoal', 'u-debora'),
        daCarol: cal.celulaDaSemana(loja('2026-10-29', 'loja-benfica'), 'pessoal', 'u-carol'),
        naoMinha: cal.celulaDaSemana(loja('2026-10-29', 'loja-benfica'), 'pessoal', 'u-debora'),
        soEscala: cal.celulaDaSemana(loja('2026-10-27', 'loja-alfragide'), 'pessoal', 'u-emily'),
        pessoalPorAbrir: cal.celulaDaSemana(undefined, 'pessoal', 'u-debora'),
      };
    })()""", dados)
    assert r["alfragide"] == {"estado": "falta", "texto": "10h–14h"}
    assert r["algueirao"] == {"estado": "ok", "texto": "ok"}
    assert r["belem"] == {"estado": "fechada", "texto": "fech."}
    assert r["oeiras"] == {"estado": "ninguem", "texto": "—"}
    assert r["benficaPorAbrir"] == {"estado": "vazia", "texto": ""}
    assert r["duas"] == {"estado": "falta", "texto": "2 faltas"}
    assert r["tres"] == {"estado": "falta", "texto": "3 faltas"}
    assert r["minha"] == {"estado": "minha", "texto": "20h–22h"}            # a Beatrice (escala) não entra
    assert r["daCarol"] == {"estado": "minha", "texto": "15h–18h · 19h–20h"}
    assert r["naoMinha"] == {"estado": "vazia", "texto": ""}
    assert r["soEscala"] == {"estado": "vazia", "texto": ""}              # a escala não é uma ida
    assert r["pessoalPorAbrir"] == {"estado": "vazia", "texto": ""}


def test_juntar_dois_meses_sem_repetir_as_ausencias(tmp_path):
    idas = [sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
            sn.ida("2026-11-03", sn.OEIRAS, sn.CAROL, "13:00", "22:00")]
    ausencias = [sn.ausencia("Weber", "2026-10-30", "2026-11-02"), sn.ausencia("Emanuela", "2026-11-10", "2026-11-12")]
    outubro = _mes(2026, 10, idas, ausencias)
    novembro = _mes(2026, 11, idas, ausencias, pode_marcar=False)
    r = _cal(tmp_path, """(() => {
      const J = cal.juntarMeses(D);
      const S = cal.juntarMeses([D[0]]);
      return { dias: J.dias.map((d) => d.data), idas: J.idas.map((i) => i.data),
               ausencias: J.ausencias.map((a) => a.nome), lojas: J.lojas, pessoas: J.pessoas,
               eu: J.eu, pode_marcar: J.pode_marcar, ferias: cal.diasComPonto(J, 'ferias'),
               so: [S.dias.length, S.idas.length, S.ausencias.length] };
    })()""", [outubro, novembro])
    assert r["dias"] == [d["data"] for d in outubro["dias"] + novembro["dias"]] and len(r["dias"]) == 61
    assert r["idas"] == ["2026-10-27", "2026-11-03"]
    assert r["ausencias"] == ["Weber", "Emanuela"]                          # a do Weber vinha nas duas
    assert (r["lojas"], r["pessoas"], r["eu"], r["pode_marcar"]) == (
        outubro["lojas"], outubro["pessoas"], sn.DEBORA, True)
    assert r["ferias"] == ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02",
                           "2026-11-10", "2026-11-11", "2026-11-12"]
    assert r["so"] == [31, 1, 1]


def test_o_filtro_de_loja_deixa_so_essa_loja_e_as_ausencias_de_quem_la_tem_a_ficha(tmp_path):
    dados = _outubro(idas=[sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                           sn.ida("2026-10-27", sn.ALFRAGIDE, sn.CAROL, "10:00", "14:00")],
                     ausencias=[sn.ausencia("Weber", "2026-10-21", "2026-10-25"),
                                sn.ausencia("Emanuela", "2026-10-14", "2026-10-15")])
    r = _cal(tmp_path, """(() => {
      const F = cal.filtrarPorLoja(D, 'loja-oeiras');
      return { lojasPorDia: [...new Set(F.dias.map((d) => d.lojas.map((l) => l.location_id).join(',')))],
               dias: F.dias.length, idas: F.idas.map((i) => i.loja), lojas: F.lojas,
               ausencias: F.ausencias.map((a) => a.nome), pontos: cal.diasComPonto(F, 'geral'),
               ferias: cal.lista(F, 'ferias', '2026-10-01').map((d) => d.ausencias.map((a) => a.nome)),
               vazio: cal.filtrarPorLoja(D, '') === D, intacto: D.dias[26].lojas.length };
    })()""", dados)
    assert r["lojasPorDia"] == ["loja-oeiras"] and r["dias"] == 31
    assert r["idas"] == ["Oeiras"]
    assert r["lojas"] == [{"id": sn.OEIRAS, "nome": "Oeiras"}]
    assert r["ausencias"] == ["Emanuela"]                                   # o Weber é de Amadora
    # 05/10 é feriado (a escala não põe ninguém); 15/10 a Emanuela de férias; 27/10 tapado.
    assert r["pontos"] == ["2026-10-05", "2026-10-06", "2026-10-13", "2026-10-15", "2026-10-20"]
    assert r["ferias"] == [["Emanuela"]]
    assert r["vazio"] is True
    assert r["intacto"] == 6                                                # não estraga os dados do mês


# --- As trocas e o histórico (2026-10-22) ------------------------------------------------------


def test_quem_esta_na_escala_no_dia_sem_quem_sai_sem_repetidos_e_sem_quem_nao_tem_conta(tmp_path):
    # 27/10 (terça), o mês SEM filtro de loja: Emily em Alfragide, Walisson em Algueirão e Joana
    # em Amadora (por loja seria Emily, Walisson, Joana; sai por nome). Uma ida da Emily às 17–18
    # parte-lhe a escala em duas linhas (fica a primeira); o Zé está na escala de Alfragide mas
    # não tem conta no RH (user_id null), por isso não se troca; a ida da Débora não é escala.
    dados = sn.semana_normal()
    dados["empregados"].append({"id": "e-ze", "name": "Zé", "location_id": sn.ALFRAGIDE, "company_id": sn.FORDAIMON})
    dados["atribuicoes"].append({"id": "a-ze", "employee_id": "e-ze", "template_id": "m-emily",
                                 "work_days": [1], "start_date": "2026-01-01", "end_date": None})
    dados["idas"] = [sn.ida("2026-10-27", sn.ALFRAGIDE, sn.user("Emily"), "17:00", "18:00"),
                     sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")]
    mes = calendario.resposta_do_mes(2026, 10, dados, sn.DEBORA, True)
    na_escala = [(p["nome"], p["user_id"]) for l in next(d for d in mes["dias"] if d["data"] == "2026-10-27")["lojas"]
                 for p in l["pessoas"] if p["origem"] == "escala"]
    assert ("Zé", None) in na_escala and na_escala.count(("Emily", "u-emily")) == 2      # o cenário é o que se diz
    todos, sem_emily, fora = _cal(
        tmp_path, "[cal.escaladosDoDia(D, '2026-10-27', null), cal.escaladosDoDia(D, '2026-10-27', 'u-emily'), "
                  "cal.escaladosDoDia(D, '2026-12-01', null)]", mes)
    emily = {"user_id": "u-emily", "nome": "Emily", "location_id": sn.ALFRAGIDE, "loja": "Alfragide",
             "inicio": "14:00", "fim": "17:00", "turno_inteiro": False}
    joana = {"user_id": "u-joana", "nome": "Joana", "location_id": sn.AMADORA, "loja": "Amadora",
             "inicio": "14:00", "fim": "23:00", "turno_inteiro": True}
    walisson = {"user_id": "u-walisson", "nome": "Walisson", "location_id": sn.ALGUEIRAO, "loja": "Algueirão",
                "inicio": "13:00", "fim": "22:00", "turno_inteiro": True}
    assert todos == [emily, joana, walisson]
    assert sem_emily == [joana, walisson]
    assert fora == []


def _entrada(acao, antes=(), depois=(), datas=None):
    retratos = list(antes) + list(depois)
    return {"id": "h1", "quando": "2026-10-20T13:32:00+00:00", "quem_id": sn.CAROL, "quem_nome": "Carol Santos",
            "acao": acao, "datas": datas or sorted({r["data"] for r in retratos}),
            "antes": list(antes), "depois": list(depois)}


def _retrato(data, loja, nome, inicio, fim, no_lugar_de=None):
    return {"data": data, "loja": loja, "nome": nome, "inicio": inicio, "fim": fim, "no_lugar_de": no_lugar_de}


def test_as_linhas_do_historico_das_seis_accoes(tmp_path):
    dias = ["2026-10-06", "2026-10-13", "2026-10-20"]
    entradas = [
        _entrada("marcou", depois=[_retrato(d, "Oeiras", n, "13:00", "22:00")
                                   for d in dias for n in ("Débora Ferreira", "Carol Santos")]),
        _entrada("alterou", [_retrato("2026-10-27", "Alfragide", "Débora Ferreira", "10:00", "14:00")],
                 [_retrato("2026-10-28", "Oeiras", "Débora Ferreira", "13:00", "22:00")]),
        _entrada("alterou", [_retrato("2026-10-27", "Alfragide", "Débora Ferreira", "10:00", "14:00")],
                 [_retrato("2026-10-27", "Alfragide", "Carol Santos", "10:00", "14:00")]),
        _entrada("apagou", [_retrato("2026-10-27", "Loja Alfragide", "Débora Ferreira", "10:00", "14:00")]),
        _entrada("trocou", depois=[_retrato("2026-10-27", "Alfragide", "Beatrice", "14:00", "23:00", "Emily")]),
        _entrada("trocou entre si", depois=[_retrato("2026-10-27", "Amadora", "Emily", "14:00", "23:00", "Joana"),
                                            _retrato("2026-10-27", "Alfragide", "Joana", "14:00", "23:00", "Emily")]),
        _entrada("desfez a troca", [_retrato("2026-10-27", "Alfragide", "Beatrice", "14:00", "23:00", "Emily")]),
        _entrada("desfez a troca", [_retrato("2026-10-27", "Amadora", "Emily", "14:00", "23:00", "Joana"),
                                    _retrato("2026-10-27", "Alfragide", "Joana", "14:00", "23:00", "Emily")]),
        _entrada("trocou", depois=[_retrato("2026-10-27", "Alfragide", "Beatrice", "14:00", "23:00",
                                            "(conta removida)")]),
    ]
    r = _cal(tmp_path, "D.map(cal.linhaDoHistorico)", entradas)
    assert r == [
        "20/10 às 14:32 · Carol · marcou Débora e Carol em Oeiras, 13h–22h · 6/10, 13/10, 20/10",
        "20/10 às 14:32 · Carol · alterou a ida de Débora: Alfragide 10h–14h, 27/10 → Oeiras 13h–22h, 28/10",
        "20/10 às 14:32 · Carol · alterou a ida de Débora: Alfragide 10h–14h, 27/10 → Carol em Alfragide 10h–14h, 27/10",
        "20/10 às 14:32 · Carol · apagou a ida de Débora em Alfragide, 10h–14h · 27/10",
        "20/10 às 14:32 · Carol · trocou Emily por Beatrice em Alfragide, 14h–23h · 27/10",
        "20/10 às 14:32 · Carol · trocou Emily (Alfragide) com Joana (Amadora) · 27/10",
        "20/10 às 14:32 · Carol · desfez a troca de Emily por Beatrice em Alfragide · 27/10",
        "20/10 às 14:32 · Carol · desfez a troca de Emily (Alfragide) com Joana (Amadora) · 27/10",
        "20/10 às 14:32 · Carol · trocou (conta removida) por Beatrice em Alfragide, 14h–23h · 27/10",
    ]


def test_um_lote_grande_no_historico_mostra_os_primeiros_dias_e_quantos_faltam(tmp_path):
    dias = ["2026-10-%02d" % d for d in range(1, 32)]
    lote = _entrada("marcou", depois=[_retrato(d, "Oeiras", n, "13:00", "22:00")
                                      for d in dias for n in ("Débora Ferreira", "Carol Santos")])
    assert _cal(tmp_path, "cal.linhaDoHistorico(D)", lote) == (
        "20/10 às 14:32 · Carol · marcou Débora e Carol em Oeiras, 13h–22h · 1/10, 2/10, 3/10 e mais 28")
