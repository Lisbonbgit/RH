"""**O X que tira uma linha da conta** — carregado, não lido.

Pedido do dono (2026-08-25), com o print do POS do Vendus à frente: cada linha
da conta tem um X à direita e um toque tira o produto. Até aqui, apagar uma
linha era tocar na linha, esperar o diálogo do produto e carregar em «Remover
da conta» — três toques para desfazer um engano de um.

O ecrã deste POS desenha-se sem servidor nenhum, e dois defeitos foram a
produção exactamente assim (ver `faturacao-lacai-licoes`). Por isso aqui não se
lê o ficheiro à procura de um `<X />`: monta-se o `PosVenda` a sério sobre a
conta que a função REAL do servidor (`venda._venda_publica`) devolve, CARREGA-SE
no X da segunda linha, e afirma-se o que saiu no pedido e o que ficou no ecrã.

O que este ficheiro NÃO cobre: as guardas do servidor sobre o `DELETE`
(`remover_linha` — conta aberta, do balcão, sem emissão em curso, sessão
aberta). Essas são de `test_venda.py`, e é lá que continuam.
"""
import json

import pytest

from faturacao.venda import _venda_publica

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_ACAI = "Açaí Regular"
_COLA = "Coca-Cola"


def _linha(id_, produto_id, nome, preco):
    return {
        "id": id_, "produto_id": produto_id, "produto_nome": nome,
        "produto_preco": preco, "produto_tax_id": "INT", "quantidade": 1,
        "opcoes": [], "respostas_texto": [], "preco_override": None,
        "tax_override": None, "desconto_pct": None, "desconto_eur": None,
    }


def _conta(linhas, travada=False):
    """A conta como o `GET /pos/venda/aberta` a manda — pela função real, e não
    por um dicionário escrito à mão que podia divergir dela."""
    return _venda_publica({
        "id": "v-1", "loja_id": "l1", "caixa_id": "c1", "sessao_id": "s1",
        "operador_id": "o1", "dispositivo_id": "pc-1", "linhas": linhas,
        "desconto_global_pct": None, "desconto_global_eur": None,
        "estado": "aberta", "criada_em": "2026-08-25T10:00:00+00:00",
    }, travada)


_L_ACAI = _linha("l-1", "p-acai", _ACAI, 7.05)
_L_COLA = _linha("l-2", "p-cola", _COLA, 1.15)


def _produto(id_, nome, preco):
    return {
        "id": id_, "nome": nome, "categoria_id": "cat-1", "preco": preco,
        "tax_id": "INT", "foto_url": None, "grupos_personalizacao": [],
        "ativo": True, "vendavel": True, "erros": [],
    }


def _cenario(*, travada=False):
    """Monta o ecrã de venda com a conta à frente e devolve o que lá está —
    e, quando há X, o que acontece ao carregar no da SEGUNDA linha."""
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        # O PosVenda entra a sério; é ele que está a ser medido.
        "SUBSTITUIDOS.delete(path2.join(POS, 'PosVenda.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: 'Loja' });",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosVenda = carregar(path2.join(POS, 'PosVenda.js')).default;",
        "RESPOSTAS_POS['/pos/catalogo'] = () => ({ data: %s });" % json.dumps({
            "categorias": [{"id": "cat-1", "nome": "Venda ao Público",
                            "ordem": 0, "ativa": True}],
            "produtos": [_produto("p-acai", _ACAI, 7.05),
                         _produto("p-cola", _COLA, 1.15)],
        }, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/tipos-pagamento'] = () => ({ data: [] });",
        "RESPOSTAS_POS['/pos/venda/repartidas'] = () => ({ data: { grupos: [] } });",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "RESPOSTAS_POS['/pos/impressao/estado'] = () => ({ data:"
        " { ha_programa: true, por_sair: 0, falhados: 0 } });",
        # A conta é uma VARIÁVEL: o `DELETE` troca-a pela que sobra, como o
        # servidor faz. Uma resposta fixa deixava o ecrã a mostrar a linha
        # apagada e o teste ficava verde na mesma.
        "let conta = %s;" % json.dumps(_conta([_L_ACAI, _L_COLA], travada),
                                       ensure_ascii=False),
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: conta });",
        "RESPOSTAS_POS['DELETE /pos/venda/v-1/linhas/l-2'] = () => {",
        "  conta = %s;" % json.dumps(_conta([_L_ACAI], travada),
                                     ensure_ascii=False),
        "  return { data: conta };",
        "};",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(PosVenda, {",
        "  operador: { id: 'o1', nome: 'Ana' }, caixa: { id: 'c1', nome: 'Balcão' },",
        "  sessao: { id: 's1', fundo: 50 }, lojaNome: 'Loja',",
        "  onSair: () => {}, onCaixaFechada: () => {}, modo: 'normal' })); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const xis = () => [...alvo.querySelectorAll('button[aria-label]')]",
        "  .filter((b) => b.getAttribute('aria-label').startsWith('Remover'));",
        "const antes = { visivel: textoVisivel(alvo),"
        " etiquetas: xis().map((b) => b.getAttribute('aria-label')) };",
        "if (xis().length > 1) {",
        "  await act(async () => { xis()[1].click(); });",
        "  await act(async () => {});",
        "}",
        "process.stdout.write(JSON.stringify({",
        "  antes, depois: textoVisivel(alvo),",
        "  etiquetasDepois: xis().map((b) => b.getAttribute('aria-label')),",
        "  pedidos: pedidos.map((p) => p.metodo.toUpperCase() + ' ' + p.url),",
        "}));",
    ])


def _correr(cenario, tmp_path_factory, nome):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp(nome), "montar-%s.js" % nome)


@pytest.fixture(scope="module")
def conta_no_ecra(tmp_path_factory):
    return _correr(_cenario(), tmp_path_factory, "conta")


@pytest.fixture(scope="module")
def conta_travada_no_ecra(tmp_path_factory):
    return _correr(_cenario(travada=True), tmp_path_factory, "travada")


def test_a_conta_esta_mesmo_montada(conta_no_ecra):
    """Sem esta afirmação, os guardas a seguir mediam o vazio."""
    for nome in (_ACAI, _COLA):
        assert nome in conta_no_ecra["antes"]["visivel"], \
            conta_no_ecra["antes"]["visivel"][:400]


def test_cada_linha_da_conta_tem_o_seu_X(conta_no_ecra):
    """Um X por linha, e cada um diz QUAL o produto que tira — a etiqueta é o
    que um leitor de ecrã anuncia, e é também o que distingue dois X iguais."""
    assert conta_no_ecra["antes"]["etiquetas"] == [
        "Remover %s da conta" % _ACAI,
        "Remover %s da conta" % _COLA,
    ]


def test_carregar_no_X_manda_o_DELETE_daquela_linha(conta_no_ecra):
    """O id da linha tem de ser o da linha em que se carregou, e não o da
    primeira: dois X iguais a apagar sempre o mesmo produto é o defeito que
    este teste existe para apanhar."""
    assert any(p.endswith("DELETE /api/faturacao/pos/venda/v-1/linhas/l-2")
               or p.endswith("/pos/venda/v-1/linhas/l-2")
               for p in conta_no_ecra["pedidos"] if p.startswith("DELETE")), \
        conta_no_ecra["pedidos"]


def test_a_linha_removida_sai_do_ecra_e_a_outra_fica(conta_no_ecra):
    """Contam-se as VEZES e não a presença: o nome do produto está no ecrã
    duas vezes — uma na grelha da esquerda, onde continua a estar para se
    poder picar outra vez, e outra na conta. O que a remoção tira é a
    segunda."""
    assert conta_no_ecra["antes"]["visivel"].count(_COLA) == 2, \
        conta_no_ecra["antes"]["visivel"][:400]
    assert conta_no_ecra["depois"].count(_COLA) == 1, conta_no_ecra["depois"][:400]
    assert conta_no_ecra["depois"].count(_ACAI) == 2, conta_no_ecra["depois"][:400]
    assert conta_no_ecra["etiquetasDepois"] == ["Remover %s da conta" % _ACAI]


def test_o_X_nao_abre_o_dialogo_do_produto(conta_no_ecra):
    """As duas zonas da linha não se podem confundir: o corpo abre o diálogo,
    o X apaga. Se o toque no X caísse no botão de baixo, o ecrã que ficava era
    o do produto — e a conta desaparecia da frente da operadora."""
    assert "Remover da conta" not in conta_no_ecra["depois"], \
        conta_no_ecra["depois"][:400]
    assert "Produto" in conta_no_ecra["depois"], conta_no_ecra["depois"][:400]


def test_a_conta_TRAVADA_nao_tem_X_nenhum(conta_travada_no_ecra):
    """Emissão por confirmar: a linha continua a LER-SE (é a conta que o gestor
    vai ter de olhar), mas já não se toca — e o servidor recusaria na mesma."""
    assert _ACAI in conta_travada_no_ecra["antes"]["visivel"], \
        conta_travada_no_ecra["antes"]["visivel"][:400]
    assert conta_travada_no_ecra["antes"]["etiquetas"] == []
    assert not [p for p in conta_travada_no_ecra["pedidos"] if p.startswith("DELETE")]
