"""**O cliente dos pontos fica preso à CONTA onde o QR foi lido.**

A funcionária lê o QR que o cliente mostra na app e o POS guarda a ligação até
ao EMITIR. Guarda-a no `sessionStorage`, com o id da conta, pelo mesmo molde
do NIF (`test_o_nif_da_conta_no_pos.py`): voltar à conta para juntar mais um
artigo não pode perder o cliente, e desligar o PC tem de o esquecer.

**A peça que interessa é o id da conta.** Uma conta repartida cobra-se parte a
parte no mesmo ecrã. Uma ligação que passasse da primeira parte para a segunda
dava os pontos da fatura de uma pessoa a outra — e como a app só credita UMA
fatura por ligação, quem mostrou a app ficava sem nada.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node

_ANA = {"id": "lig-1", "primeiro_nome": "Ana"}
_CODIGO = "LQ7K2MN8P3QRSTUV4WXYZ9AB"


def _correr(guiao: str, tmp_path):
    return _montar_no_node(
        "\n".join([
            "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
            guiao,
        ]), tmp_path, "pontos-da-conta.js")


def test_a_ligacao_volta_para_a_MESMA_conta(tmp_path):
    """O cliente lembra-se de mais um artigo: sai-se do Finalizar e volta-se."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "process.stdout.write(JSON.stringify({ lida: lib.lerPontosDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["lida"] == _ANA


def test_a_ligacao_NAO_passa_para_OUTRA_conta(tmp_path):
    """**A guarda que faz isto ser seguro.** Sem ela, a segunda parte de uma
    conta repartida — ou a venda seguinte — levava os pontos de quem mostrou
    a app na anterior."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "process.stdout.write(JSON.stringify({ outra: lib.lerPontosDaConta('venda-2') }));",
    ]), tmp_path)
    assert saida["outra"] is None, (
        "A ligação de uma conta apareceu noutra — os pontos iam para quem "
        "não os ganhou.")


def test_a_ligacao_sobrevive_a_um_F5_e_MORRE_ao_desligar_o_PC(tmp_path):
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "const depoisDoF5 = lib.lerPontosDaConta('venda-1');",
        "sessionStorage.clear();",
        "process.stdout.write(JSON.stringify({",
        "  depoisDoF5, depoisDeDesligar: lib.lerPontosDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["depoisDoF5"] == _ANA
    assert saida["depoisDeDesligar"] is None


def test_remover_a_ligacao_no_ecra_apaga_a_guardada(tmp_path):
    """O «Remover» do cartão escreve `null`. Se isso não apagasse, o cliente
    voltava sozinho ao cartão depois de a funcionária o ter tirado."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "lib.guardarPontosDaConta('venda-1', null);",
        "process.stdout.write(JSON.stringify({ lida: lib.lerPontosDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["lida"] is None


def test_uma_escrita_SEM_CONTA_nao_apaga_a_ligacao_que_la_estava(tmp_path):
    """A gaveta é UMA só, e o ecrã pode desenhar-se um instante antes de a
    conta chegar. Lido pela conta certa, e não por `undefined`: por essa porta
    responde primeiro a guarda da leitura e a da escrita nunca era medida."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "lib.guardarPontosDaConta(undefined, { id: 'lig-2', primeiro_nome: 'Rui' });",
        "process.stdout.write(JSON.stringify({",
        "  aindaLa: lib.lerPontosDaConta('venda-1'),",
        "  semId: lib.lerPontosDaConta(undefined) }));",
    ]), tmp_path)
    assert saida["aindaLa"] == _ANA, "a escrita sem conta apagou a ligação da conta"
    assert saida["semId"] is None


def test_ler_o_QR_pergunta_ao_servidor_pela_conta_e_devolve_o_primeiro_nome(tmp_path):
    """O pedido que sai do browser: método, caminho, corpo e a sessão da
    operadora. É o servidor (C1) que fala com a app — daqui só sai o código
    lido e a conta."""
    saida = _correr("\n".join([
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({",
        "  data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana' } });",
        "(async () => {",
        "  const resposta = await lib.lerQrDePontos('venda-1', %s);" % json.dumps(_CODIGO),
        "  const p = pedidos[pedidos.length - 1];",
        "  process.stdout.write(JSON.stringify({ resposta, metodo: p.metodo, url: p.url,",
        "    corpo: p.corpo, operador: p.headers['X-Operator-Token'] }));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ]), tmp_path)
    assert saida["resposta"] == {"ligacao_id": "lig-1", "primeiro_nome": "Ana"}
    assert saida["metodo"] == "post"
    assert saida["url"].endswith("/api/faturacao/pos/pontos/ler"), saida["url"]
    assert saida["corpo"] == {"venda_id": "venda-1", "codigo": _CODIGO}
    assert saida["operador"] == "ot"
