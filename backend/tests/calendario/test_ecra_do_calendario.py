"""O ecrã do Calendário (`pages/bolso/BolsoCalendario.js`) MONTADO num DOM, com o servidor
fabricado à frente do axios e o relógio parado na terça, 27/10/2026, às 10:00 de Lisboa.

A resposta fabricada não é escrita à mão: sai do `calendario.resposta_do_mes` — o mesmo
código que o servidor corre — sobre a semana normal. Se o servidor mudar a forma da
resposta, é aqui que o ecrã fica vermelho (a lição do voucher ao balcão: duas suites verdes
por cima de um contrato partido).
"""
import copy
import json
import re

import pytest

import calendario
from tests.bolso_js import AXIOS_FABRICADO, SESSAO_SIMULADA, SRC, correr_js

from . import dados_semana_normal as sn

IDAS_DA_DEBORA = [sn.ida("2026-10-06", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                  sn.ida("2026-10-13", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")]


def _servidor(eu=sn.DEBORA, pode_marcar=True):
    dados = sn.semana_normal()
    dados["idas"] = list(IDAS_DA_DEBORA)
    mes = calendario.resposta_do_mes(2026, 10, dados, eu, pode_marcar)
    contagem = calendario.contagem(dados["idas"], {l["id"]: l for l in dados["lojas"]},
                                   {u["id"]: u["name"] for u in dados["utilizadores"]})
    return mes, contagem


def _semana(dados=None, idas=IDAS_DA_DEBORA):
    """Outubro E novembro, do mesmo `dados`: a semana de hoje (26/10 a 1/11) atravessa os dois."""
    dados = dados or sn.semana_normal()
    dados["idas"] = list(idas)
    return [calendario.resposta_do_mes(2026, m, dados, sn.DEBORA, True) for m in (10, 11)]


def _ecra(tmp_path, cenario, mes, contagem=(), falha=None, antes="", novembro=None, vista="mes"):
    # `vista`: a vista guardada antes de abrir. Os testes do Mês guardam «mes»; com None não há
    # nada guardado e o ecrã abre na Semana. Um mês sem resposta aqui falha à vista (500).
    return correr_js("\n".join([
        "pararRelogio(2026, 10, 27, 10, 0);",
        "const MESES = { 10: %s, 11: %s };" % (json.dumps(mes, ensure_ascii=False),
                                               json.dumps(novembro, ensure_ascii=False)),
        "const CONTAGEM = %s;" % json.dumps(list(contagem), ensure_ascii=False),
        "const FALHA = %s;" % json.dumps(falha),
        "global.SERVIDOR = (metodo, url, corpo, params) => {",
        "  if (metodo === 'GET' && url === '/calendario') {",
        "    if (FALHA) return { erro: FALHA };",
        "    return MESES[params.mes] || { erro: { response: { status: 500, data: { detail: 'Sem o mês ' + params.mes } } } };",
        "  }",
        "  if (metodo === 'GET' && url === '/calendario/contagem') return CONTAGEM;",
        "  return {};",
        "};",
        "localStorage.setItem('bolso_cal_vista', %s);" % json.dumps(vista) if vista else "",
        antes,       # depois do servidor: pode embrulhá-lo (segurar uma resposta)
        "const BolsoCalendario = importar('pages/bolso/BolsoCalendario').default;",
        "const raiz = await montar(React.createElement(BolsoCalendario));",   # para recarregar o ecrã
        "await esperar();",
        cenario,
    ]), tmp_path, simulados=dict(SESSAO_SIMULADA, axios=AXIOS_FABRICADO), dom=True)


BURACOS_DO_DIA = """
const buracos = [...document.querySelectorAll('main [data-buraco]')].map((b) => ({
  loja: b.closest('li').querySelector('span').textContent,
  tipo: b.getAttribute('data-buraco'),
  texto: b.querySelector('span').textContent,
  vermelho: b.classList.contains('bg-destructive-strong') && b.classList.contains('text-white'),
  amarelo: b.classList.contains('bg-warning/15') && b.classList.contains('text-warning-strong'),
}));
const tapar = [...document.querySelectorAll('main button')].filter((b) => b.textContent.trim() === 'Tapar').length;
"""


def test_abre_no_dia_de_hoje_com_os_buracos_a_vermelho_e_a_amarelo(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, BURACOS_DO_DIA + """
devolve({
  mes: document.querySelector('h1').textContent,
  dia: document.querySelector('main h2').textContent,
  hoje: document.querySelector('[data-dia="2026-10-27"]').getAttribute('aria-pressed'),
  buracos, tapar,
  belem: [...document.querySelectorAll('main li')].some((li) => li.textContent === 'Belémfechada'),
  marcar: !!botao('Marcar ida'),
  pedidos: REGISTO,
});
""", mes)
    assert (r["mes"], r["dia"], r["hoje"]) == ("outubro 2026", "terça, 27 de outubro", "true")
    assert r["buracos"] == [
        {"loja": "Alfragide", "tipo": "falta", "texto": "falta 10h–14h", "vermelho": False, "amarelo": True},
        {"loja": "Benfica", "tipo": "ninguem", "texto": "ninguém", "vermelho": True, "amarelo": False},
        {"loja": "Oeiras", "tipo": "ninguem", "texto": "ninguém", "vermelho": True, "amarelo": False}]
    assert (r["tapar"], r["belem"], r["marcar"]) == (3, True, True)
    assert r["pedidos"] == [["GET", "/calendario", None, {"ano": 2026, "mes": 10}]]


def test_quem_le_sem_poder_marcar_nao_ve_tapar_nem_marcar(tmp_path):
    mes, _ = _servidor(eu=sn.CONTABILISTA, pode_marcar=False)
    r = _ecra(tmp_path, BURACOS_DO_DIA + "devolve({ tapar, buracos: buracos.length, marcar: !!botao('Marcar ida') });", mes)
    assert r == {"tapar": 0, "buracos": 3, "marcar": False}


def test_os_pontos_da_grelha_e_os_feriados(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const ponto = (d) => !!document.querySelector('[data-dia="' + d + '"] [data-ponto]');
const dia = (d) => document.querySelector('[data-dia="' + d + '"]');
const geral = { d05: ponto('2026-10-05'), d02: ponto('2026-10-02') };
await clicar(botao('Pessoal'));
const pessoal = { d06: ponto('2026-10-06'), d05: ponto('2026-10-05') };
devolve({ geral, pessoal, feriado: /warning-strong/.test(dia('2026-10-05').className),
          altura: dia('2026-10-05').className.includes('h-11'), celulas: document.querySelectorAll('[data-dia]').length });
""", mes)
    assert r == {"geral": {"d05": True, "d02": False}, "pessoal": {"d06": True, "d05": False},
                 "feriado": True, "altura": True, "celulas": 31}


def test_tocar_num_dia_mostra_o_e_o_pessoal_mostra_as_minhas_idas(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
await clicar(document.querySelector('[data-dia="2026-10-06"]'));
await clicar(botao('Pessoal'));
const cartao = [...document.querySelectorAll('main section')].pop();
devolve({ dia: cartao.querySelector('h2').textContent,
          linhas: [...cartao.querySelectorAll('button')].map((b) => b.textContent) });
""", mes)
    assert r == {"dia": "terça, 6 de outubro", "linhas": ["Oeiras13h–22h"]}


def test_a_lista_comeca_hoje(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
await clicar(botao('Lista'));
devolve([...document.querySelectorAll('main h2')].map((h) => h.textContent).slice(0, 2));
""", mes)
    assert r == ["terça, 27 de outubro", "quarta, 28 de outubro"]


def test_a_contagem_mostra_o_mes_e_o_ano_e_abre_os_meses(tmp_path):
    mes, contagem = _servidor()
    r = _ecra(tmp_path, """
await clicar(botao('Contagem'));
await esperar();
const linha = document.querySelector('main li button');
const primeira = linha.textContent.trim();
await clicar(linha);
devolve({ primeira, meses: document.querySelectorAll('main ol li').length, filtros: !!botao('Geral'),
          pedidos: REGISTO.map((x) => x[1]) });
""", mes, contagem)
    assert r == {"primeira": "Débora · outubro 2 dias · 2026 2 dias", "meses": 12, "filtros": False,
                 "pedidos": ["/calendario", "/calendario/contagem"]}


def test_a_vista_e_o_filtro_lembram_se_e_sem_localstorage_abre_em_semana_geral(tmp_path):
    outubro, novembro = _semana()
    lembrado = _ecra(
        tmp_path, "devolve([botao('Lista').getAttribute('aria-pressed'), botao('Férias').getAttribute('aria-pressed')]);",
        outubro, vista="lista", antes="localStorage.setItem('bolso_cal_filtro', 'ferias');")
    assert lembrado == ["true", "true"]
    sem = _ecra(
        tmp_path, "devolve([botao('Semana').getAttribute('aria-pressed'), botao('Geral').getAttribute('aria-pressed')]);",
        outubro, novembro=novembro, vista=None,
        antes="Object.defineProperty(global, 'localStorage', { get() { throw new Error('modo privado'); }, configurable: true });")
    assert sem == ["true", "true"]


def test_um_401_que_chega_ao_ecra_so_faz_logout(tmp_path):
    """Fase 3: o `lib/bolso.js` já tentou a re-entrada pelo Face ID. Não se navega à mão:
    o ProtectedRoute leva ao login com o `state.from` e, depois de entrar, volta-se aqui."""
    mes, _ = _servidor()
    r = _ecra(tmp_path, "devolve(REGISTO.filter((x) => x[0] !== 'GET'));", mes, falha={"response": {"status": 401}})
    assert r == [["logout"]]


def test_tapar_abre_com_as_horas_do_buraco_e_marcar_abre_vazio(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const lerPainel = () => {
  const dlg = document.querySelector('[role="dialog"]');
  return { titulo: dlg.querySelector('h2').textContent, loja: dlg.querySelector('[aria-label="Loja"]').value,
           inicio: dlg.querySelector('[aria-label="Hora de início"]').value,
           fim: dlg.querySelector('[aria-label="Hora de fim"]').value,
           dias: [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')) };
};
const alfragide = [...document.querySelectorAll('main [data-buraco]')]
  .find((b) => b.closest('li').querySelector('span').textContent === 'Alfragide');
await clicar(botao('Tapar', alfragide));
const tapar = lerPainel();
await clicar(botao('Fechar', document.querySelector('[role="dialog"]')));
await clicar(botao('Marcar ida'));
devolve({ tapar, marcar: lerPainel() });
""", mes)
    assert r == {
        "tapar": {"titulo": "Tapar Alfragide", "loja": sn.ALFRAGIDE, "inicio": "10:00", "fim": "14:00",
                  "dias": ["2026-10-27"]},
        # Desenho, secção 4: «o mesmo painel vazio, com a loja a escolher» (as horas vêm da
        # loja que se escolher — prova-se no painel, Tarefa 12).
        "marcar": {"titulo": "Marcar ida", "loja": "", "inicio": "", "fim": "", "dias": ["2026-10-27"]}}


def test_sessao_expirada_ao_gravar_no_painel_so_faz_logout(tmp_path):
    """Fase 3: como nos pedidos do ecrã, só `logout()`; o ProtectedRoute leva ao login com
    o `state.from`."""
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const oeiras = [...document.querySelectorAll('main [data-buraco]')]
  .find((b) => b.closest('li').querySelector('span').textContent === 'Oeiras');
await clicar(botao('Tapar', oeiras));
global.SERVIDOR = () => ({ erro: { response: { status: 401, data: { detail: 'Token expirado' } } } });
await clicar(botao('Marcar 1 ida', document.querySelector('[role="dialog"]')));
await esperar();
devolve(REGISTO.filter((x) => x[0] === 'logout' || x[0] === 'navigate'));
""", mes)
    assert r == [["logout"]]


def test_depois_de_gravar_o_painel_fecha_e_o_mes_volta_a_ler_se(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const oeiras = [...document.querySelectorAll('main [data-buraco]')]
  .find((b) => b.closest('li').querySelector('span').textContent === 'Oeiras');
await clicar(botao('Tapar', oeiras));
await clicar(botao('Marcar 1 ida', document.querySelector('[role="dialog"]')));
await esperar();
devolve({ aberto: !!document.querySelector('[role="dialog"]'), pedidos: REGISTO.map((x) => x[0] + ' ' + x[1]) });
""", mes)
    assert r == {"aberto": False, "pedidos": ["GET /calendario", "POST /calendario/idas", "GET /calendario"]}


# A linha da ida da Débora em Oeiras, a 6/10 (Geral), e o que se vê depois de lhe tocar.
TOCAR_NA_IDA_DE_OEIRAS = """
await clicar(document.querySelector('[data-dia="2026-10-06"]'));
const oeiras = [...document.querySelectorAll('main li')].find((li) => li.querySelector('span').textContent === 'Oeiras');
const linha = [...oeiras.children].find((el) => el.textContent.startsWith('Débora'));
const forma = { tag: linha.tagName, texto: linha.textContent };
await clicar(linha);
const dlg = document.querySelector('[role="dialog"]');
"""


def test_tocar_numa_ida_abre_a_ida_dessa_pessoa_e_nao_a_de_quem_ve(tmp_path):
    # Desenho, secção 4: «Tocar numa ida abre o painel com Guardar e Apagar». Quem vê é a
    # Carol e a ida é da Débora: se o ecrã não passar a pessoa da ida ao painel, ele abre em
    # quem vê e o «Guardar» passa a ida para a Carol sem aviso. (Com a Débora a ver, cair
    # nela por omissão dava o mesmo resultado e a falta não se via.)
    mes, _ = _servidor(eu=sn.CAROL)
    r = _ecra(tmp_path, TOCAR_NA_IDA_DE_OEIRAS + """
const painel = { titulo: dlg.querySelector('h2').textContent, loja: dlg.querySelector('[aria-label="Loja"]').value,
                 inicio: dlg.querySelector('[aria-label="Hora de início"]').value,
                 fim: dlg.querySelector('[aria-label="Hora de fim"]').value,
                 dias: [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')),
                 pessoas: [...dlg.querySelectorAll('fieldset button[aria-pressed="true"]')].map((b) => b.textContent),
                 apagar: !!botao('Apagar', dlg) };
await clicar(botao('Guardar', dlg));
await esperar();
devolve({ forma, painel, gravado: REGISTO.filter((x) => x[0] === 'PUT') });
""", mes)
    assert r == {
        "forma": {"tag": "BUTTON", "texto": "Débora Ferreira13h–22hida"},
        "painel": {"titulo": "Ida de Débora Ferreira", "loja": sn.OEIRAS, "inicio": "13:00", "fim": "22:00",
                   "dias": ["2026-10-06"], "pessoas": ["Débora Ferreira"], "apagar": True},
        "gravado": [["PUT", "/calendario/idas/" + IDAS_DA_DEBORA[0]["id"],
                     {"data": "2026-10-06", "location_id": sn.OEIRAS, "user_id": sn.DEBORA,
                      "inicio": "13:00", "fim": "22:00"}, None]]}
    # Quem só lê (o contabilista) vê a mesma linha como texto: não abre nada.
    mes, _ = _servidor(eu=sn.CONTABILISTA, pode_marcar=False)
    r = _ecra(tmp_path, TOCAR_NA_IDA_DE_OEIRAS + "devolve({ forma, aberto: !!dlg });", mes)
    assert r == {"forma": {"tag": "DIV", "texto": "Débora Ferreira13h–22hida"}, "aberto": False}


def test_cada_destino_do_menu_e_uma_rota_do_app_com_os_papeis_do_bolso(tmp_path):
    destinos = correr_js("devolve(importar('pages/bolso/partilhado').DESTINOS.map((d) => d.caminho));",
                         tmp_path, simulados=SESSAO_SIMULADA, dom=True)
    assert destinos == ["/bolso", "/bolso/calendario"]
    app = (SRC / "App.js").read_text(encoding="utf-8")
    # Fase 3: as rotas do bolso passam pelo `RotaDoBolso`, que leva os papéis (e a Barreira).
    corpo = app[app.index("const RotaDoBolso"):]
    corpo = corpo[:corpo.index(");")]
    assert "<ProtectedRoute allowedRoles={['admin', 'gerente', 'contabilista']}>" in corpo
    for caminho in destinos:
        rota = re.compile(r'<Route path="%s" element=\{\s*<RotaDoBolso>' % re.escape(caminho))
        assert rota.search(app), "O App.js não tem a rota %s com os papéis do bolso." % caminho


def test_duas_pessoas_sem_conta_a_mesma_hora_na_mesma_loja_aparecem_as_duas(tmp_path):
    # A chave das linhas era `${user_id}-${inicio}`: duas pessoas da escala sem conta no RH
    # (user_id null) a entrar à mesma hora repetiam-na («same key» no stderr do React).
    dados = sn.semana_normal()
    dados["utilizadores"] = [u for u in dados["utilizadores"] if u["id"] != sn.user("Emanuela")]
    dados["empregados"].append({"id": "e-ze", "name": "Zé", "location_id": sn.OEIRAS, "company_id": sn.FORDAIMON})
    dados["atribuicoes"].append({"id": "a-ze", "employee_id": "e-ze", "template_id": "m-emanuela",
                                 "work_days": [0, 3, 4, 5, 6], "start_date": "2026-01-01", "end_date": None})
    mes = calendario.resposta_do_mes(2026, 10, dados, sn.DEBORA, True)
    r = _ecra(tmp_path, """
await clicar(document.querySelector('[data-dia="2026-10-26"]'));
const oeiras = [...document.querySelectorAll('main li')].find((li) => li.querySelector('span').textContent === 'Oeiras');
devolve([...oeiras.children].slice(1).map((el) => el.textContent));
""", mes)
    assert r == ["Emanuela13h–22hescala", "Zé13h–22hescala"]


def test_sem_nenhuma_loja_com_horario_o_dia_diz_onde_se_define_e_nao_ha_marcar(tmp_path):
    # Antes do arranque (ou se o horário se tirar a todas): o cartão do dia ficava em branco e
    # o «Marcar ida» abria um painel com o seletor de loja vazio.
    dados = sn.semana_normal()
    for loja in dados["lojas"]:
        loja["horario"] = None
    mes = calendario.resposta_do_mes(2026, 10, dados, sn.DEBORA, True)
    assert mes["lojas"] == []
    r = _ecra(tmp_path, """
devolve({ dia: [...document.querySelectorAll('main section')].pop().textContent, marcar: !!botao('Marcar ida') });
""", mes)
    assert r == {"dia": "terça, 27 de outubroAinda nenhuma loja tem horário. Defina-o em Locais, no portal.",
                 "marcar": False}



# O 1.º pedido da contagem fica seguro até `soltar(...)`; os seguintes respondem já.
SEGURAR_A_PRIMEIRA_CONTAGEM = """
const servidor = global.SERVIDOR;
let soltar = null;
global.SERVIDOR = (metodo, url, ...resto) => {
  if (url === '/calendario/contagem' && !soltar) return new Promise((ok) => { soltar = ok; });
  return servidor(metodo, url, ...resto);
};
"""
LER_A_CONTAGEM = """
const lido = { linha: (document.querySelector('main li button') || {}).textContent || null,
               alerta: !!document.querySelector('[role="alert"]'),
               pedidos: REGISTO.filter((x) => x[1] === '/calendario/contagem').length };
"""


@pytest.mark.parametrize("o_que_chega_tarde", [
    "[]",                                                                        # a contagem velha
    "{ erro: { response: { status: 500, data: { detail: 'Falhou a contagem velha' } } } }",
])
def test_a_contagem_que_chega_atrasada_nao_pisa_a_mais_recente(tmp_path, o_que_chega_tarde):
    # Como o mês: cada pedido leva um número e só o último escreve no ecrã (resposta ou erro).
    mes, contagem = _servidor()
    r = _ecra(tmp_path, """
await clicar(botao('Contagem'));
await esperar();
await clicar(botao('Mês'));
await clicar(botao('Contagem'));
await esperar();
await act(async () => { soltar(%s); });
await esperar();
""" % o_que_chega_tarde + LER_A_CONTAGEM + "devolve(lido);", mes, contagem, antes=SEGURAR_A_PRIMEIRA_CONTAGEM)
    assert r == {"linha": "Débora · outubro 2 dias · 2026 2 dias", "alerta": False, "pedidos": 2}


def test_o_erro_da_contagem_sai_ao_pedir_de_novo(tmp_path):
    mes, contagem = _servidor()
    r = _ecra(tmp_path, """
await clicar(botao('Contagem'));
await esperar();
await act(async () => { soltar({ erro: { response: { status: 500, data: { detail: 'Falhou' } } } }); });
await esperar();
const antes = !!document.querySelector('[role="alert"]');
await clicar(botao('Mês'));
await clicar(botao('Contagem'));
await esperar();
""" + LER_A_CONTAGEM + "devolve({ antes, ...lido });", mes, contagem, antes=SEGURAR_A_PRIMEIRA_CONTAGEM)
    assert r == {"antes": True, "linha": "Débora · outubro 2 dias · 2026 2 dias", "alerta": False, "pedidos": 2}


# --- A Semana: as lojas em linhas, os 7 dias em colunas (adenda de 2026-10-15) ---------------

# A grelha tal como se vê: o cabeçalho e, por loja, o texto de cada célula.
LER_A_SEMANA = """
const celula = (loja, dia) => document.querySelector('main [data-loja="' + loja + '"] [data-celula="' + dia + '"]');
const grelha = () => [...document.querySelectorAll('main [data-loja]')].map((linha) => [
  linha.firstElementChild.textContent, [...linha.querySelectorAll('[data-celula]')].map((c) => c.textContent)]);
const cabecalho = () => [...document.querySelectorAll('main [data-cabecalho] span')].map((s) => s.textContent).filter(Boolean);
const escolhidos = () => [...new Set([...document.querySelectorAll('main [data-celula][aria-pressed="true"]')]
  .map((c) => c.getAttribute('data-celula')))];
const titulo = () => document.querySelector('h1').textContent;
const lerBuracos = () => [...document.querySelectorAll('main [data-buraco]')].map((b) => [
  b.closest('li').querySelector('span').textContent, b.querySelector('span').textContent]);
"""

# A semana normal de 26/10 a 1/11 (desenho, «A semana normal»): Alfragide sem ninguém das 10 às
# 14 (Emily só às 14, seg/ter) e das 19 às 23 (Beatrice sai às 19, qua/qui); Belém fecha à
# terça; Benfica abriu a 24/10 e ainda não tem escala; Oeiras sem ninguém à terça. O domingo,
# 1/11, vem da resposta de NOVEMBRO e é Todos os Santos: no feriado a escala não põe ninguém
# (decisão do dono, 2026-10-16), por isso todas as lojas abertas ficam «—».
GRELHA_DE_26_OUT = [
    ["Alfragide", ["10h–14h", "10h–14h", "19h–23h", "19h–23h", "ok", "ok", "—"]],
    ["Algueirão", ["ok"] * 6 + ["—"]],
    ["Amadora", ["ok"] * 6 + ["—"]],
    ["Belém", ["ok", "fech.", "ok", "ok", "ok", "ok", "—"]],
    ["Benfica", ["—"] * 7],
    ["Oeiras", ["ok", "—", "ok", "ok", "ok", "ok", "—"]],
]


def test_a_semana_abre_por_omissao_com_a_grelha_das_lojas(tmp_path):
    outubro, novembro = _semana()
    r = _ecra(tmp_path, LER_A_SEMANA + """
const celulas = [...document.querySelectorAll('main [data-celula]')];
devolve({ semana: botao('Semana').getAttribute('aria-pressed'), titulo: titulo(), cabecalho: cabecalho(),
          grelha: grelha(), escolhidos: escolhidos(),
          botoes: celulas.every((c) => c.tagName === 'BUTTON' && c.classList.contains('h-11')),
          setas: [!!botao('Semana anterior'), !!botao('Semana seguinte'), !!botao('Mês anterior')],
          dia: document.querySelector('main h2').textContent, buracos: lerBuracos(),
          marcar: !!botao('Marcar ida'), pedidos: REGISTO.map((x) => [x[1], x[3]]) });
""", outubro, novembro=novembro, vista=None)
    assert (r["semana"], r["titulo"]) == ("true", "26 out – 1 nov")
    assert r["cabecalho"] == ["S 26", "T 27", "Q 28", "Q 29", "S 30", "S 31", "D 1"]
    assert r["grelha"] == GRELHA_DE_26_OUT
    assert (r["escolhidos"], r["botoes"], r["setas"]) == (["2026-10-27"], True, [True, True, False])
    # Por baixo, a agenda de hoje — a mesma do Mês, com Tapar.
    assert r["dia"] == "terça, 27 de outubro"
    assert r["buracos"] == [["Alfragide", "falta 10h–14h"], ["Benfica", "ninguém"], ["Oeiras", "ninguém"]]
    assert r["marcar"] is True
    assert r["pedidos"] == [["/calendario", {"ano": 2026, "mes": 10}], ["/calendario", {"ano": 2026, "mes": 11}]]


def test_as_setas_da_semana_andam_sete_dias_e_pedem_os_meses_da_semana(tmp_path):
    outubro, novembro = _semana()
    r = _ecra(tmp_path, LER_A_SEMANA + """
const passos = [];
const passo = () => passos.push([titulo(), REGISTO.splice(0).map((x) => x[3].mes)]);
passo();
await clicar(botao('Semana anterior')); await esperar(); passo();
await clicar(botao('Semana seguinte')); await esperar(); passo();
const voltou = grelha();
await clicar(botao('Semana seguinte')); await esperar(); passo();
// O dia escolhido é um só: passou a 3/11, toca-se no 5/11, e o Mês abre em novembro com ele.
await clicar(celula('loja-oeiras', '2026-11-05'));
await clicar(botao('Mês')); await esperar(); passo();
const noMes = document.querySelector('[data-dia][aria-pressed="true"]').getAttribute('data-dia');
const setas = [!!botao('Mês anterior'), !!botao('Semana anterior')];
// No Mês as setas continuam a andar um mês (e voltar a outubro escolhe hoje).
await clicar(botao('Mês anterior')); await esperar(); passo();
devolve({ passos, voltou, noMes, setas,
          depois: document.querySelector('[data-dia][aria-pressed="true"]').getAttribute('data-dia') });
""", outubro, novembro=novembro, vista=None)
    assert r["passos"] == [["26 out – 1 nov", [10, 11]], ["19 – 25 out", [10]], ["26 out – 1 nov", [10, 11]],
                           ["2 – 8 nov", [11]], ["novembro 2026", []], ["outubro 2026", [10]]]
    assert r["voltou"] == GRELHA_DE_26_OUT
    # (7 dias antes do 5/11 era o 29/10: aqui volta-se um MÊS, para hoje.)
    assert (r["noMes"], r["setas"], r["depois"]) == ("2026-11-05", [True, False], "2026-10-27")


def test_tocar_numa_celula_mostra_esse_dia_por_baixo_e_tapa_com_o_mes_dele(tmp_path):
    outubro, novembro = _semana()
    r = _ecra(tmp_path, LER_A_SEMANA + """
await clicar(celula('loja-alfragide', '2026-10-29'));
const quinta = { dia: document.querySelector('main h2').textContent, escolhidos: escolhidos(), buracos: lerBuracos() };
await clicar(celula('loja-belem', '2026-11-01'));
const domingo = { dia: document.querySelector('main h2').textContent, escolhidos: escolhidos(), buracos: lerBuracos(),
                  titulo: titulo() };
await clicar(botao('Tapar', document.querySelector('main [data-buraco]')));
const dlg = document.querySelector('[role="dialog"]');
devolve({ quinta, domingo, painel: { titulo: dlg.querySelector('h2').textContent,
  loja: dlg.querySelector('[aria-label="Loja"]').value, inicio: dlg.querySelector('[aria-label="Hora de início"]').value,
  dias: [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')) } });
""", outubro, novembro=novembro, vista=None)
    assert r["quinta"] == {"dia": "quinta, 29 de outubro", "escolhidos": ["2026-10-29"],
                           "buracos": [["Alfragide", "falta 19h–23h"], ["Benfica", "ninguém"]]}
    # Tocar na linha de Belém escolhe o DIA (a agenda mostra todas as lojas); o 1/11 é de novembro
    # e é feriado (Todos os Santos): a escala não põe ninguém, todas as lojas ficam sem ninguém.
    assert r["domingo"] == {"dia": "domingo, 1 de novembro", "escolhidos": ["2026-11-01"],
                            "buracos": [[l, "ninguém"] for l in ("Alfragide", "Algueirão", "Amadora", "Belém",
                                                                  "Benfica", "Oeiras")],
                            "titulo": "26 out – 1 nov"}
    # O painel (o primeiro Tapar, Alfragide) abre na grelha de NOVEMBRO com o 1/11 escolhido (com
    # a de outubro, o dia não estava lá).
    assert r["painel"] == {"titulo": "Tapar Alfragide", "loja": sn.ALFRAGIDE, "inicio": "10:00", "dias": ["2026-11-01"]}


def test_o_pessoal_da_semana_mostra_so_as_horas_das_minhas_idas(tmp_path):
    outubro, novembro = _semana(idas=IDAS_DA_DEBORA + [sn.ida("2026-10-14", sn.OEIRAS, sn.CAROL, "13:00", "22:00")])
    r = _ecra(tmp_path, LER_A_SEMANA + """
await clicar(botao('Semana anterior')); await esperar();
await clicar(botao('Semana anterior')); await esperar();
await clicar(botao('Pessoal'));
const cheias = [...document.querySelectorAll('main [data-celula]')].filter((c) => c.textContent)
  .map((c) => [c.closest('[data-loja]').getAttribute('data-loja'), c.getAttribute('data-celula'), c.textContent]);
devolve({ titulo: titulo(), linhas: grelha().length, cheias, dia: document.querySelector('main h2').textContent });
""", outubro, novembro=novembro, vista=None)
    # A ida da Carol a 14/10 e as escalas não são minhas: só a minha ida de 13/10 tem horas.
    assert r == {"titulo": "12 – 18 out", "linhas": 6, "cheias": [[sn.OEIRAS, "2026-10-13", "13h–22h"]],
                 "dia": "terça, 13 de outubro"}


def test_as_ferias_da_semana_sao_a_lista_das_ausencias_que_tocam_a_semana(tmp_path):
    dados = sn.semana_normal()
    dados["ausencias"] = [sn.ausencia("Emanuela", "2026-10-15", "2026-10-15"),
                          sn.ausencia("Rafaela", "2026-10-20", "2026-10-26"),
                          sn.ausencia("Weber", "2026-10-30", "2026-11-02")]
    outubro, novembro = _semana(dados)
    r = _ecra(tmp_path, """
await clicar(botao('Férias'));
const cartao = document.querySelector('main section');
devolve({ celulas: document.querySelectorAll('main [data-celula]').length, titulo: cartao.querySelector('h2').textContent,
          linhas: [...cartao.querySelectorAll('p.font-semibold')].map((p) => p.parentElement.textContent),
          marcar: !!botao('Marcar ida') });
""", outubro, novembro=novembro, vista=None)
    # Sem grelha; a Emanuela (15/10) fica de fora; o Weber vem nos dois meses e aparece uma vez.
    assert r == {"celulas": 0, "titulo": "Ausências da semana",
                 "linhas": ["Rafaela · Férias20/10–26/10 · Belém", "Weber · Férias30/10–02/11 · Amadora"],
                 "marcar": True}


def test_enquanto_falta_um_dos_meses_a_semana_fica_em_esqueleto(tmp_path):
    # Na semana de 19/10 o ecrã já tem outubro; ao voltar à de 26/10 falta só novembro (seguro).
    outubro, novembro = _semana()
    r = _ecra(tmp_path, LER_A_SEMANA + """
await clicar(botao('Semana anterior')); await esperar();
segurar = true;
await clicar(botao('Semana seguinte')); await esperar();
const antes = { titulo: titulo(), celulas: document.querySelectorAll('main [data-celula]').length,
                esqueleto: [...document.querySelectorAll('main div[aria-hidden="true"]')]
                  .some((d) => d.className.includes('animate-pulse')), marcar: !!botao('Marcar ida'),
                lojas: !!document.querySelector('[aria-label="Filtro de loja"]') };
await act(async () => { soltar(MESES[11]); });
await esperar();
devolve({ antes, depois: grelha() });
""", outubro, novembro=novembro, vista=None, antes="""
const servidor = global.SERVIDOR;
let segurar = false;
let soltar = null;
global.SERVIDOR = (metodo, url, corpo, params) => {
  if (segurar && url === '/calendario' && params.mes === 11) {
    segurar = false;
    return new Promise((ok) => { soltar = ok; });
  }
  return servidor(metodo, url, corpo, params);
};
""")
    # As pastilhas das lojas ficam (vêm da última leitura): o cabeçalho não salta a cada semana.
    assert r == {"antes": {"titulo": "26 out – 1 nov", "celulas": 0, "esqueleto": True, "marcar": False, "lojas": True},
                 "depois": GRELHA_DE_26_OUT}


def _outubro_velho(outubro):
    """Outubro com outra cara (todas as lojas tapadas): se ele chegar ao ecrã, vê-se."""
    velho = copy.deepcopy(outubro)
    for dia in velho["dias"]:
        for loja in dia["lojas"]:
            loja["buracos"] = []
    return velho


@pytest.mark.parametrize("o_que_chega_tarde", ["velho", "erro"])
def test_a_resposta_atrasada_de_outra_semana_nao_pisa_a_actual(tmp_path, o_que_chega_tarde):
    # Como no Mês: cada pedido leva um número e só o último escreve no ecrã. O pedido de
    # outubro da semana de 19/10 fica seguro; volta-se à de 26/10 e só depois ele chega.
    outubro, novembro = _semana()
    tarde = (_outubro_velho(outubro) if o_que_chega_tarde == "velho"
             else {"erro": {"response": {"status": 500, "data": {"detail": "Falhou a semana velha"}}}})
    r = _ecra(tmp_path, LER_A_SEMANA + """
await clicar(botao('Semana anterior')); await esperar();
await clicar(botao('Semana seguinte')); await esperar();
const antes = grelha();
await act(async () => { soltar(%s); });
await esperar();
devolve({ antes, depois: grelha(), titulo: titulo(), alerta: !!document.querySelector('[role="alert"]'),
          pedidos: REGISTO.map((x) => x[3].mes) });
""" % json.dumps(tarde, ensure_ascii=False), outubro, novembro=novembro, vista=None, antes="""
const servidor = global.SERVIDOR;
let soltar = null;
let outubros = 0;
global.SERVIDOR = (metodo, url, corpo, params) => {
  if (url === '/calendario' && params.mes === 10 && ++outubros === 2) return new Promise((ok) => { soltar = ok; });
  return servidor(metodo, url, corpo, params);
};
""")
    assert r == {"antes": GRELHA_DE_26_OUT, "depois": GRELHA_DE_26_OUT, "titulo": "26 out – 1 nov", "alerta": False,
                 "pedidos": [10, 11, 10, 10, 11]}


# --- O filtro de loja: «Todas | Alfragide | …» por baixo das vistas (adenda de 2026-10-15) ----

FILA_DE_LOJAS = """
const fila = () => document.querySelector('[aria-label="Filtro de loja"]');
const pastilha = (nome) => botao(nome, fila());
const escolhida = () => [...fila().querySelectorAll('button[aria-pressed="true"]')].map((b) => b.textContent);
const pontos = () => [...document.querySelectorAll('main [data-dia]')].filter((d) => d.querySelector('[data-ponto]'))
  .map((d) => d.getAttribute('data-dia').slice(8));
"""
LER_O_PAINEL = """
const lerPainel = () => {
  const dlg = document.querySelector('[role="dialog"]');
  return { titulo: dlg.querySelector('h2').textContent, loja: dlg.querySelector('[aria-label="Loja"]').value,
           opcoes: dlg.querySelectorAll('[aria-label="Loja"] option').length,
           inicio: dlg.querySelector('[aria-label="Hora de início"]').value,
           fim: dlg.querySelector('[aria-label="Hora de fim"]').value,
           dias: [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')) };
};
const fecharPainel = () => clicar(botao('Fechar', document.querySelector('[role="dialog"]')));
"""
# Uma ida que tapa Alfragide (29/10) e outra a mais em Oeiras (30/10): na Lista de Oeiras só fica a de Oeiras.
IDAS_DO_FILTRO = IDAS_DA_DEBORA + [sn.ida("2026-10-29", sn.ALFRAGIDE, sn.CAROL, "19:00", "23:00"),
                                  sn.ida("2026-10-30", sn.OEIRAS, sn.CAROL, "13:00", "17:00")]
GRELHA_DE_OEIRAS = [["Oeiras", ["ok", "—", "ok", "ok", "ok", "ok", "—"]]]   # 1/11 é feriado: ninguém


def test_escolher_uma_loja_deixa_so_essa_loja_na_semana_no_mes_e_na_lista(tmp_path):
    dados = sn.semana_normal()
    # Em produção as lojas chamam-se «Loja Oeiras»: a pastilha (e a linha da Semana) dizem só «Oeiras».
    next(l for l in dados["lojas"] if l["id"] == sn.OEIRAS)["name"] = "Loja Oeiras"
    outubro, novembro = _semana(dados, idas=IDAS_DO_FILTRO)
    r = _ecra(tmp_path, LER_A_SEMANA + FILA_DE_LOJAS + """
const pastilhas = [...fila().querySelectorAll('button')].map((b) => [b.textContent, b.getAttribute('aria-pressed')]);
const forma = { altas: [...fila().querySelectorAll('button')].every((b) => b.classList.contains('h-11')),
                desliza: fila().classList.contains('overflow-x-auto') };
await clicar(pastilha('Oeiras'));
const semana = { escolhida: escolhida(), grelha: grelha(), buracos: lerBuracos(),
                 guardada: localStorage.getItem('bolso_cal_loja') };
await clicar(botao('Mês')); await esperar();
const mes = { escolhida: escolhida(), pontos: pontos(), buracos: lerBuracos() };
await clicar(botao('Lista'));
devolve({ pastilhas, forma, semana, mes, lista: [...document.querySelectorAll('main section')].map((s) => s.textContent) });
""", outubro, novembro=novembro, vista=None)
    assert r["pastilhas"] == [["Todas", "true"], ["Alfragide", "false"], ["Algueirão", "false"], ["Amadora", "false"],
                              ["Belém", "false"], ["Benfica", "false"], ["Oeiras", "false"]]
    # 44 px de alto; a fila desliza para o lado sozinha (a página não).
    assert r["forma"] == {"altas": True, "desliza": True}
    assert r["semana"] == {"escolhida": ["Oeiras"], "grelha": GRELHA_DE_OEIRAS,
                           "buracos": [["Loja Oeiras", "ninguém"]], "guardada": sn.OEIRAS}
    # Sem o filtro, o Mês tinha pontos em 21 dias (Alfragide e Benfica): Oeiras só falta às terças por
    # tapar e a 05/10, feriado (a escala não põe ninguém).
    assert r["mes"] == {"escolhida": ["Oeiras"], "pontos": ["05", "20", "27"], "buracos": [["Loja Oeiras", "ninguém"]]}
    assert r["lista"] == ["terça, 27 de outubroLoja Oeiras13h–22hninguémTapar",
                          "sexta, 30 de outubroCarol Santos · Loja Oeiras13h–17h"]


def test_nas_ferias_ficam_so_as_ausencias_de_quem_tem_a_loja_na_ficha(tmp_path):
    dados = sn.semana_normal()
    dados["ausencias"] = [sn.ausencia("Emanuela", "2026-10-29", "2026-10-30"),   # ficha em Oeiras
                          sn.ausencia("Rafaela", "2026-10-20", "2026-10-26"),    # Belém
                          sn.ausencia("Weber", "2026-10-30", "2026-11-02"),      # Amadora
                          sn.ausencia("Joana", "2026-10-28", "2026-10-28")]      # Algueirão (às quartas vai a Oeiras)
    outubro, novembro = _semana(dados)
    r = _ecra(tmp_path, FILA_DE_LOJAS + """
const linhas = () => [...document.querySelectorAll('main p.font-semibold')].map((p) => p.textContent);
await clicar(botao('Férias'));
const todas = linhas();
await clicar(pastilha('Oeiras'));
const semana = linhas();
await clicar(botao('Mês')); await esperar();
devolve({ todas, semana, pontos: pontos() });
""", outubro, novembro=novembro, vista=None)
    assert r["todas"] == ["Rafaela · Férias", "Joana · Férias", "Emanuela · Férias", "Weber · Férias"]
    # Desenho: «ausências de quem tem essa loja na ficha» — a Joana trabalha em Oeiras à quarta, mas a ficha é de Algueirão.
    assert (r["semana"], r["pontos"]) == (["Emanuela · Férias"], ["29", "30"])


def test_a_loja_lembra_se_ao_recarregar_e_uma_que_ja_nao_existe_volta_a_todas(tmp_path):
    outubro, novembro = _semana()
    r = _ecra(tmp_path, LER_A_SEMANA + FILA_DE_LOJAS + """
await clicar(pastilha('Oeiras'));
await act(async () => { raiz.unmount(); });
await montar(React.createElement(BolsoCalendario));
await esperar();
const recarregado = { escolhida: escolhida(), grelha: grelha() };
await clicar(pastilha('Todas'));
devolve({ recarregado, todas: { escolhida: escolhida(), linhas: grelha().length,
                                guardada: localStorage.getItem('bolso_cal_loja') } });
""", outubro, novembro=novembro, vista=None)
    assert r == {"recarregado": {"escolhida": ["Oeiras"], "grelha": GRELHA_DE_OEIRAS},
                 "todas": {"escolhida": ["Todas"], "linhas": 6, "guardada": None}}
    # Uma loja guardada que entretanto saiu do calendário (perdeu o horário, fechou) conta como «Todas».
    r = _ecra(tmp_path, LER_A_SEMANA + FILA_DE_LOJAS + "devolve({ escolhida: escolhida(), grelha: grelha() });",
              outubro, novembro=novembro, vista=None, antes="localStorage.setItem('bolso_cal_loja', 'loja-que-fechou');")
    assert r == {"escolhida": ["Todas"], "grelha": GRELHA_DE_26_OUT}


def test_a_pastilha_escolhida_e_levada_a_vista_ao_abrir_e_ao_mudar(tmp_path):
    # Medido no browser a 375 px: com «Oeiras» (a última) guardada, a fila abria no início — via-se
    # «Todas» sem destaque e a escolhida escondida à direita. O jsdom não tem `scrollIntoView`:
    # espia-se e regista-se em que pastilha foi chamado e com que opções.
    outubro, novembro = _semana()
    r = _ecra(tmp_path, FILA_DE_LOJAS + """
const ao_abrir = vistas.splice(0);
await clicar(pastilha('Belém'));
devolve({ ao_abrir, ao_mudar: vistas.splice(0),
          sem_barra: fila().classList.contains('[scrollbar-width:none]')
                     && fila().classList.contains('[&::-webkit-scrollbar]:hidden') });
""", outubro, novembro=novembro, vista=None, antes="""
localStorage.setItem('bolso_cal_loja', %s);
const vistas = [];
window.Element.prototype.scrollIntoView = function (opcoes) { vistas.push([this.textContent, opcoes]); };
""" % json.dumps(sn.OEIRAS))
    # `block: 'nearest'`: só a fila desliza para o lado; a página não salta na vertical.
    assert r == {"ao_abrir": [["Oeiras", {"block": "nearest", "inline": "center"}]],
                 "ao_mudar": [["Belém", {"block": "nearest", "inline": "center"}]],
                 "sem_barra": True}


def test_com_uma_loja_escolhida_marcar_abre_nela_e_tapar_e_editar_continuam(tmp_path):
    outubro, novembro = _semana()
    r = _ecra(tmp_path, FILA_DE_LOJAS + LER_O_PAINEL + """
await clicar(pastilha('Oeiras'));
await clicar(botao('Marcar ida'));
const marcar = lerPainel();
await fecharPainel();
await clicar(pastilha('Belém'));
await clicar(botao('Marcar ida'));
const fechada = lerPainel();
await fecharPainel();
await clicar(pastilha('Oeiras'));
await clicar(botao('Tapar', document.querySelector('main [data-buraco]')));
const tapar = lerPainel();
await fecharPainel();
await clicar(botao('Mês')); await esperar();
await clicar(document.querySelector('main [data-dia="2026-10-06"]'));
await clicar([...document.querySelectorAll('main li button')].find((b) => b.textContent.startsWith('Débora')));
devolve({ marcar, fechada, tapar, editar: lerPainel() });
""", outubro, novembro=novembro, vista=None)
    # As horas são as da loja no dia, como ao escolhê-la no painel; o painel continua a ter as 6 lojas.
    assert r["marcar"] == {"titulo": "Marcar ida", "loja": sn.OEIRAS, "opcoes": 6, "inicio": "13:00", "fim": "22:00",
                           "dias": ["2026-10-27"]}
    # Belém fecha à terça: a loja vem escolhida e as horas vazias (no painel também não as enche).
    assert r["fechada"] == {"titulo": "Marcar ida", "loja": sn.BELEM, "opcoes": 6, "inicio": "", "fim": "",
                            "dias": ["2026-10-27"]}
    assert r["tapar"] == {"titulo": "Tapar Oeiras", "loja": sn.OEIRAS, "opcoes": 6, "inicio": "13:00", "fim": "22:00",
                          "dias": ["2026-10-27"]}
    assert r["editar"] == {"titulo": "Ida de Débora Ferreira", "loja": sn.OEIRAS, "opcoes": 6, "inicio": "13:00",
                           "fim": "22:00", "dias": ["2026-10-06"]}


def test_a_contagem_nao_tem_filtro_de_loja(tmp_path):
    mes, contagem = _servidor()
    r = _ecra(tmp_path, FILA_DE_LOJAS + """
await clicar(pastilha('Alfragide'));
await clicar(botao('Contagem')); await esperar();
devolve({ fila: !!fila(), linha: document.querySelector('main li button').textContent });
""", mes, contagem)
    # As idas da Débora são em Oeiras e continuam a contar com «Alfragide» escolhida.
    assert r == {"fila": False, "linha": "Débora · outubro 2 dias · 2026 2 dias"}
