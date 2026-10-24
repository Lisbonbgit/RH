"""**O NIF da conta da app no cartão Cliente** — montado e tocado, não lido.

Cerca de um terço das faturas das lojas leva NIF, e o NIF é sempre ditado e
escrito à mão: é por aí que entram os enganos (um telefone escrito como NIF
dava uma recusa do Vendus por dia). Quem mostra o QR da app na caixa já tem,
muitas vezes, o NIF na conta — e a leitura passa a trazê-lo.

As decisões do dono que isto guarda (spec de 2026-10-24):

- **perguntar sempre, nunca preencher sozinho** — um botão «Usar o NIF da app
  · 2•• ••• •35» no cartão Cliente, e uma fatura sem toque sai sem NIF;
- **o NIF aparece escondido**, no botão e no cartão depois do toque: o ecrã da
  caixa está virado para a fila;
- **o «Remover» tira o NIF se ainda for o da app**, e deixa ficar o que a
  operadora mudou;
- **um NIF já escrito não se tapa**, e uma conta repartida não o passa às
  partes.

Pelo `PosVenda` montado e pelas DUAS portas da leitura — o «Ler QR do cliente»
do cartão e a pergunta do FINALIZAR —, com o servidor fabricado à frente do
axios: o que se afirma é o que a operadora LÊ e o CORPO do EMITIR.
"""
import json

import pytest

from .test_o_dividir_e_o_separar_no_ecra import (
    _COOKIE, _L_ACAI, _L_COOKIE, _conta, _correr, _linha)
from .test_os_pontos_no_ecra_do_pos import (
    _CODIGO, _EMITIR, _PARTE_ACAI, _PARTE_COOKIE, _RESTO, _na_pergunta, _no_finalizar)

# O telefone da queixa de 2026-09-11 com o dígito de controlo certo
# (test_o_nif_que_nao_existe_no_pos.py) — e um segundo NIF, o que a operadora
# escreve à mão.
_NIF = "219363935"
_MASCARA = "2•• ••• •35"
_OUTRO_NIF = "517542510"

_LER_COM_NIF = (
    "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {"
    " ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: false,"
    " nif: %s } });" % json.dumps(_NIF))

# O cartão Cliente SOZINHO — a secção com o título «Cliente». «Consumidor
# Final» também é um botão do editor, e um guarda que lesse o ecrã inteiro
# media outra coisa.
_OLHAR = "\n".join([
    "const seccaoCliente = () => [...alvo.querySelectorAll('section')].find(",
    "  (s) => (s.querySelector('p') || {}).textContent === 'Cliente');",
    "const cartaoCliente = () => {",
    "  const el = seccaoCliente();",
    "  if (!el) throw new Error('sem cartão Cliente no ecrã: '",
    "    + textoVisivel(alvo).slice(0, 400));",
    "  return textoVisivel(el);",
    "};",
])

# As DUAS portas. Pelo cartão, o `_arranque` já respondeu «Não» à pergunta e a
# operadora carrega em «Ler QR do cliente»; pela pergunta, o QR lê-se na
# janela que o FINALIZAR abre e o ecrã de pagamento apanha a ligação da gaveta
# ao montar. São caminhos diferentes até ao `CartaoCliente`, e só um deles
# passa pelo `onLigada` do `PosFinalizar`.
_PORTAS = {
    "cartao": (_no_finalizar, "await carregar_em('Ler QR do cliente');"),
    "pergunta": (_na_pergunta, ""),
}


def _lido_com_nif(porta, extra=""):
    arranque, abrir = _PORTAS[porta]
    return "\n".join([
        arranque("\n".join([_LER_COM_NIF, extra])),
        _OLHAR,
        abrir,
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
    ])


@pytest.fixture(scope="module", params=sorted(_PORTAS))
def sem_toque(request, tmp_path_factory):
    """O QR lido, o botão à vista — e ninguém lhe toca."""
    return _correr("\n".join([
        _lido_com_nif(request.param),
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        "const html = alvo.innerHTML;",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ noCartao, visivel, html, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-sem-toque-" + request.param)


@pytest.fixture(scope="module", params=sorted(_PORTAS))
def com_toque(request, tmp_path_factory):
    """O QR lido e o cliente a dizer que sim: um toque no botão."""
    return _correr("\n".join([
        _lido_com_nif(request.param),
        "await carregar_em('Usar o NIF da app');",
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        "const html = alvo.innerHTML;",
        "const nifGuardado = lib.lerNifDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noCartao, visivel, html, nifGuardado, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-com-toque-" + request.param)


def test_o_botao_aparece_com_o_NIF_ESCONDIDO_e_o_numero_inteiro_nao_esta_no_ecra(sem_toque):
    """O ecrã da caixa está virado para a fila: o número inteiro não se lê, nem
    junto nem aos grupos de três — e não está no DOM, nem num atributo."""
    assert "Usar o NIF da app · " + _MASCARA in sem_toque["noCartao"], sem_toque["noCartao"]
    assert "Consumidor Final" in sem_toque["noCartao"], sem_toque["noCartao"]
    for inteiro in (_NIF, "219 363 935"):
        assert inteiro not in sem_toque["visivel"], sem_toque["visivel"][:600]
        assert inteiro not in sem_toque["html"]


def test_sem_tocar_no_botao_a_fatura_sai_SEM_NIF(sem_toque):
    """**Perguntar sempre, nunca preencher sozinho.** Muitos clientes não
    querem NIF na fatura, e uma Fatura Simplificada com um NIF que ninguém
    pediu só se corrige com nota de crédito. Os pontos seguem na mesma."""
    assert sem_toque["emitirVivo"] is True
    assert len(sem_toque["corpos"]) == 1, sem_toque["corpos"]
    corpo = sem_toque["corpos"][0]
    assert corpo["nif"] is None, corpo
    assert corpo["pontos_ligacao"] == {"id": "lig-1", "primeiro_nome": "Ana"}, corpo


def test_um_toque_poe_o_NIF_da_app_no_cartao_e_ele_continua_ESCONDIDO(com_toque):
    """Depois do toque o cartão diz que há NIF — mascarado, como no botão — e o
    botão sai. O NIF fica na gaveta do NIF desta conta, como um NIF ditado: é
    isso que o faz sobreviver a voltar à conta para juntar mais um artigo."""
    assert _MASCARA in com_toque["noCartao"], com_toque["noCartao"]
    assert "Usar o NIF da app" not in com_toque["noCartao"], com_toque["noCartao"]
    assert "Consumidor Final" not in com_toque["noCartao"], com_toque["noCartao"]
    for inteiro in (_NIF, "219 363 935"):
        assert inteiro not in com_toque["visivel"], com_toque["visivel"][:600]
        assert inteiro not in com_toque["html"]
    assert com_toque["nifGuardado"] == _NIF


def test_depois_do_toque_o_EMITIR_leva_o_NIF_no_campo_de_sempre_e_nunca_nos_pontos(com_toque):
    """O NIF viaja no `nif` de sempre e o servidor valida-o como a qualquer
    outro (`fiscal.py::_valida_nif`). O `pontos_ligacao` continua a ser os dois
    campos de sempre: um NIF lá dentro ficava gravado na venda."""
    assert com_toque["emitirVivo"] is True
    assert len(com_toque["corpos"]) == 1, com_toque["corpos"]
    corpo = com_toque["corpos"][0]
    assert corpo["nif"] == _NIF, corpo
    assert corpo["pontos_ligacao"] == {"id": "lig-1", "primeiro_nome": "Ana"}, corpo


# --- O «Remover» do cartão dos pontos -----------------------------------------


@pytest.fixture(scope="module")
def remover_sem_mexer(tmp_path_factory):
    """O NIF da app usado, e o cliente tirado da fatura logo a seguir."""
    return _correr("\n".join([
        _lido_com_nif("cartao"),
        "await carregar_em('Usar o NIF da app');",
        "await carregar_em('Remover');",
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        "const nifGuardado = lib.lerNifDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noCartao, visivel, nifGuardado, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-remover")


@pytest.fixture(scope="module")
def remover_editado(tmp_path_factory):
    """O NIF da app usado e depois MUDADO pela operadora (o cliente quis o da
    empresa), e só então o «Remover»."""
    return _correr("\n".join([
        # O editor do NIF usa o teclado do PosCampoValor, que o preâmbulo
        # substitui por uma marca; sem o verdadeiro, abrir o lápis rebentava.
        # Antes do `_arranque`, que é onde o PosFinalizar carrega.
        "SUBSTITUIDOS.delete(path.join(POS, 'PosCampoValor.js'));",
        _lido_com_nif("cartao"),
        "await carregar_em('Usar o NIF da app');",
        # O lápis do cartão Cliente: o `Botao` do banco de ensaio deita fora o
        # `aria-label`, por isso apanha-se pelo ícone, dentro da secção.
        "const lapis = seccaoCliente().querySelector('[data-icone=\"Pencil\"]').closest('button');",
        "await act(async () => { lapis.click(); });",
        "const noEditor = alvo.querySelector('#nif-cliente').value;",
        "await act(async () => { escrever(alvo.querySelector('#nif-cliente'), %s); });"
        % json.dumps(_OUTRO_NIF),
        # O «Confirmar» DO CARTÃO, e não o primeiro do ecrã com essa palavra.
        "const confirmar = [...seccaoCliente().querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes('Confirmar'));",
        "await act(async () => { confirmar.click(); });",
        "const editorFechado = !alvo.querySelector('#nif-cliente');",
        "await carregar_em('Remover');",
        "const noCartao = cartaoCliente();",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noEditor, editorFechado, noCartao, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-remover-editado")


def test_o_Remover_tira_tambem_o_NIF_da_app_que_ninguem_mexeu(remover_sem_mexer):
    """Tirar o cliente da fatura e deixar lá o NIF dele era meia remoção: a
    fatura saía em nome de quem a funcionária acabou de tirar."""
    r = remover_sem_mexer
    assert "Consumidor Final" in r["noCartao"], r["noCartao"]
    assert _MASCARA not in r["visivel"], r["visivel"][:600]
    assert "Usar o NIF da app" not in r["visivel"], r["visivel"][:600]
    assert r["nifGuardado"] == ""
    assert r["corpos"][0]["nif"] is None, r["corpos"][0]
    assert r["corpos"][0]["pontos_ligacao"] is None, r["corpos"][0]


def test_o_Remover_deixa_ficar_o_NIF_que_a_operadora_MUDOU(remover_editado):
    """Um NIF mudado à mão deixou de ser o da app: é da operadora, e o
    «Remover» dos pontos não lhe toca. E o lápis mostra os dígitos — abri-lo é
    uma acção explícita, e é lá que ela os confirma com o cliente."""
    r = remover_editado
    assert r["noEditor"] == _NIF
    assert r["editorFechado"] is True
    assert "517 542 510" in r["noCartao"], r["noCartao"]
    assert r["corpos"][0]["nif"] == _OUTRO_NIF, r["corpos"][0]
    assert r["corpos"][0]["pontos_ligacao"] is None, r["corpos"][0]


# --- Um NIF já escrito não se tapa --------------------------------------------


@pytest.fixture(scope="module")
def nif_escrito_antes(tmp_path_factory):
    """O cliente ditou um NIF ANTES de mostrar a app."""
    return _correr("\n".join([
        _lido_com_nif("cartao", "lib.guardarNifDaConta('v-1', %s);" % json.dumps(_OUTRO_NIF)),
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ noCartao, visivel, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-escrito-antes")


def test_com_um_NIF_ja_escrito_nao_ha_botao_e_a_fatura_leva_o_ESCRITO(nif_escrito_antes):
    """O que a operadora escreveu não se substitui por baixo dela — nem com um
    botão a convidar a isso. E de propósito sem aviso nenhum sobre a diferença
    (decisão do dono)."""
    r = nif_escrito_antes
    assert "Pontos para: Ana ✓" in r["visivel"], r["visivel"][:600]
    assert "Usar o NIF da app" not in r["visivel"], r["visivel"][:600]
    assert "517 542 510" in r["noCartao"], r["noCartao"]
    assert r["corpos"][0]["nif"] == _OUTRO_NIF, r["corpos"][0]


# --- A conta que se PARTE não passa o NIF da app às partes ---------------------
#
# **Nada disto é código novo no `PosVenda`, e é por isso que precisa de guarda.**
# `esquecerOsPontosDaMae` apaga a ligação (e o `nif` vai com ela), e a gaveta
# do NIF tem uma entrada só: montar o ecrã de pagamento de uma parte grava lá
# `{parte, ''}` por cima do NIF da mãe. Qualquer refactor de uma das duas
# gavetas reabria a fuga — o NIF de quem mostrou a app na fatura de outra
# pessoa — sem uma linha deste ficheiro a mudar.

_P1_EMITIDA = dict(
    _conta("p-1", [_linha("x1", "p-cookie", _COOKIE, 3.80)], estado="emitida", mae="v-1"),
    documento={"id": "d-2", "numero": "FS 01P2026/98", "atcud": "A-98",
               "total": 3.80, "modo": "normal", "vendus_document_id": 2},
)

_EMITIR_A_PARTE = "\n".join([
    "await carregar_em('Dinheiro');",
    "await carregar_em('EMITIR DOCUMENTO');",
    "await act(async () => {});",
])


@pytest.fixture(scope="module")
def dividir_depois_do_toque(tmp_path_factory):
    """Pela pergunta do FINALIZAR: o QR lido, o NIF da app usado, e a conta
    dividida."""
    return _correr("\n".join([
        _lido_com_nif("pergunta", "\n".join([
            "RESPOSTAS_POS['POST /pos/venda/v-1/dividir'] = () => ({ data: %s });"
            % json.dumps({
                "modo": "dividir",
                "conta_mae": _conta("v-1", [_L_COOKIE, _L_ACAI], estado="separada"),
                "partes": [_PARTE_COOKIE, _PARTE_ACAI],
            }, ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/p-1/finalizar'] = () => ({ data: %s });"
            % json.dumps(_P1_EMITIDA, ensure_ascii=False),
        ])),
        "await carregar_em('Usar o NIF da app');",
        "const naMae = cartaoCliente();",
        "await carregar_em('Dividir Conta');",
        "const naParte = cartaoCliente();",
        "const visivelNaParte = textoVisivel(alvo);",
        _EMITIR_A_PARTE,
        "process.stdout.write(JSON.stringify({ naMae, naParte, visivelNaParte,",
        "  corpos: pedidos.filter((p) => p.url.endsWith('/pos/venda/p-1/finalizar'))",
        "    .map((p) => p.corpo) }));",
    ]), tmp_path_factory, "nif-da-app-dividir")


@pytest.fixture(scope="module")
def separar_depois_do_toque(tmp_path_factory):
    """Pelo cartão: o QR lido, o NIF da app usado, uma parte separada e
    cobrada — e o RESTO, que é a MESMA conta v-1 onde o NIF foi posto."""
    return _correr("\n".join([
        _lido_com_nif("cartao", "\n".join([
            "RESPOSTAS_POS['POST /pos/venda/v-1/separar-parte'] = () => ({ data: %s });"
            % json.dumps({"parte": _PARTE_COOKIE, "conta": _RESTO}, ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/p-1/finalizar'] = () => ({ data: %s });"
            % json.dumps(_P1_EMITIDA, ensure_ascii=False),
        ])),
        "await carregar_em('Usar o NIF da app');",
        "const naMae = cartaoCliente();",
        "await carregar_em('Separar Conta');",
        # A LINHA da conta, e não o cartão da grelha: só a linha tem o «cada».
        "const linhaDoCookie = [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(%s)" % json.dumps(_COOKIE),
        "    && (b.textContent || '').includes('cada'));",
        "if (!linhaDoCookie) throw new Error('sem linha do cookie: '",
        "  + textoVisivel(alvo).slice(0, 400));",
        "await act(async () => { linhaDoCookie.click(); });",
        "await act(async () => {});",
        "await carregar_em('COBRAR ESTA PESSOA');",
        "const naParte = cartaoCliente();",
        "const visivelNaParte = textoVisivel(alvo);",
        _EMITIR_A_PARTE,
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_RESTO, ensure_ascii=False),
        "await carregar_em('Nova Venda');",
        "await carregar_em('FINALIZAR');",
        "if (botao('Não')) await carregar_em('Não');",
        "const noResto = cartaoCliente();",
        "const visivelNoResto = textoVisivel(alvo);",
        "await carregar_em('Dinheiro');",
        "await carregar_em('EMITIR DOCUMENTO');",
        "await act(async () => {});",
        "const corpos = (id) => pedidos.filter(",
        "  (p) => p.url.endsWith('/pos/venda/' + id + '/finalizar')).map((p) => p.corpo);",
        "process.stdout.write(JSON.stringify({ naMae, naParte, visivelNaParte, noResto,",
        "  visivelNoResto, corpoDaParte: corpos('p-1'), corpoDoResto: corpos('v-1') }));",
    ]), tmp_path_factory, "nif-da-app-separar")


def test_dividir_depois_do_toque_a_parte_nao_leva_o_NIF_da_app(dividir_depois_do_toque):
    r = dividir_depois_do_toque
    assert _MASCARA in r["naMae"], "o toque não chegou a pôr o NIF na conta: %s" % r["naMae"]
    assert "Consumidor Final" in r["naParte"], r["naParte"]
    assert "Usar o NIF da app" not in r["visivelNaParte"], r["visivelNaParte"][:600]
    assert r["corpos"] and r["corpos"][0]["nif"] is None, r["corpos"]


def test_separar_depois_do_toque_nem_a_parte_nem_o_RESTO_levam_o_NIF_da_app(
        separar_depois_do_toque):
    """O resto é a MESMA conta onde o NIF foi posto, e quem o paga é outra
    pessoa: com o NIF de quem mostrou a app lá dentro, a fatura dela saía em
    nome de outro — um erro fiscal a sério, e silencioso."""
    r = separar_depois_do_toque
    assert _MASCARA in r["naMae"], "o toque não chegou a pôr o NIF na conta: %s" % r["naMae"]
    assert "Consumidor Final" in r["naParte"], r["naParte"]
    assert "Usar o NIF da app" not in r["visivelNaParte"], r["visivelNaParte"][:600]
    assert r["corpoDaParte"] and r["corpoDaParte"][0]["nif"] is None, r["corpoDaParte"]
    assert "Consumidor Final" in r["noResto"], r["noResto"]
    assert "Usar o NIF da app" not in r["visivelNoResto"], r["visivelNoResto"][:600]
    assert r["corpoDoResto"] and r["corpoDoResto"][-1]["nif"] is None, r["corpoDoResto"]
