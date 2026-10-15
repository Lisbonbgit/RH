"""O ecrã do Calendário (`pages/bolso/BolsoCalendario.js`) MONTADO num DOM, com o servidor
fabricado à frente do axios e o relógio parado na terça, 27/10/2026, às 10:00 de Lisboa.

A resposta fabricada não é escrita à mão: sai do `calendario.resposta_do_mes` — o mesmo
código que o servidor corre — sobre a semana normal. Se o servidor mudar a forma da
resposta, é aqui que o ecrã fica vermelho (a lição do voucher ao balcão: duas suites verdes
por cima de um contrato partido).
"""
import json
import re

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


def _ecra(tmp_path, cenario, mes, contagem=(), falha=None, antes=""):
    return correr_js("\n".join([
        "pararRelogio(2026, 10, 27, 10, 0);",
        antes,
        "const MES = %s;" % json.dumps(mes, ensure_ascii=False),
        "const CONTAGEM = %s;" % json.dumps(list(contagem), ensure_ascii=False),
        "const FALHA = %s;" % json.dumps(falha),
        "global.SERVIDOR = (metodo, url) => {",
        "  if (metodo === 'GET' && url === '/calendario') return FALHA ? { erro: FALHA } : MES;",
        "  if (metodo === 'GET' && url === '/calendario/contagem') return CONTAGEM;",
        "  return {};",
        "};",
        "const BolsoCalendario = importar('pages/bolso/BolsoCalendario').default;",
        "await montar(React.createElement(BolsoCalendario));",
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


def test_a_vista_e_o_filtro_lembram_se_e_sem_localstorage_abre_em_mes_geral(tmp_path):
    mes, _ = _servidor()
    lembrado = _ecra(
        tmp_path, "devolve([botao('Lista').getAttribute('aria-pressed'), botao('Férias').getAttribute('aria-pressed')]);",
        mes, antes="localStorage.setItem('bolso_cal_vista', 'lista'); localStorage.setItem('bolso_cal_filtro', 'ferias');")
    assert lembrado == ["true", "true"]
    sem = _ecra(
        tmp_path, "devolve([botao('Mês').getAttribute('aria-pressed'), botao('Geral').getAttribute('aria-pressed')]);",
        mes, antes="Object.defineProperty(global, 'localStorage', { get() { throw new Error('modo privado'); }, configurable: true });")
    assert sem == ["true", "true"]


def test_sessao_expirada_sai_para_o_login(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, "devolve(REGISTO.filter((x) => x[0] !== 'GET'));", mes, falha={"response": {"status": 401}})
    assert r == [["logout"], ["navigate", "/login"]]


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


def test_sessao_expirada_ao_gravar_no_painel_sai_para_o_login(tmp_path):
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
    assert r == [["logout"], ["navigate", "/login"]]


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
    for caminho in destinos:
        rota = re.compile(r'<Route path="%s" element=\{\s*<ProtectedRoute allowedRoles=\{\[\'admin\', '
                          r'\'gerente\', \'contabilista\'\]\}>' % re.escape(caminho))
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
