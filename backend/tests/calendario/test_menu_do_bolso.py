"""O menu lateral (☰) da Gestão Lisbonb, montado a sério (jsdom) dentro da Faturação, e as
peças que os dois ecrãs do bolso passam a partilhar (desenho, secção 4)."""
import json

from tests.bolso_js import AXIOS_FABRICADO, SESSAO_SIMULADA, correr_js

PAINEL = {"hoje": "2026-10-27",
          "ambito": {"pedido": "all", "unidade": None, "somadas": [{"id": "c1", "nome": "Fordaimon Foods"}],
                     "sem_acesso": [], "unidades": []},
          "cartoes": {}, "serie_dias": [], "serie_meses": [], "reparticao": [], "reparticao_por": "empresa",
          "dias_sem_vendas": [], "leituras": []}


def _faturacao(tmp_path, cenario):
    """Monta o `BolsoApp` com o servidor fabricado a responder ao painel e corre `cenario`."""
    return correr_js("\n".join([
        "const PAINEL = %s;" % json.dumps(PAINEL),
        "global.SERVIDOR = (metodo, url) => (url === '/painel' ? PAINEL : {});",
        "const BolsoApp = importar('pages/bolso/BolsoApp').default;",
        "await montar(React.createElement(BolsoApp));",
        "await esperar();",
        cenario,
    ]), tmp_path, simulados=dict(SESSAO_SIMULADA, axios=AXIOS_FABRICADO), dom=True)


def test_o_menu_abre_com_faturacao_calendario_e_terminar_sessao(tmp_path):
    r = _faturacao(tmp_path, """
const antes = !!document.querySelector('[role="dialog"]');
await clicar(botao('Abrir menu'));
const menu = document.querySelector('[role="dialog"]');
devolve({
  antes,
  titulo: menu.querySelector('h2').textContent,
  itens: [...menu.querySelectorAll('nav button')].map((b) => b.textContent.trim()),
  actual: menu.querySelector('[aria-current="page"]').textContent.trim(),
  sair: [...menu.querySelectorAll('button')].some((b) => b.textContent.includes('Terminar sessão')),
  fechoGrande: botao('Fechar menu', menu).className.includes('h-11 w-11'),
  fechoPequeno: [...menu.querySelectorAll('.sr-only')].some((s) => s.textContent === 'Close'),
});
""")
    assert r == {"antes": False, "titulo": "Gestão Lisbonb", "itens": ["Faturação", "Calendário"],
                 "actual": "Faturação", "sair": True, "fechoGrande": True, "fechoPequeno": False}


def test_tocar_no_calendario_fecha_o_menu_e_navega(tmp_path):
    r = _faturacao(tmp_path, """
await clicar(botao('Abrir menu'));
await clicar(botao('Calendário', document.querySelector('[role="dialog"]')));
devolve({ aberto: !!document.querySelector('[role="dialog"]'), registo: REGISTO.filter((x) => x[0] === 'navigate') });
""")
    assert r == {"aberto": False, "registo": [["navigate", "/bolso/calendario"]]}


def test_terminar_sessao_sai_e_vai_para_o_login(tmp_path):
    r = _faturacao(tmp_path, """
await clicar(botao('Abrir menu'));
await clicar([...document.querySelectorAll('[role="dialog"] button')].find((b) => b.textContent.includes('Terminar sessão')));
devolve(REGISTO.filter((x) => x[0] !== 'GET'));
""")
    assert r == [["logout"], ["navigate", "/login"]]


def test_a_faturacao_continua_igual_por_baixo(tmp_path):
    """O que saiu do BolsoApp para o partilhado.js (o Segmento e a calha) continua a desenhar
    a barra das empresas; e o «Terminar sessão» do fundo passou para o menu (um sítio só)."""
    r = _faturacao(tmp_path, """
devolve({
  grupo: botao('Grupo').getAttribute('aria-pressed'),
  empresa: botao('Fordaimon').getAttribute('aria-pressed'),
  sairNoFundo: [...document.querySelectorAll('main button')].some((b) => b.textContent.includes('Terminar sessão')),
  titulo: document.title,
});
""")
    assert r == {"grupo": "true", "empresa": "false", "sairNoFundo": False, "titulo": "Gestão Lisbonb"}


def test_o_sheet_por_omissao_continua_a_desenhar_o_seu_fecho(tmp_path):
    r = correr_js("""
const S = importar('components/ui/sheet');
await montar(React.createElement(S.Sheet, { open: true },
  React.createElement(S.SheetContent, null, React.createElement(S.SheetTitle, null, 'Outro ecrã'))));
devolve([...document.querySelectorAll('[role="dialog"] .sr-only')].map((s) => s.textContent));
""", tmp_path, dom=True)
    assert r == ["Close"]


def test_ler_e_guardar_aguentam_um_localstorage_que_rebenta(tmp_path):
    r = correr_js("""
Object.defineProperty(global, 'localStorage', { get() { throw new Error('modo privado'); }, configurable: true });
const { ler, guardar } = importar('pages/bolso/partilhado');
guardar('x', '1');
devolve(ler('x', 'por omissão'));
""", tmp_path, simulados=SESSAO_SIMULADA, dom=True)
    assert r == "por omissão"
