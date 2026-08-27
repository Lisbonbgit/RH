"""**Desligar o PC tem de pedir o PIN outra vez.**

O dono, com o POS já a vender numa loja: «eu desligo o pc e ligo novamente.
quando eu entro novamente no pos, ele já está numa sessão. mas isso não
deveria acontecer, era sempre para entrar nesta página.»

Não é um incómodo, é um buraco de responsabilização: quem abrir o PC a seguir
vende com o nome de quem lá esteve antes, e o Z do fim do dia culpa quem já
tinha ido embora. O token do operador dura 12 horas do lado do servidor — o
que estava errado era o SÍTIO onde o browser o guardava.

**A distinção que faz isto funcionar** é entre os dois armazenamentos do
browser, e não entre prazos:

- `localStorage` sobrevive a fechar o browser e a desligar o PC. É onde o
  EMPARELHAMENTO tem de viver — um PC emparelhado uma vez fica emparelhado;
- `sessionStorage` morre quando a janela fecha, mas sobrevive a um F5. É
  exactamente o que a sessão do operador precisa: recarregar a página a meio
  de uma venda não pode expulsar ninguém, e desligar o PC tem de expulsar.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node


def _correr(guiao: str, tmp_path):
    """Corre o `lib/pos.js` A SÉRIO em Node, com os dois armazenamentos do
    browser — e não uma cópia das funções escrita aqui.

    Usa o mesmo suporte de montagem dos ecrãs (`_montar_no_node`): é ele que
    sabe onde vive o `jsdom`, o `babel` e o resto, e uma segunda montagem
    escrita aqui divergia dele à primeira mudança."""
    return _montar_no_node(
        "\n".join([
            "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
            guiao,
        ]), tmp_path, "sessao.js")


def test_o_EMPARELHAMENTO_sobrevive_a_desligar_o_PC_DUAS_vezes(tmp_path):
    """Fica no `localStorage`, e é o que tem de ser: um PC emparelhado uma vez
    não pode voltar a pedir o código do gestor a cada arranque.

    **Dois ciclos, e não um.** Escrevi este teste com um só desligar e a
    mutação passou por ele: pôr o emparelhamento a ler pelo caminho da sessão
    devolvia o token à mesma da primeira vez — porque a leitura MUDA-O de
    sítio — e só se perdia no arranque SEGUINTE. Com lojas a vender, esse
    defeito custava um pedido de código ao gestor por cada reinício de cada
    PC, e o teste dizia que estava tudo bem."""
    saida = _correr("\n".join([
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: 'Loja' });",
        # Primeiro desligar: o sessionStorage morre, o localStorage fica.
        "sessionStorage.clear();",
        "const primeiro = lib.getDeviceToken();",
        # Segundo desligar — é aqui que um emparelhamento mal guardado se perde.
        "sessionStorage.clear();",
        "process.stdout.write(JSON.stringify({",
        "  primeiro, segundo: lib.getDeviceToken(), loja: lib.getLojaNome() }));",
    ]), tmp_path)
    assert saida["primeiro"] == "dt"
    assert saida["segundo"] == "dt", (
        "O emparelhamento perdeu-se ao segundo arranque — a loja fica a pedir "
        "um código novo ao gestor de cada vez que liga o PC.")
    assert saida["loja"] == "Loja"


def test_a_SESSAO_DO_OPERADOR_nao_sobrevive_a_desligar_o_PC(tmp_path):
    """O pedido do dono, literalmente."""
    saida = _correr("\n".join([
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Débora' });",
        "sessionStorage.clear();",   # desligar o PC
        "process.stdout.write(JSON.stringify({",
        "  token: lib.getOperatorToken(), dados: lib.getOperadorGuardado() }));",
    ]), tmp_path)
    assert saida["token"] is None, "O POS entrou com a sessão de quem lá esteve antes."
    assert saida["dados"] is None


def test_um_F5_a_meio_de_uma_venda_NAO_expulsa_a_operadora(tmp_path):
    """A outra metade, e a que impede a correcção de ser pior do que o
    defeito: recarregar a página não pode mandar a operadora escrever o PIN
    com o cliente à frente."""
    saida = _correr("\n".join([
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Débora' });",
        # Um F5 não toca no sessionStorage — só o fechar da janela o faz.
        "process.stdout.write(JSON.stringify({",
        "  token: lib.getOperatorToken(), dados: lib.getOperadorGuardado() }));",
    ]), tmp_path)
    assert saida["token"] == "ot"
    assert saida["dados"]["nome"] == "Débora"


def test_uma_sessao_JA_GUARDADA_no_sitio_antigo_e_mudada_de_sitio(tmp_path):
    """**O cuidado com as lojas que já estão a vender.** No instante do deploy
    há operadoras com a sessão no `localStorage`, do código anterior. Sem
    isto, a primeira vez que a página recarregasse elas eram expulsas para o
    PIN — a meio de um turno, com fila à frente.

    A mudança de sítio acontece uma vez, na primeira leitura, e APAGA a cópia
    antiga: sem esse apagar, a sessão voltava a ser restaurada em cada
    arranque e o defeito do dono ficava exactamente como estava."""
    saida = _correr("\n".join([
        # Como o código anterior a tinha deixado.
        "localStorage.setItem('pos_operator_token', 'ot-antigo');",
        "localStorage.setItem('pos_operador', JSON.stringify({ id: 'o1', nome: 'Ana' }));",
        "const primeira = lib.getOperatorToken();",
        "process.stdout.write(JSON.stringify({",
        "  primeira,",
        "  ficou_na_sessao: sessionStorage.getItem('pos_operator_token'),",
        "  sobra_no_antigo: localStorage.getItem('pos_operator_token'),",
        "  dados: lib.getOperadorGuardado(),",
        "}));",
    ]), tmp_path)
    assert saida["primeira"] == "ot-antigo", "Expulsou a operadora no deploy."
    assert saida["ficou_na_sessao"] == "ot-antigo"
    assert saida["sobra_no_antigo"] is None, (
        "A cópia antiga ficou para trás — no arranque seguinte o defeito volta.")
    assert saida["dados"]["nome"] == "Ana"


def test_depois_da_mudanca_de_sitio_desligar_o_PC_JA_pede_o_PIN(tmp_path):
    """E é isto que faz da migração uma correcção e não um adiamento: a sessão
    mudada de sítio comporta-se como as novas já no arranque seguinte."""
    saida = _correr("\n".join([
        "localStorage.setItem('pos_operator_token', 'ot-antigo');",
        "localStorage.setItem('pos_operador', JSON.stringify({ id: 'o1', nome: 'Ana' }));",
        "lib.getOperatorToken();",   # a página carrega uma vez com o código novo
        "sessionStorage.clear();",   # e o PC é desligado
        "process.stdout.write(JSON.stringify({ token: lib.getOperatorToken() }));",
    ]), tmp_path)
    assert saida["token"] is None


def test_sair_APAGA_a_sessao_dos_dois_sitios(tmp_path):
    """O botão de sair não pode deixar a sessão na cópia antiga."""
    saida = _correr("\n".join([
        "localStorage.setItem('pos_operator_token', 'velho');",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Débora' });",
        "lib.esquecerOperador();",
        "process.stdout.write(JSON.stringify({",
        "  sessao: sessionStorage.getItem('pos_operator_token'),",
        "  antigo: localStorage.getItem('pos_operator_token'),",
        "}));",
    ]), tmp_path)
    assert saida["sessao"] is None
    assert saida["antigo"] is None
