"""As trocas no ecrã do Calendário (desenho das trocas, §3): o `BolsoCalendario` montado num DOM
com o servidor fabricado, o mês calculado pelo `calendario.resposta_do_mes` e o relógio parado
na terça, 27/10/2026. Nesse dia a Emily está em Alfragide 14h–23h, a Joana na Amadora 14h–23h e
o Walisson no Algueirão 13h–22h; a Beatrice e o Weber estão de folga.
"""
import json

import pytest

import calendario

from . import dados_semana_normal as sn
from .test_ecra_do_calendario import _ecra

EMILY, BEATRICE, JOANA, WALISSON = (sn.user(n) for n in ("Emily", "Beatrice", "Joana", "Walisson"))


def troca(user_id, loja, sai, troca_id, inicio="14:00", fim="23:00"):
    return dict(sn.ida("2026-10-27", loja, user_id, inicio, fim), troca_id=troca_id, no_lugar_de_emp=sn.emp(sai))


def _mes(eu=sn.DEBORA, pode_trocar=True, idas=(), dados=None, mes=10):
    dados = dados or sn.semana_normal()
    dados["idas"] = list(idas)
    return calendario.resposta_do_mes(2026, mes, dados, eu, True, pode_trocar)


# A linha de uma pessoa numa loja do dia (Mês, Geral) e o diálogo aberto.
AJUDAS = """
const linhaDe = (loja, nome) => [...[...document.querySelectorAll('main li')]
  .find((li) => li.querySelector('span').textContent === loja).children].find((el) => el.textContent.startsWith(nome));
const dlg = () => document.querySelector('[role="dialog"]');
const botoes = (rotulo) => [...dlg().querySelectorAll('button')].filter((b) => b.textContent.trim() === rotulo);
const pessoa = (nome) => [...dlg().querySelectorAll('fieldset button')].find((b) => b.textContent.startsWith(nome));
"""


# Na Semana (a vista por omissão, `None`: nada guardado; a semana de hoje, 26/10 a 1/11, pede
# também novembro) e no Mês: o toque na linha da escala tem de estar provado nas duas.
@pytest.mark.parametrize("vista", [None, "mes"])
def test_a_linha_da_escala_so_e_botao_para_admin_e_so_com_conta(tmp_path, vista):
    ler = AJUDAS + """
const forma = (el) => [el.tagName, el.getAttribute('aria-label')];
devolve([forma(linhaDe('Alfragide', 'Emily')), forma(linhaDe('Algueirão', 'Walisson'))]);
"""
    sem_conta = sn.semana_normal()
    sem_conta["utilizadores"] = [u for u in sem_conta["utilizadores"] if u["id"] != WALISSON]
    def _abrir(**kw):
        return _ecra(tmp_path, ler, _mes(**kw), novembro=_mes(mes=11, **kw), vista=vista)

    assert _abrir(dados=sem_conta) == [["BUTTON", "Trocar Emily, 14h–23h"], ["DIV", None]]
    # O gerente marca idas mas não troca: a mesma linha é texto.
    assert _abrir(eu=sn.GERENTE, pode_trocar=False) == [["DIV", None], ["DIV", None]]


def test_outra_pessoa_avisa_quem_esta_na_escala_noutra_loja_e_envia_a_troca(tmp_path):
    mes = _mes()
    r = _ecra(tmp_path, AJUDAS + """
await clicar(linhaDe('Alfragide', 'Emily'));
const painel = {
  titulo: dlg().querySelector('h2').textContent, subtitulo: dlg().querySelector('h2 + p').textContent,
  segmentos: ['Outra pessoa', 'Trocar turnos'].map((s) => botoes(s)[0]?.getAttribute('aria-pressed')),
  pessoas: [...dlg().querySelectorAll('fieldset button')].map((b) => b.textContent),
  inicio: dlg().querySelector('[aria-label="Hora de início"]').value,
  fim: dlg().querySelector('[aria-label="Hora de fim"]').value,
  semPessoa: botoes('Trocar')[0].disabled,
};
await clicar(pessoa('Beatrice'));
await escrever(dlg().querySelector('[aria-label="Hora de fim"]'), '18:00');
await clicar(botoes('Trocar')[0]);
await esperar();
devolve({ painel, aberto: !!dlg(), pedidos: REGISTO.map((x) => [x[0], x[1], x[2]]) });
""", mes)
    na_escala = {"Joana": "na escala em Amadora 14h–23h", "Walisson": "na escala em Algueirão 13h–22h"}
    assert r["painel"] == {
        "titulo": "Trocar Emily", "subtitulo": "terça, 27 de outubro · Alfragide",
        "segmentos": ["true", "false"],
        "pessoas": [p["nome"] + na_escala.get(p["nome"], "") for p in mes["pessoas"] if p["id"] != EMILY],
        "inicio": "14:00", "fim": "23:00", "semPessoa": True}
    assert r["aberto"] is False
    assert r["pedidos"] == [
        ["GET", "/calendario", None],
        ["POST", "/calendario/trocas",
         {"data": "2026-10-27", "sai": EMILY, "entra": BEATRICE, "inicio": "14:00", "fim": "18:00"}],
        ["GET", "/calendario", None]]


def test_o_aviso_da_escala_e_so_para_quem_esta_noutra_loja(tmp_path):
    # Sexta, 30/10: a Beatrice está na MESMA loja da Emily (Alfragide 10h–19h), sem aviso; a
    # Rafaela está em Belém.
    r = _ecra(tmp_path, AJUDAS + """
await clicar(document.querySelector('[data-dia="2026-10-30"]'));
await clicar(linhaDe('Alfragide', 'Emily'));
devolve(['Beatrice', 'Rafaela'].map((n) => pessoa(n).textContent));
""", _mes())
    assert r == ["Beatrice", "Rafaelana escala em Belém 11h30–19h"]


def test_trocar_turnos_lista_quem_esta_na_escala_e_envia_as_duas_pessoas(tmp_path):
    r = _ecra(tmp_path, AJUDAS + """
await clicar(linhaDe('Alfragide', 'Emily'));
await clicar(botoes('Trocar turnos')[0]);
const opcoes = [...dlg().querySelectorAll('fieldset button')].map((b) => b.textContent);
const horas = !!dlg().querySelector('[aria-label="Hora de início"]');
await clicar(pessoa('Joana'));
await clicar(botoes('Trocar turnos').pop());
await esperar();
devolve({ opcoes, horas, aberto: !!dlg(), pedidos: REGISTO.filter((x) => x[0] === 'POST').map((x) => [x[1], x[2]]) });
""", _mes())
    assert r == {"opcoes": ["JoanaAmadora 14h–23h", "WalissonAlgueirão 13h–22h"], "horas": False, "aberto": False,
                 "pedidos": [["/calendario/trocas/entre-si", {"data": "2026-10-27", "uma": EMILY, "outra": JOANA}]]}


def test_trocar_turnos_so_aparece_quando_a_linha_e_o_turno_inteiro_mesmo_com_o_filtro_de_loja(tmp_path):
    # Uma ida da Emily no Algueirão parte-lhe o dia em duas linhas (noutra loja: com o filtro em
    # Alfragide não se vê, e conta na mesma). Trocar os turnos levava o turno inteiro dela.
    cenario = AJUDAS + """
await clicar(linhaDe('Alfragide', 'Emily'));
devolve({ outra: botoes('Outra pessoa').length, turnos: botoes('Trocar turnos').length });
"""
    filtro = "localStorage.setItem('bolso_cal_loja', %s);" % json.dumps(sn.ALFRAGIDE)
    assert _ecra(tmp_path, cenario, _mes(), antes=filtro) == {"outra": 1, "turnos": 1}
    partido = _mes(idas=[sn.ida("2026-10-27", sn.ALGUEIRAO, EMILY, "13:00", "14:00")])
    assert _ecra(tmp_path, cenario, partido, antes=filtro) == {"outra": 0, "turnos": 0}


# A Débora (admin) no lugar da Emily em Alfragide e o Guilherme (gerente) no lugar da Joana na
# Amadora, a 27/10.
TROCAS = [troca(sn.DEBORA, sn.ALFRAGIDE, "Emily", "t-1"), troca(sn.GERENTE, sn.AMADORA, "Joana", "t-2")]
LER_AS_TROCAS = """
const trocas = () => [...document.querySelectorAll('main span')].filter((s) => s.textContent.startsWith('no lugar de'))
  .map((s) => { const linha = s.closest('.min-h-11'); return [linha.tagName, linha.textContent]; });
const vistas = {};
vistas.dia = trocas();
await clicar(botao('Pessoal'));
vistas.pessoal = trocas();
await clicar(botao('Lista'));
vistas.listaPessoal = trocas();
await clicar(botao('Geral'));
vistas.lista = trocas();
"""


def test_a_troca_aparece_no_lugar_de_no_dia_na_lista_e_no_pessoal(tmp_path):
    r = _ecra(tmp_path, AJUDAS + """
await clicar(linhaDe('Alfragide', 'Débora'));
const painel = { titulo: dlg().querySelector('h2').textContent, guardar: botoes('Guardar').length,
                 desfazer: botoes('Desfazer a troca').length, duas: dlg().textContent.includes('apaga as duas') };
await clicar(botao('Fechar', dlg()));
""" + LER_AS_TROCAS + "devolve({ painel, vistas });", _mes(idas=TROCAS))
    assert r["painel"] == {"titulo": "Troca", "guardar": 0, "desfazer": 1, "duas": False}
    debora = "no lugar de Emily14h–23htroca"
    guilherme = "no lugar de Joana14h–23htroca"
    assert r["vistas"] == {
        "dia": [["BUTTON", "Débora Ferreira" + debora], ["BUTTON", "Guilherme Gestor" + guilherme]],
        "pessoal": [["BUTTON", "Alfragide" + debora]],
        "listaPessoal": [["BUTTON", "Alfragide" + debora]],
        "lista": [["BUTTON", "Débora Ferreira · Alfragide" + debora], ["BUTTON", "Guilherme Gestor · Amadora" + guilherme]],
    }


def test_o_gerente_ve_a_troca_como_texto(tmp_path):
    r = _ecra(tmp_path, LER_AS_TROCAS + "devolve(vistas);", _mes(eu=sn.GERENTE, pode_trocar=False, idas=TROCAS))
    assert r == {
        "dia": [["DIV", "Débora Ferreirano lugar de Emily14h–23htroca"], ["DIV", "Guilherme Gestorno lugar de Joana14h–23htroca"]],
        "pessoal": [["DIV", "Amadorano lugar de Joana14h–23htroca"]],
        "listaPessoal": [["DIV", "Amadorano lugar de Joana14h–23htroca"]],
        "lista": [["DIV", "Débora Ferreira · Alfragideno lugar de Emily14h–23htroca"],
                  ["DIV", "Guilherme Gestor · Amadorano lugar de Joana14h–23htroca"]],
    }


def test_desfazer_uma_troca_entre_si_pede_dois_toques_e_apaga_as_duas(tmp_path):
    entre_si = [troca(EMILY, sn.AMADORA, "Joana", "t-3"), troca(JOANA, sn.ALFRAGIDE, "Emily", "t-3")]
    r = _ecra(tmp_path, AJUDAS + """
await clicar(linhaDe('Alfragide', 'Joana'));
const painel = { titulo: dlg().querySelector('h2').textContent,
                 idas: [...dlg().querySelectorAll('li')].map((li) => li.textContent),
                 duas: dlg().textContent.includes('Desfazer apaga as duas.') };
await clicar(botoes('Desfazer a troca')[0]);
const depoisDoPrimeiro = { apagou: REGISTO.some((x) => x[0] === 'DELETE'), botao: botoes('Tocar de novo para desfazer').length };
await clicar(botoes('Tocar de novo para desfazer')[0]);
await esperar();
devolve({ painel, depoisDoPrimeiro, aberto: !!dlg(), pedidos: REGISTO.map((x) => x[0] + ' ' + x[1]) });
""", _mes(idas=entre_si))
    assert r == {
        "painel": {"titulo": "Troca", "duas": True,
                   "idas": ["Emily no lugar de JoanaAmadora · 14h–23h", "Joana no lugar de EmilyAlfragide · 14h–23h"]},
        "depoisDoPrimeiro": {"apagou": False, "botao": 1},
        "aberto": False,
        "pedidos": ["GET /calendario", "DELETE /calendario/trocas/t-3", "GET /calendario"]}


RECUSAR_A_TROCA = """
const servidorDoMes = global.SERVIDOR;
global.SERVIDOR = (metodo, url, ...resto) => (metodo === 'POST'
  ? { erro: %s } : servidorDoMes(metodo, url, ...resto));
"""
TROCAR_EMILY_POR_BEATRICE = AJUDAS + """
await clicar(linhaDe('Alfragide', 'Emily'));
await clicar(pessoa('Beatrice'));
await clicar(botoes('Trocar')[0]);
await esperar();
"""


def test_uma_recusa_do_servidor_aparece_no_painel_tal_como_vem(tmp_path):
    frase = "Já há uma troca para Emily a 27/10 (Beatrice)."
    r = _ecra(tmp_path, TROCAR_EMILY_POR_BEATRICE + """
devolve({ alerta: dlg().querySelector('[role="alert"]').textContent, livre: !botoes('Trocar')[0].disabled,
          leituras: REGISTO.filter((x) => x[0] === 'GET').length });
""", _mes(), antes=RECUSAR_A_TROCA % json.dumps({"response": {"status": 409, "data": {"detail": frase}}}))
    assert r == {"alerta": frase, "livre": True, "leituras": 1}


def test_sessao_expirada_ao_trocar_so_faz_logout(tmp_path):
    r = _ecra(tmp_path, TROCAR_EMILY_POR_BEATRICE + """
devolve(REGISTO.filter((x) => x[0] === 'logout' || x[0] === 'navigate'));
""", _mes(), antes=RECUSAR_A_TROCA % json.dumps({"response": {"status": 401}}))
    assert r == [["logout"]]


def test_quem_entra_com_ausencia_aprovada_depois_da_troca_diz_troca_e_extra(tmp_path):
    # Regra B: a troca fica até uma admin a desfazer, mas a loja não pode parecer coberta por
    # alguém de férias — a etiqueta diz as duas coisas.
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Beatrice", "2026-10-27", "2026-10-27"))
    r = _ecra(tmp_path, AJUDAS + "devolve(linhaDe('Alfragide', 'Beatrice').textContent);",
              _mes(dados=dados, idas=[troca(BEATRICE, sn.ALFRAGIDE, "Emily", "t-1")]))
    assert r == "Beatriceno lugar de Emily14h–23htroca · extra"


def test_a_metade_que_sobra_de_uma_troca_nao_mostra_trocar_turnos(tmp_path):
    # A Beatrice no lugar da Emily das 14h às 18h: a Emily fica das 18h às 23h, que não é o
    # turno inteiro dela (o servidor recusava os turnos com 409). Outra pessoa continua.
    r = _ecra(tmp_path, AJUDAS + """
await clicar(linhaDe('Alfragide', 'Emily'));
devolve({ titulo: dlg().querySelector('h2').textContent, turnos: botoes('Trocar turnos').length,
          horas: [dlg().querySelector('[aria-label="Hora de início"]').value, dlg().querySelector('[aria-label="Hora de fim"]').value] });
""", _mes(idas=[troca(BEATRICE, sn.ALFRAGIDE, "Emily", "t-1", "14:00", "18:00")]))
    assert r == {"titulo": "Trocar Emily", "turnos": 0, "horas": ["18:00", "23:00"]}


def test_trocar_turnos_nao_lista_o_colega_igual_nem_quem_tem_o_turno_partido(tmp_path):
    # Sexta, 30/10, a Emily em Alfragide 14h–23h. A Joana passa para Alfragide 14h–23h (a mesma
    # loja e as mesmas horas: a troca não mudava nada, 400) e a Carol fica no lugar do Weber na
    # Amadora das 14h às 18h (o Weber fica com 18h–23h, que não é o turno inteiro dele, 409). A
    # Beatrice está na mesma loja com outras horas: essa troca-se.
    dados = sn.semana_normal()
    sexta_joana = next(d for d in next(m for m in dados["modelos"] if m["id"] == "m-joana")["dias"] if d["dia"] == 4)
    sexta_joana.update(location_id=sn.ALFRAGIDE, inicio="14:00", fim="23:00")
    carol = dict(sn.ida("2026-10-30", sn.AMADORA, sn.CAROL, "14:00", "18:00"), troca_id="t-1", no_lugar_de_emp=sn.emp("Weber"))
    r = _ecra(tmp_path, AJUDAS + """
await clicar(document.querySelector('[data-dia="2026-10-30"]'));
await clicar(linhaDe('Alfragide', 'Emily'));
await clicar(botoes('Trocar turnos')[0]);
devolve([...dlg().querySelectorAll('fieldset button')].map((b) => b.textContent));
""", _mes(dados=dados, idas=[carol]))
    assert r == ["BeatriceAlfragide 10h–19h", "EmanuelaOeiras 13h–22h", "RafaelaBelém 11h30–19h"]
