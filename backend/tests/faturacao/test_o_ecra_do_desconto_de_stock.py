"""**O ecrã do interruptor** — e a frase que decide se ligá-lo faz sentido hoje.

O interruptor é a parte fácil. A parte que interessa é o aviso das lojas ainda
sem unidade do Estoque: ligar o desconto com lojas por ligar **não dá erro
nenhum** — o stock dessas simplesmente não desce, e a diferença só aparece na
contagem do mês. Se o ecrã não o disser, ninguém sabe.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_TUDO_LIGADO = {"ativo": False, "mudado_em": None, "lojas_por_ligar": []}
_COM_LOJAS_POR_LIGAR = {
    "ativo": False, "mudado_em": None,
    "lojas_por_ligar": [{"id": "l1", "nome": "Belém"}, {"id": "l2", "nome": "Oeiras"}],
}


def _monta(resposta, leituras, tmp_path, nome, falhar=False):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const Ecra = carregar(path2.join(ADMIN, 'FatDescontoStock.js')).default;",
        ("RESPOSTAS_GESTAO['/faturacao/desconto-stock'] = () => { const e = "
         "new Error('502'); e.response = { status: 502, data: { detail: "
         "'O servidor não respondeu.' } }; throw e; };") if falhar else
        ("RESPOSTAS_GESTAO['/faturacao/desconto-stock'] = () => ({ data: %s });"
         % json.dumps(resposta, ensure_ascii=False)),
        ("RESPOSTAS_GESTAO['PUT /faturacao/desconto-stock'] = () => ({ data: %s });"
         % json.dumps(dict(resposta or {}, ativo=True), ensure_ascii=False)),
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(React.createElement(Ecra)); });",
        "await act(async () => {}); await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const saida = {};",
        "saida.texto = alvo.textContent;",
    ] + leituras + [
        "saida.pedidos = pedidos.map((p) => [p.metodo, String(p.url)]);",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => { "
        "process.stderr.write(String(e && e.stack || e)); process.exit(1); });" % guiao,
        tmp_path, nome)


def test_o_ecra_DIZ_quais_sao_as_lojas_por_ligar(tmp_path):
    """A frase que este ecrã existe para dizer."""
    saida = _monta(_COM_LOJAS_POR_LIGAR, [
        "saida.aviso = (porTestid('desconto-lojas-por-ligar') || {}).textContent;",
    ], tmp_path, "por-ligar.js")
    assert saida["aviso"], "não avisa que há lojas sem unidade do Estoque"
    assert "Belém" in saida["aviso"] and "Oeiras" in saida["aviso"], saida["aviso"]
    assert "2 loja" in saida["aviso"], saida["aviso"]


def test_com_tudo_ligado_nao_ha_aviso_nenhum(tmp_path):
    """Um aviso permanente deixa de se ler ao terceiro dia."""
    saida = _monta(_TUDO_LIGADO, [
        "saida.aviso = !!porTestid('desconto-lojas-por-ligar');",
        "saida.confirma = !!porTestid('desconto-tudo-ligado');",
    ], tmp_path, "tudo-ligado.js")
    assert saida["aviso"] is False
    assert saida["confirma"], "e diz que está tudo ligado"


def test_o_ecra_avisa_do_que_fazer_ANTES_de_ligar(tmp_path):
    """A razão de ser da Fase 1 — comparar o relatório com uma contagem —
    tem de estar escrita onde se carrega no botão, não só na cabeça de quem
    construiu isto."""
    saida = _monta(_TUDO_LIGADO, [], tmp_path, "antes-de-ligar.js")
    assert "Consumo" in saida["texto"]
    assert "contagem" in saida["texto"]
    assert "app" in saida["texto"], "tem de dizer que a app não desconta"


def test_ligar_o_interruptor_manda_o_PUT(tmp_path):
    saida = _monta(_TUDO_LIGADO, [
        "const el = porTestid('desconto-interruptor');",
        "const setter = Object.getOwnPropertyDescriptor(",
        "  window.HTMLInputElement.prototype, 'checked').set;",
        "await act(async () => { setter.call(el, true);",
        "  el.dispatchEvent(new window.Event('click', { bubbles: true }));",
        "  el.dispatchEvent(new window.Event('change', { bubbles: true })); });",
        "await act(async () => {}); await act(async () => {});",
    ], tmp_path, "ligar.js")
    puts = [p for p in saida["pedidos"] if p[0] == "put"]
    assert puts, saida["pedidos"]


def test_o_servidor_em_baixo_nao_deixa_o_interruptor_a_mentir(tmp_path):
    """Um interruptor desenhado a «desligado» quando não se sabe o estado é
    uma mentira permanente — o dono lê «não está a descontar» sem isso ter
    sido verificado. Com erro, o interruptor fica travado e o erro à vista."""
    saida = _monta(None, [
        "saida.erro = !!porTestid('desconto-erro');",
        "saida.travado = (porTestid('desconto-interruptor') || {}).disabled;",
    ], tmp_path, "em-baixo.js", falhar=True)
    assert saida["erro"], "o erro passou em silêncio"
    assert saida["travado"] is True, "o interruptor ficou clicável sem se saber o estado"
