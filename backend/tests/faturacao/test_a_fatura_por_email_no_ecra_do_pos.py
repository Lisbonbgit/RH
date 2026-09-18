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


# --- O cartão no Finalizar, pelo PosVenda inteiro ------------------------------


@pytest.fixture(scope="module")
def cartao(tmp_path_factory):
    """Lê o QR com a preferência LIGADA e carrega no botão três vezes, com o
    servidor a responder de três maneiras: a concordar, a recusar, e a DIVERGIR
    do que se pediu."""
    cenario = _no_finalizar("\n".join([
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {",
        "  ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: true,",
        "  email: %s } });" % json.dumps(_EMAIL_DO_CLIENTE),
        # A rota da preferência responde o que a variável disser no instante do
        # toque — é o mesmo botão nos três casos.
        "let respostaDaPreferencia = () => ({ data: { fatura_por_email: false } });",
        "RESPOSTAS_POS['POST /pos/pontos/preferencia'] = () => respostaDaPreferencia();",
    ]))
    return _correr("\n".join([
        cenario,
        # O cartão SOZINHO, e não o ecrã todo: a asserção do «@» tem de falar
        # do cartão. Um endereço de suporte no rodapé, ou um artigo com «@» no
        # nome, punha este teste vermelho por uma fuga que não existe.
        "const cartao = () => {",
        "  const el = alvo.querySelector('[data-testid=\"cartao-pontos\"]');",
        "  if (!el) throw new Error('sem cartão dos pontos no ecrã: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  return textoVisivel(el);",
        "};",
        "await carregar_em('Ler QR do cliente');",
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "const porEmail = cartao();",
        "const ecraTodo = textoVisivel(alvo);",
        # 1) O servidor concorda com o que se pediu.
        "await carregar_em('Voltar ao papel');",
        "const noPapel = cartao();",
        "const guardada = lib.lerPontosDaConta('v-1');",
        # 2) O servidor RECUSA (a ligação já foi usada).
        "respostaDaPreferencia = () => {",
        "  const e = new Error('Request failed with status code 409');",
        "  e.response = { status: 409, data: { detail: 'Esse QR já foi usado.' } };",
        "  throw e;",
        "};",
        "await carregar_em('Enviar por email');",
        "const depoisDaRecusa = cartao();",
        "const guardadaDepois = lib.lerPontosDaConta('v-1');",
        # 3) O servidor responde 200 mas DIVERGE do pedido: pediu-se `true` e
        #    ele diz que ficou `false` (a app já tinha desligado a preferência).
        "respostaDaPreferencia = () => ({ data: { fatura_por_email: false } });",
        "await carregar_em('Enviar por email');",
        "const depoisDaDivergencia = cartao();",
        "const guardadaDivergente = lib.lerPontosDaConta('v-1');",
        "const corposPreferencia = pedidos.filter(",
        "  (p) => p.url.endsWith('/pos/pontos/preferencia')).map((p) => p.corpo);",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ porEmail, ecraTodo, noPapel, guardada,",
        "  corposPreferencia, depoisDaRecusa, guardadaDepois, depoisDaDivergencia,",
        "  guardadaDivergente, emitirVivo, corpos }));",
    ]), tmp_path_factory, "cartao-email")


def test_com_a_preferencia_LIGADA_o_cartao_diz_email_e_oferece_voltar_ao_papel(cartao):
    assert "Pontos para: Ana ✓ · Fatura por email ✉" in cartao["porEmail"], \
        cartao["porEmail"][:600]
    assert "Voltar ao papel" in cartao["porEmail"], cartao["porEmail"][:600]
    assert "Remover" in cartao["porEmail"], cartao["porEmail"][:600]


def test_o_endereco_NUNCA_aparece_no_ecra_do_balcao(cartao):
    """Só o sim/não. O ecrã da caixa está à vista da loja inteira, e um email
    por cima dele é uma porta de enumeração. O «@» afirma-se sobre o CARTÃO; o
    endereço, sobre o ecrã todo."""
    assert _EMAIL_DO_CLIENTE not in cartao["ecraTodo"], cartao["ecraTodo"][:600]
    assert "@" not in cartao["porEmail"], cartao["porEmail"][:600]


def test_voltar_ao_papel_pede_ao_SERVIDOR_e_so_depois_muda_o_ecra(cartao):
    """A preferência é do cliente e vive na app: quem a grava é o servidor."""
    assert cartao["corposPreferencia"][0] == {
        "venda_id": "v-1", "ligacao_id": "lig-1", "valor": False}
    assert "Pontos para: Ana ✓ · Fatura em papel" in cartao["noPapel"], \
        cartao["noPapel"][:600]
    assert "Enviar por email" in cartao["noPapel"], cartao["noPapel"][:600]
    assert cartao["guardada"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}


def test_uma_RECUSA_do_servidor_nao_mente_no_cartao(cartao):
    """O toque em «Enviar por email» com a app a recusar não pode deixar o
    cartão a prometer email: quem vier a seguir lê a promessa, não o toast."""
    assert cartao["corposPreferencia"][1] == {
        "venda_id": "v-1", "ligacao_id": "lig-1", "valor": True}
    assert "Fatura em papel" in cartao["depoisDaRecusa"], \
        cartao["depoisDaRecusa"][:600]
    assert "Fatura por email" not in cartao["depoisDaRecusa"], \
        cartao["depoisDaRecusa"][:600]
    assert cartao["guardadaDepois"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}


def test_o_cartao_escreve_o_que_o_SERVIDOR_devolveu_e_nao_o_que_se_pediu(cartao):
    """**O caso que mata a escrita optimista.** Aqui o pedido é `true` e a
    resposta é 200 com `false` — a app já tinha desligado a preferência pelo
    telemóvel, ou o valor de lá é outro. Um `mudarLigacao({ ...ligacao,
    fatura_por_email: valor })` deixava o cartão a prometer email com a app a
    dizer o contrário, e passava nos outros CINCO testes do cartão — contados
    um a um: o inicial, o do endereço, o «voltar ao papel», o do corpo do
    EMITIR, e a RECUSA, onde o `await` rebenta ANTES da escrita e por isso o
    cartão fica certo por acidente."""
    assert cartao["corposPreferencia"][2] == {
        "venda_id": "v-1", "ligacao_id": "lig-1", "valor": True}
    assert "Fatura em papel" in cartao["depoisDaDivergencia"], \
        cartao["depoisDaDivergencia"][:600]
    assert "Fatura por email" not in cartao["depoisDaDivergencia"], \
        cartao["depoisDaDivergencia"][:600]
    assert cartao["guardadaDivergente"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}


def test_a_preferencia_NAO_viaja_no_corpo_do_EMITIR(cartao):
    """**A decisão de não imprimir um documento fiscal não pode vir do corpo de
    um pedido do browser.** O servidor lê a preferência do `fat_pontos_qr` que
    é dele; o `pontos_ligacao` continua a ser os mesmos dois campos de sempre —
    um campo a mais aqui era um documento a desaparecer com um curl."""
    assert cartao["emitirVivo"] is True
    assert len(cartao["corpos"]) == 1, cartao["corpos"]
    assert cartao["corpos"][0]["pontos_ligacao"] == {
        "id": "lig-1", "primeiro_nome": "Ana"}


# --- A resposta que chega depois de o cliente já ter saído do ecrã ------------


@pytest.fixture(scope="module")
def tardia(tmp_path_factory):
    """Carrega no botão da preferência e, **com o pedido ainda em voo**, tira o
    cliente da fatura pelo «Remover». Só depois é que o servidor responde — a
    dizer que sim, que ficou por email."""
    cenario = _no_finalizar("\n".join([
        # A preferência começa DESLIGADA: o botão diz «Enviar por email», e o
        # que o servidor vai responder (`true`) é a resposta mais perigosa que
        # há — a que, escrita às cegas, põe o cliente de volta no cartão a
        # prometer um email que ninguém pediu.
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {",
        "  ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: false,",
        "  email: %s } });" % json.dumps(_EMAIL_DO_CLIENTE),
        # Fica pendurada até ao `soltar`: é a única maneira de pôr o dedo da
        # operadora ENTRE o pedido e a resposta, que é onde o defeito vive.
        "let soltar = null;",
        "RESPOSTAS_POS['POST /pos/pontos/preferencia'] =",
        "  () => new Promise((r) => { soltar = r; });",
    ]))
    return _correr("\n".join([
        cenario,
        "const temCartao = () => !!alvo.querySelector('[data-testid=\"cartao-pontos\"]');",
        # O «Remover» DO CARTÃO, e vivo. Scoped ao cartão porque é ali que o
        # defeito se fecharia à martelada — desligar o botão enquanto o pedido
        # voa fecha esta porta e deixa a outra (trocar de conta) aberta, e de
        # caminho prende a mão da operadora a um pedido que não é dela.
        "const removerVivo = () => [...alvo.querySelectorAll(",
        "  '[data-testid=\"cartao-pontos\"] button')].find(",
        "  (b) => (b.textContent || '').includes('Remover') && !b.disabled);",
        "await carregar_em('Ler QR do cliente');",
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "await carregar_em('Enviar por email');",
        "const removerEstavaVivo = !!removerVivo();",
        "if (removerEstavaVivo) await act(async () => { removerVivo().click(); });",
        "const cartaoLogoAposRemover = temCartao();",
        # E agora o servidor responde — tarde, e a dizer que sim.
        "await act(async () => { soltar({ data: { fatura_por_email: true } }); });",
        "await act(async () => {});",
        "const cartaoDepoisDaResposta = temCartao();",
        "const ecraDepois = textoVisivel(alvo);",
        "const guardadaDepois = lib.lerPontosDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ removerEstavaVivo,",
        "  cartaoLogoAposRemover, cartaoDepoisDaResposta, ecraDepois,",
        "  guardadaDepois, emitirVivo, corpos }));",
    ]), tmp_path_factory, "tardia-email")


def test_o_Remover_fica_vivo_enquanto_a_preferencia_esta_em_voo(tardia):
    """Tirar o cliente da fatura não espera pela app. O pedido da preferência
    é do cliente; o «Remover» é da operadora, e a fila é dela."""
    assert tardia["removerEstavaVivo"] is True
    assert tardia["cartaoLogoAposRemover"] is False


def test_uma_resposta_TARDIA_nao_ressuscita_o_cliente_ja_removido(tardia):
    """**O cartão a dizer uma coisa e a verdade ser outra, desta vez pelo
    relógio.** Com o pedido em voo e o cliente já removido, um
    `mudarLigacao({ ...ligacao, ... })` a seguir ao `await` escrevia a ligação
    capturada no instante do toque: o cliente voltava ao cartão, à gaveta
    `pos_pontos_da_conta`, e daí ao `pontos_ligacao` do EMITIR — pontos para
    uma pessoa que a operadora tinha acabado de tirar da fatura."""
    assert tardia["cartaoDepoisDaResposta"] is False, tardia["ecraDepois"][:600]
    assert "Ler QR do cliente" in tardia["ecraDepois"], tardia["ecraDepois"][:600]
    assert "Pontos para: Ana" not in tardia["ecraDepois"], tardia["ecraDepois"][:600]
    assert tardia["guardadaDepois"] is None
    assert tardia["emitirVivo"] is True
    assert len(tardia["corpos"]) == 1, tardia["corpos"]
    assert tardia["corpos"][0]["pontos_ligacao"] is None, tardia["corpos"][0]
