"""O ajudante que corre JavaScript do frontend em Node (`tests/bolso_js.py`)."""
import pytest

from tests.bolso_js import AXIOS_FABRICADO, correr_js


def test_corre_um_modulo_verdadeiro_do_frontend(tmp_path):
    # `cn` é o twMerge(clsx(...)) de lib/utils.js: o px-4 ganha ao px-2.
    assert correr_js("devolve(importar('lib/utils').cn('px-2 text-sm', 'px-4'));", tmp_path) == "text-sm px-4"


def test_um_modulo_simulado_chega_aos_modulos_do_frontend(tmp_path):
    r = correr_js("devolve(importar('lib/utils').cn('a', 'b'));", tmp_path,
                  simulados={"tailwind-merge": "({ twMerge: (s) => 'simulado:' + s })"})
    assert r == "simulado:a b"


def test_o_axios_fabricado_regista_o_pedido_e_devolve_a_resposta(tmp_path):
    r = correr_js(
        "global.SERVIDOR = (metodo, url, corpo, params) => ({ eco: [metodo, url, params] });\n"
        "const { getPainel } = importar('lib/bolso');\n"
        "const { data } = await getPainel('c1', 'u1');\n"
        "devolve({ data, registo: REGISTO });",
        tmp_path, simulados={"axios": AXIOS_FABRICADO})
    params = {"empresa": "c1", "unidade": "u1"}
    assert r == {"data": {"eco": ["GET", "/painel", params]}, "registo": [["GET", "/painel", None, params]]}


def test_com_dom_monta_o_sheet_do_radix_e_clica(tmp_path):
    """O Sheet é o caso que obrigou a trocar o `Event` do Node pelo do jsdom."""
    r = correr_js(
        "const S = importar('components/ui/sheet');\n"
        "let fechou = 0;\n"
        "await montar(React.createElement(S.Sheet, { open: true, onOpenChange: () => { fechou += 1; } },\n"
        "  React.createElement(S.SheetContent, null, React.createElement(S.SheetTitle, null, 'Olá'))));\n"
        "const dialogo = document.querySelector('[role=\"dialog\"]');\n"
        "await clicar(botao('Close', dialogo) || dialogo.querySelector('button'));\n"
        "devolve({ titulo: dialogo.querySelector('h2').textContent, fechou });",
        tmp_path, dom=True)
    assert r == {"titulo": "Olá", "fechou": 1}


def test_o_relogio_parado_e_o_localstorage_do_jsdom(tmp_path):
    r = correr_js(
        "pararRelogio(2026, 10, 16, 0, 30);\n"
        "localStorage.setItem('x', '1');\n"
        "devolve({ dia: new Date().getDate(), hora: new Date().getHours(), x: localStorage.getItem('x') });",
        tmp_path, dom=True)
    assert r == {"dia": 16, "hora": 0, "x": "1"}


def test_um_erro_no_javascript_falha_o_teste_com_a_mensagem(tmp_path):
    with pytest.raises(pytest.fail.Exception, match="rebentou de propósito"):
        correr_js("throw new Error('rebentou de propósito');", tmp_path)


def test_um_erro_num_clique_do_react_falha_o_teste(tmp_path):
    """O React apanha a excepção de um handler e só a escreve no stderr: o Node sai com 0 e,
    sem olhar para o stderr, um teste negativo («clicou e não saiu pedido») ficava verde."""
    with pytest.raises(pytest.fail.Exception, match="handler rebentou"):
        correr_js(
            "await montar(React.createElement('button',\n"
            "  { onClick: () => { throw new Error('handler rebentou'); } }, 'Ir'));\n"
            "await clicar(botao('Ir'));\n"
            "devolve('continuou');",
            tmp_path, dom=True)
