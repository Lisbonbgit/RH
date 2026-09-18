"""**A fatura por email no ecrã do POS** — montado e tocado, não lido.

O cliente que mostra o QR na caixa pode levar a fatura por email em vez do
talão. O ecrã do balcão diz qual dos dois vai acontecer, deixa trocar num
toque, e **nunca mostra o endereço** — um ecrã de caixa com o email de quem
está à frente é uma porta de enumeração, e o balcão não precisa dele para
nada (o servidor nem sequer o manda).

Os ecrãs do POS desenham-se todos sem servidor nenhum, e já foram defeitos a
produção exactamente assim. Por isso aqui monta-se o `PosLerQr` e o `PosVenda`
INTEIROS, com o servidor fabricado à frente do axios, carrega-se nos botões, e
o que se afirma é o que a operadora LÊ (`textoVisivel`) e o que o ecrã MANDA
(`pedidos[i].corpo`).

O `PosVenda` inteiro e não o `PosFinalizar` sozinho: entre o cartão e o
`POST /pos/venda/{id}/finalizar` há dois ficheiros, e o que se quer provar
também é o CORPO desse pedido.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
# São SEIS nomes, e estão todos AQUI EM CIMA de propósito. Dois deles — o
# `_UTEIS` e o `_CODIGO` — são usados já pela fixture desta task, aqui mesmo em
# baixo; os outros quatro (`_correr`, `_EMITIDA`, `_EMITIR`, `_no_finalizar`) só
# pelas partes de baixo do ficheiro, o cartão e o ecrã do documento emitido. Um
# import acrescentado a meio do ficheiro fazia a parte que o usasse rebentar na
# RECOLHA — `NameError` antes de correr teste nenhum — se alguém executasse as
# tarefas deste plano por outra ordem.
from .test_o_dividir_e_o_separar_no_ecra import _correr  # noqa: F401
from .test_os_pontos_no_ecra_do_pos import (  # noqa: F401
    _CODIGO, _EMITIDA, _EMITIR, _UTEIS, _no_finalizar,
)

# O endereço que o servidor NÃO manda — posto aqui de propósito na resposta
# fabricada. Se algum dia alguém o acrescentar do outro lado (ou passar a
# guardar a resposta inteira na gaveta), é este teste que grita.
_EMAIL_DO_CLIENTE = "ana.silva@exemplo.pt"


@pytest.fixture(scope="module")
def leitura(tmp_path_factory):
    """A janela «Ler QR do cliente» sozinha: o que ela entrega ao Finalizar, e
    o que a gaveta da conta faz com a resposta CRUA do servidor."""
    cenario = "\n".join([
        _COMPONENTES,
        _UTEIS,
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosLerQr = carregar(path.join(POS, 'PosLerQr.js')).default;",
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {",
        "  ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: true,",
        "  email: %s } });" % json.dumps(_EMAIL_DO_CLIENTE),
        "(async () => {",
        "  const ligadas = [];",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(PosLerQr, {",
        "    vendaId: 'v-1', onLigada: (l) => ligadas.push(l), onFechar: () => {},",
        "  })); });",
        "  await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "  lib.guardarPontosDaConta('v-1', ligadas[0]);",
        "  const saida = {",
        "    ligadas,",
        "    guardada: lib.lerPontosDaConta('v-1'),",
        "    visivel: textoVisivel(alvo),",
        "  };",
        # **A gaveta escrita com a FORMA CRUA do servidor**, e não com o objecto
        # que o PosLerQr já filtrou. É a única escrita que prova a filtragem da
        # GAVETA: alimentada com os três campos limpos, um `{ ...ligacao }` lá
        # dentro passava despercebido para sempre.
        "  lib.guardarPontosDaConta('v-2', { id: 'lig-2', primeiro_nome: 'Ana',",
        "    fatura_por_email: true, email: %s });" % json.dumps(_EMAIL_DO_CLIENTE),
        "  saida.guardadaCrua = lib.lerPontosDaConta('v-2');",
        "  saida.gaveta = sessionStorage.getItem('pos_pontos_da_conta');",
        "  await act(async () => { raiz.unmount(); });",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("qr-email"), "montar-qr-email.js")


def test_a_preferencia_lida_no_QR_chega_ao_Finalizar_e_sobrevive_a_gaveta(leitura):
    """**Os três campos, e só estes.** O `fatura_por_email` serve para desenhar
    o cartão e mais nada: quem decide se o papel sai é o servidor, pelo
    `fat_pontos_qr` que ele próprio gravou ao ler o QR."""
    assert leitura["ligadas"] == [
        {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True}]
    assert leitura["guardada"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True}


def test_o_ENDERECO_do_cliente_nao_entra_na_gaveta_nem_no_ecra(leitura):
    """A gaveta escolhe campo a campo de propósito, e prova-se com a resposta
    crua: um `{ ...ligacao }` a copiar o que o servidor mandou punha o email de
    cada cliente no `sessionStorage` do PC do balcão — e o `sessionStorage` do
    POS é lido por tudo o que corra naquela aba."""
    assert leitura["guardadaCrua"] == {
        "id": "lig-2", "primeiro_nome": "Ana", "fatura_por_email": True}
    assert _EMAIL_DO_CLIENTE not in leitura["gaveta"], leitura["gaveta"]
    assert _EMAIL_DO_CLIENTE not in leitura["visivel"], leitura["visivel"][:400]
