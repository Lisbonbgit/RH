"""**«Se eu escrever o meu código da conta, dá para utilizar?»**

Pergunta do dono, 2026-09-16, com a janela «Ler QR do cliente» aberta à frente.
A resposta é não — e é de propósito: os pontos são de quem MOSTRA a app na
caixa, não de quem sabe um número de cor. Era essa a burla do talão apanhado no
lixo que este ecrã veio fechar.

O problema não era a recusa, era o que o balcão ouvia. Dois códigos parecidos
de mais:

    LA12345678               ← o código da CONTA, o que se dá a um amigo
    LQK7M2P...(22 caracteres) ← o QR, que a app cria e que dura 45 segundos

e o servidor respondia aos dois a mesma frase — «QR inválido ou expirado, peça
ao cliente para abrir o QR outra vez» —, que manda repetir exactamente o que
não pode funcionar.

O formato responde-se agora no ecrã, antes de sair do PC: a pergunta não é
sobre a conta de ninguém. Gasto ou expirado continua a ser o servidor a dizer.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node

_QR = "LQK7M2NP3QRSTUVWXYZ4AB"          # 22 caracteres depois do «LQ»


def _recado(texto, tmp_path):
    saida = _montar_no_node("\n".join([
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "process.stdout.write(JSON.stringify("
        "{ recado: lib.recadoDeCodigoQrErrado(%s) }));" % json.dumps(texto),
    ]), tmp_path, "recado-do-qr.js")
    return saida["recado"]


@pytest.mark.parametrize("codigo", [
    "LQ" + _QR,
    "lq" + _QR.lower(),          # o leitor com Caps Lock inverte a CAIXA
    " LQ" + _QR + "\n",          # e cola-lhe o Enter
])
def test_um_QR_a_SERIO_passa_sem_recado(codigo, tmp_path):
    assert _recado(codigo, tmp_path) is None


def test_o_campo_vazio_nao_e_um_erro(tmp_path):
    """Quem ainda não escreveu nada não levou com nada."""
    assert _recado("", tmp_path) is None


def test_o_codigo_da_CONTA_diz_que_e_o_da_conta(tmp_path):
    """A frase tem de nomear o que a pessoa escreveu — senão volta a escrevê-lo."""
    recado = _recado("LA12345678", tmp_path)
    assert recado and "conta" in recado.lower(), recado
    assert "Mostrar QR na caixa" in recado, recado


@pytest.mark.parametrize("escrito", [
    "219363935",          # um NIF
    "12",                 # o número da mesa
    "Ana",                # o nome do cliente
])
def test_qualquer_outra_coisa_explica_onde_nasce_o_QR(escrito, tmp_path):
    """Tudo o que a mão escreve quando o campo está com o foco e ninguém
    percebeu para que serve."""
    recado = _recado(escrito, tmp_path)
    assert recado and "Mostrar QR na caixa" in recado, recado


@pytest.mark.parametrize("escrito", ["219363935", "12", "Ana", "LQ123", "LA1234567"])
def test_a_frase_generica_nao_ACUSA_ninguem_de_ter_escrito_o_codigo_da_conta(escrito, tmp_path):
    """**As duas frases têm de ser distinguíveis por um teste.**

    Ambas acabam em «Mostrar QR na caixa», por isso afirmar só essa expressão
    dava as duas por boas: o ramo genérico podia passar a dizer «esse é o código
    da conta do cliente» e nenhuma linha ficava vermelha. Quem escreveu um NIF
    ouviria que escreveu uma conta, e a funcionária ia investigar uma conta que
    ninguém escreveu — a recusa que não explica nada, mudada de fato.

    Repare-se no «LA1234567»: oito caracteres depois do LA mas só sete dígitos,
    por isso NÃO é um código de conta e não pode ser tratado como tal."""
    recado = _recado(escrito, tmp_path)
    assert recado and "conta" not in recado.lower(), recado


@pytest.mark.parametrize("quase", [
    "LQ" + _QR[:-1],             # 21 caracteres: um a menos
    "LQ" + _QR + "X",            # 23: um a mais
    "LQ" + _QR[:-1] + "-",       # símbolo: o leitor com o layout trocado
])
def test_um_QR_MAL_LIDO_nao_vai_ao_servidor(quase, tmp_path):
    """O leitor com o layout do teclado trocado troca símbolos, e uma leitura
    cortada a meio chega curta. Nenhuma delas tem hipótese no servidor."""
    assert _recado(quase, tmp_path) is not None
