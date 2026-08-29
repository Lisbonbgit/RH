"""**O NIF que o cliente já ditou não se perde.**

Queixa do balcão, palavra do dono: «o cliente pede fatura com NIF, a
funcionária escreve-o, o cliente lembra-se de juntar mais uma coisa ao pedido,
e quando se volta ao finalizar o NIF desapareceu». Desaparecia porque vivia
dentro do `PosFinalizar`, e sair desse ecrã desmonta o componente.

**A parte que interessa não é o guardar — é o ID DA CONTA.** Uma conta
repartida cobra-se parte a parte, no MESMO ecrã, e um NIF que passasse da
primeira parte para a segunda punha a fatura de um cliente em nome de outro.
Isso é um erro fiscal a sério, e silencioso: sai uma Fatura Simplificada real,
com o NIF errado, entregue à Autoridade Tributária.
"""
from .test_a_faixa_do_modo_no_ecra import _montar_no_node


def _correr(guiao: str, tmp_path):
    return _montar_no_node(
        "\n".join([
            "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
            guiao,
        ]), tmp_path, "nif-da-conta.js")


def test_o_NIF_volta_para_a_MESMA_conta(tmp_path):
    """O caso da queixa: escreve-se, sai-se do ecrã, volta-se."""
    saida = _correr("\n".join([
        "lib.guardarNifDaConta('venda-1', '517542510');",
        "process.stdout.write(JSON.stringify({ lido: lib.lerNifDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["lido"] == "517542510"


def test_o_NIF_NAO_passa_para_OUTRA_conta(tmp_path):
    """**A guarda que faz isto ser seguro.** Sem ela, a segunda parte de uma
    conta repartida — ou a venda seguinte — saía com o NIF do cliente
    anterior, numa fatura real."""
    saida = _correr("\n".join([
        "lib.guardarNifDaConta('venda-1', '517542510');",
        "process.stdout.write(JSON.stringify({ outra: lib.lerNifDaConta('venda-2') }));",
    ]), tmp_path)
    assert saida["outra"] == "", (
        "O NIF de uma conta apareceu noutra — a fatura sai em nome de quem "
        "não a pediu.")


def test_o_NIF_sobrevive_a_um_F5_e_MORRE_ao_desligar_o_PC(tmp_path):
    """`sessionStorage`, a mesma regra da sessão da operadora: recarregar a
    página a meio de uma venda não pode apagar o que já se escreveu, e
    desligar o PC tem de limpar tudo."""
    saida = _correr("\n".join([
        "lib.guardarNifDaConta('venda-1', '517542510');",
        # Um F5 não toca no sessionStorage: o módulo é recarregado, o
        # armazenamento fica.
        "const depoisDoF5 = lib.lerNifDaConta('venda-1');",
        "sessionStorage.clear();",   # desligar o PC
        "process.stdout.write(JSON.stringify({",
        "  depoisDoF5, depoisDeDesligar: lib.lerNifDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["depoisDoF5"] == "517542510"
    assert saida["depoisDeDesligar"] == ""


def test_apagar_o_NIF_no_ecra_apaga_o_guardado(tmp_path):
    """O botão «Limpar» do cartão do cliente escreve texto vazio. Se isso não
    apagasse, o NIF voltava sozinho ao ecrã depois de a operadora o ter
    tirado de propósito — porque o cliente mudou de ideias."""
    saida = _correr("\n".join([
        "lib.guardarNifDaConta('venda-1', '517542510');",
        "lib.guardarNifDaConta('venda-1', '');",
        "process.stdout.write(JSON.stringify({ lido: lib.lerNifDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["lido"] == ""


def test_uma_escrita_SEM_CONTA_nao_apaga_o_NIF_que_la_estava(tmp_path):
    """A gaveta é UMA só. O ecrã pode desenhar-se um instante antes de a conta
    chegar, e uma escrita sem id não podia levar consigo o NIF da conta que
    está a ser cobrada — a operadora via o campo esvaziar-se sozinho.

    Escrito assim, e não a ler com `undefined`: por essa porta responde
    primeiro a guarda da LEITURA, e a da escrita nunca chegava a ser medida —
    a mutação sobreviveu à primeira versão deste teste."""
    saida = _correr("\n".join([
        "lib.guardarNifDaConta('venda-1', '517542510');",
        "lib.guardarNifDaConta(undefined, '999999999');",
        "process.stdout.write(JSON.stringify({",
        "  aindaLa: lib.lerNifDaConta('venda-1'),",
        "  semId: lib.lerNifDaConta(undefined) }));",
    ]), tmp_path)
    assert saida["aindaLa"] == "517542510", "a escrita sem conta apagou o NIF da conta"
    assert saida["semId"] == ""
