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

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node

# Os QUATRO campos da gaveta. O `fatura_por_email` entrou a 2026-09-17 com a
# fatura por email e o `nif` da conta da app a 2026-10-24; estão sempre
# presentes, mesmo a `False` e a `None` — ver `lib/pos.js::guardarPontosDaConta`.
_ANA = {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False, "nif": None}
# A mesma cliente, com NIF na conta da app: o telefone da queixa de 2026-09-11
# com o dígito de controlo certo (test_o_nif_que_nao_existe_no_pos.py).
_ANA_COM_NIF = dict(_ANA, nif="219363935")
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


def test_o_NIF_da_conta_da_app_fica_na_gaveta_da_MESMA_conta_e_so_dessa(tmp_path):
    """O NIF que o servidor mandou na leitura fica com a ligação, para o cartão
    Cliente o poder OFERECER — e morre com ela: outra conta não o vê."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA_COM_NIF),
        "process.stdout.write(JSON.stringify({",
        "  lida: lib.lerPontosDaConta('venda-1'), outra: lib.lerPontosDaConta('venda-2') }));",
    ]), tmp_path)
    assert saida["lida"] == _ANA_COM_NIF
    assert saida["outra"] is None


# --- O NIF da app no cartão Cliente: as duas decisões, corridas a sério -------


def _em_node(expressoes, tmp_path):
    """As funções REAIS do `lib/pos.js` sobre cada expressão, numa só viagem
    ao Node."""
    return _correr(
        "process.stdout.write(JSON.stringify([%s]));" % ", ".join(expressoes), tmp_path)


def test_a_mascara_mostra_so_o_primeiro_digito_e_os_dois_ultimos(tmp_path):
    """O ecrã da caixa está virado para a fila: chega para a funcionária
    confirmar «é este?», e o resto não se lê por cima do ombro."""
    assert _em_node(["lib.nifMascarado('219363935')", "lib.nifMascarado('517542510')"],
                    tmp_path) == ["2•• ••• •35", "5•• ••• •10"]


def test_a_mascara_de_um_numero_que_nao_tem_nove_digitos_nao_mostra_nada(tmp_path):
    """Uma máscara que deixasse passar o número inteiro não escondia coisa
    nenhuma — e com dez dígitos o `slice` dos dois últimos mostrava três."""
    assert _em_node([
        "lib.nifMascarado('')", "lib.nifMascarado(null)", "lib.nifMascarado(undefined)",
        "lib.nifMascarado('12345')", "lib.nifMascarado('2193639351')",
    ], tmp_path) == [""] * 5


def _oferece(ligacao, nif_texto):
    return "lib.nifDaAppParaOferecer({ ligacao: %s, nifTexto: %s })" % (
        json.dumps(ligacao), "undefined" if nif_texto is None else json.dumps(nif_texto))


def test_com_o_campo_do_NIF_vazio_oferece_se_o_NIF_da_app(tmp_path):
    """Vazio, só com espaços, ou nunca escrito: o botão aparece, com os nove
    dígitos que o toque vai pôr no campo."""
    assert _em_node([_oferece(_ANA_COM_NIF, ""), _oferece(_ANA_COM_NIF, "   "),
                     _oferece(_ANA_COM_NIF, None)], tmp_path) == ["219363935"] * 3


@pytest.mark.parametrize("ligacao, nif_texto", [
    (None, ""),                                   # nenhum QR lido nesta conta
    (_ANA, ""),                                   # a conta da app não tem NIF
    ({"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}, ""),  # gaveta antiga
    (dict(_ANA, nif="219363931"), ""),            # o telefone da queixa: não é NIF
    (dict(_ANA, nif="219 363 935"), ""),          # o servidor manda nove dígitos e mais nada
    (_ANA_COM_NIF, "5"),                          # um dígito escrito depois da leitura
    (_ANA_COM_NIF, "517 542 510"),                # o NIF ditado ANTES do QR
    (_ANA_COM_NIF, "219363935"),                  # o próprio, já no campo
])
def test_o_NIF_da_app_NAO_se_oferece(ligacao, nif_texto, tmp_path):
    """**Perguntar sempre, nunca tapar o que lá está.** Sem cliente lido, sem
    NIF que passe o dígito de controlo, ou com QUALQUER dígito no campo, não há
    botão: o que a operadora escreveu não se substitui por baixo dela, e um
    botão que pusesse um número inválido acendia o aviso vermelho do cartão."""
    assert _em_node([_oferece(ligacao, nif_texto)], tmp_path) == [None]
