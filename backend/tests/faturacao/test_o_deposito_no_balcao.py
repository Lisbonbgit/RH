"""**A faixa do depósito no ecrã do balcão.**

Faixa própria entre a lista e o total — e NÃO uma linha de produto. É o que a
lei manda (linha separada do preço do produto) e é como o Vendus a mostra.

Duas coisas que só se vêem montando o ecrã:

1. **o depósito não conta no contador de artigos.** Uma conta com uma
   Coca-Cola tem UM produto. No POS do Vendus lê-se «1 Produtos / 1 Uni.» com
   o depósito à vista, e o nosso tem de dizer o mesmo;
2. **a faixa não aparece quando não há embalagens** — que é a esmagadora
   maioria das contas desta casa. Uma linha a 0,00 € em todas as contas de
   açaí do dia era ruído permanente no ecrã mais usado da casa.
"""
import json

from faturacao.venda import _venda_publica

from .test_o_dividir_e_o_separar_no_ecra import (
    _COMPONENTES, _montar_no_node, _produto,
)

_ACAI = "Açaí Regular"
_AGUA = "Água 50cl"


def _linha(id_, produto_id, nome, preco, qtd=1, deposito=None):
    li = {
        "id": id_, "produto_id": produto_id, "produto_nome": nome,
        "produto_preco": preco, "produto_tax_id": "INT", "quantidade": qtd,
        "opcoes": [], "respostas_texto": [], "preco_override": None,
        "tax_override": None, "desconto_pct": None, "desconto_eur": None,
    }
    if deposito is not None:
        li["deposito_unitario"] = deposito
    return li


def _conta(linhas):
    """A conta como o SERVIDOR a devolve — pela função real, para os totais
    (e o depósito) virem da aritmética que corre em produção e não de um
    dicionário escrito à mão que pode divergir dela."""
    return _venda_publica({
        "id": "v1", "loja_id": "l1", "caixa_id": "c1", "sessao_id": "s1",
        "operador_id": "o1", "dispositivo_id": "pc-1", "linhas": linhas,
        "desconto_global_pct": None, "desconto_global_eur": None,
        "estado": "aberta", "criada_em": "2026-09-03T10:00:00+00:00",
        "conta_mae_id": None,
    })


_CATALOGO = {
    "categorias": [{"id": "cat-1", "nome": "Venda ao Público", "ordem": 0, "ativa": True}],
    "produtos": [_produto("p-acai", _ACAI, 8.99), _produto("p-agua", _AGUA, 1.45)],
}


def _monta(linhas, leituras, tmp_path_factory, nome):
    cenario = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "SUBSTITUIDOS.delete(path2.join(POS, 'PosVenda.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: 'Loja' });",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosVenda = carregar(path2.join(POS, 'PosVenda.js')).default;",
        "RESPOSTAS_POS['/pos/catalogo'] = () => ({ data: %s });"
        % json.dumps(_CATALOGO, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/tipos-pagamento'] = () => ({ data: [",
        "  { id: 'tp-1', nome: 'Dinheiro', da_troco: true, pronto: true } ] });",
        "RESPOSTAS_POS['/pos/venda/repartidas'] = () => ({ data: { grupos: [] } });",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "RESPOSTAS_POS['/pos/impressao/estado'] = () => ({ data:"
        " { ha_programa: true, por_sair: 0, falhados: 0 } });",
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_conta(linhas), ensure_ascii=False),
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(React.createElement(PosVenda, {",
        "  operador: { id: 'o1', nome: 'Ana' }, caixa: { id: 'c1', nome: 'Balcão' },",
        "  sessao: { id: 's1', fundo: 50 }, lojaNome: 'Loja',",
        "  onSair: () => {}, onCaixaFechada: () => {}, modo: 'normal' })); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const saida = {};",
    ] + leituras + [
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp(nome), "dep-%s.js" % nome)


def test_a_faixa_DIZ_o_deposito_e_quantas_embalagens(tmp_path_factory):
    saida = _monta(
        [_linha("l1", "p-acai", _ACAI, 8.99),
         _linha("l2", "p-agua", _AGUA, 1.45, qtd=2, deposito=0.10)],
        ["saida.faixa = (porTestid('pos-faixa-deposito') || {}).textContent;"],
        tmp_path_factory, "faixa")
    assert saida["faixa"], "a faixa do depósito não apareceu"
    assert "Depósito" in saida["faixa"]
    assert "0,20" in saida["faixa"], saida["faixa"]
    assert "2 embalagens" in saida["faixa"], saida["faixa"]


def test_UMA_embalagem_no_singular(tmp_path_factory):
    saida = _monta(
        [_linha("l1", "p-agua", _AGUA, 1.45, deposito=0.10)],
        ["saida.faixa = (porTestid('pos-faixa-deposito') || {}).textContent;"],
        tmp_path_factory, "singular")
    assert "1 embalagem" in saida["faixa"] and "embalagens" not in saida["faixa"], saida["faixa"]


def test_uma_conta_SEM_embalagens_nao_tem_faixa_nenhuma(tmp_path_factory):
    """A esmagadora maioria das contas desta casa."""
    saida = _monta(
        [_linha("l1", "p-acai", _ACAI, 8.99)],
        ["saida.tem = !!porTestid('pos-faixa-deposito');"],
        tmp_path_factory, "sem")
    assert saida["tem"] is False


def test_o_deposito_NAO_conta_no_contador_de_artigos(tmp_path_factory):
    """Uma conta com um açaí e uma água tem DOIS produtos, não três. É o que
    o POS do Vendus mostra, e o contador é o que a operadora usa para
    conferir a conta com o cliente à frente."""
    saida = _monta(
        [_linha("l1", "p-acai", _ACAI, 8.99),
         _linha("l2", "p-agua", _AGUA, 1.45, deposito=0.10)],
        ["saida.ecra = textoVisivel(alvo);"],
        tmp_path_factory, "contador")
    assert "2 Produtos" in saida["ecra"], saida["ecra"][-400:]


def test_o_TOTAL_ja_traz_o_deposito(tmp_path_factory):
    """8,99 + 1,45 + 0,10. O total é sempre o do servidor — este ecrã nunca
    soma preços — e é ele que o cliente paga."""
    saida = _monta(
        [_linha("l1", "p-acai", _ACAI, 8.99),
         _linha("l2", "p-agua", _AGUA, 1.45, deposito=0.10)],
        ["saida.ecra = textoVisivel(alvo);"],
        tmp_path_factory, "total")
    assert "10,54" in saida["ecra"], saida["ecra"][-400:]
