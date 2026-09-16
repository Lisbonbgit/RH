"""**Nove dígitos não são um NIF.**

Queixa de uma colaboradora, com fotografia do ecrã (2026-09-11): ao emitir uma
conta de 18,44 € para o cliente `219 363 931`, o balcão levou com isto à frente
do cliente —

    O Vendus não respondeu — não saiu nenhum documento.
    Vendus HTTP 400: {"errors":[{"code":"A001","message":"Unable to create
    client - NIF português inválido...

`219 363 931` é um **telefone fixo de Lisboa**. O ecrã aceitou-o (contava nove
dígitos e mais nada), mostrou-o formatado e a negrito como se fosse um cliente
válido, e acendeu o EMITIR. Quem disse que não foi o Vendus, no fim, com a
venda toda feita. Medido em produção nesse dia: 651 emissões em 4 dias, 4
falhadas — cerca de uma por dia, em cinco lojas.

O que este ficheiro guarda é o ecrã: a pergunta «este número existe?» passa a
ser feita ENQUANTO o cliente ainda está à frente para a repetir. A guarda a
sério é a do servidor (`test_fiscal.py::test_o_TELEFONE_...`) — qualquer curl
chega à rota na mesma —, e esta é a que poupa a viagem.

**O que este ficheiro NÃO cobre, dito com todas as letras.** O que se vê
mede-se com a folha de estilo à mão do preâmbulo; esconder a frase por outro
caminho (opacidade, largura zero) passa por aqui sem acordar ninguém. E o
`disabled` do EMITIR prova-se pelo atributo, não pelo pixel.
"""
import json
from pathlib import Path

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_arredondamento_do_ecra import _corpo_da_funcao, _corpo_da_seta, _ler
from .test_as_fotos_no_ecra import _COMPONENTES as _COMPONENTES_COM_ID

_POS_FINALIZAR = (Path(__file__).resolve().parents[3]
                  / "frontend" / "src" / "pages" / "pos" / "PosFinalizar.js")


# --- Nível 1: a aritmética, corrida a sério ----------------------------------

def _nif_valido(nif, tmp_path):
    saida = _montar_no_node("\n".join([
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "process.stdout.write(JSON.stringify({ valido: lib.nifValidoPT(%s) }));"
        % json.dumps(nif),
    ]), tmp_path, "nif-valido.js")
    return saida["valido"]


@pytest.mark.parametrize("nif", ["123456789", "500000000", "517542510", "295258144",
                                 "219363935", "123 456 789"])
def test_um_NIF_a_SERIO_passa(nif, tmp_path):
    """Os que já vivem na suite, o da própria casa, um lido em produção — e o
    telefone da queixa com o dígito de controlo certo (5), que é a prova de que
    quem recusa é a aritmética e não o prefixo: `21` é um começo legítimo de
    NIF de pessoa singular."""
    assert _nif_valido(nif, tmp_path) is True


@pytest.mark.parametrize("nif", ["219363931", "111111111", "000000000",
                                 "12345", "", "1234567890"])
def test_o_que_NAO_e_um_NIF_e_apanhado(nif, tmp_path):
    """`219363931` é a queixa. `111111111` é a armadilha do resto 0 (o resto 0
    e o resto 1 dão os dois controlo 0). `000000000` passa o módulo 11 e não
    existe — nenhum NIF português começa por zero."""
    assert _nif_valido(nif, tmp_path) is False


# --- O tecto do campo: nove DÍGITOS, não onze caracteres ---------------------

def _escrito(texto, tmp_path):
    """Corre o `nifAteNove` do próprio ecrã, extraído do ficheiro de produção
    (o padrão da casa: a decisão corre, não se relê)."""
    corpo = _corpo_da_funcao(
        _ler(_POS_FINALIZAR), "const nifAteNove = (texto) =>", _POS_FINALIZAR)
    saida = _montar_no_node("\n".join([
        corpo,
        "process.stdout.write(JSON.stringify({ fica: nifAteNove(%s) }));"
        % json.dumps(texto),
    ]), tmp_path, "nif-ate-nove.js")
    return saida["fica"]


@pytest.mark.parametrize("escrito,fica", [
    ("219 363 935", "219 363 935"),    # como ela escreve, aos grupos de três
    ("2193639311", "219363931"),       # o décimo dígito não entra
    (" 219 363 935", " 219 363 935"),  # um espaço a mais à frente não come nada
    ("219  363 935", "219  363 935"),  # nem um espaço duplo pelo meio
    ("219a363b935", "219363935"),      # letras nunca
])
def test_o_campo_conta_DIGITOS_e_nao_caracteres(escrito, fica, tmp_path):
    """O tecto era de 11 CARACTERES. Com um espaço a mais, o nono dígito era
    engolido em silêncio e o ecrã ficava a pedir «faltam 1» enquanto as teclas
    não faziam nada; com o teclado do PC entravam dez e onze dígitos, e aí o
    ecrã pedia «faltam -1»."""
    assert _escrito(escrito, tmp_path) == fica


# --- Nível 2: o ecrã montado, e o que a operadora LÊ -------------------------

# A biblioteca de UI mínima que responde ao dedo — a mesma técnica do
# `test_o_separador_de_faturacao_no_ecra.py`. Sem um `<button>` a sério, o
# `disabled` do EMITIR não existe em lado nenhum e o guarda media metade.
_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled, type: 'button',",
    "  'data-desligado': props.disabled ? 'sim' : 'nao',",
    "}, props.children);",
    "const Campo = (props) => React.createElement('input', {",
    "  value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, placeholder: props.placeholder,",
    "});",
    "const Div = (props) => React.createElement('div', null, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button') return Botao;",
    "  if (nome === 'Input') return Campo;",
    "  return Div;",
    "} });",
])

_VENDA = ("{ id: 'v1', estado: 'aberta', totais: { total: 18.44 }, "
          "linhas: [{ id: 'l1', nome: 'Açaí', quantidade: 1, total: 18.44 }] }")


@pytest.fixture(scope="module")
def finalizar_com_nif(tmp_path_factory):
    """O `PosFinalizar` montado três vezes — com o telefone da queixa, com um
    NIF a sério e sem NIF nenhum. O NIF entra como entra na vida real: já
    guardado para esta conta (`lib/pos.js::guardarNifDaConta`), que é o que o
    ecrã lê ao abrir."""
    cenario = "\n".join([
        _COMPONENTES,
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "const Finalizar = carregar(path.join(POS, 'PosFinalizar.js')).default;",
        "const VENDA = %s;" % _VENDA,
        "async function ecraCom(nif) {",
        "  sessionStorage.clear();",
        "  if (nif) lib.guardarNifDaConta('v1', nif);",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(Finalizar, {",
        # `pronto: true` — um tipo por ligar ao Vendus desenha-se morto, de
        # propósito (ver `BotaoTipo`), e não havia como escolher nada.
        "    venda: VENDA,",
        "    tiposPagamento: [{ id: 't1', nome: 'Dinheiro', pronto: true }],",
        "    onVoltar: () => {}, onEmitir: () => {}, onAplicarDesconto: () => {},",
        "  })); });",
        "  await act(async () => {});",
        # O dedo na forma de pagamento: sem ele o EMITIR fica cinzento por
        # OUTRA razão («Escolha como o cliente vai pagar») e o guarda do NIF
        # media um botão que já estava morto — verde por engano.
        "  const dinheiro = Array.from(alvo.querySelectorAll('button'))",
        "    .find((b) => /Dinheiro/.test(b.textContent || ''));",
        "  if (!dinheiro) throw new Error('Sem botão de pagamento no ecrã montado.');",
        "  await act(async () => { dinheiro.click(); });",
        "  await act(async () => {});",
        "  const botao = Array.from(alvo.querySelectorAll('button'))",
        "    .find((b) => /EMITIR DOCUMENTO/i.test(b.textContent || ''));",
        "  const saida = { visivel: textoVisivel(alvo),",
        "    emitir: botao ? botao.getAttribute('data-desligado') : 'SEM BOTÃO' };",
        "  await act(async () => { raiz.unmount(); });",
        "  alvo.innerHTML = '';",
        "  return saida;",
        "}",
        "(async () => {",
        "  const saida = {};",
        "  saida.telefone = await ecraCom('219363931');",
        "  saida.aSerio = await ecraCom('219363935');",
        "  saida.semNif = await ecraCom('');",
        "  saida.aMeio = await ecraCom('2193');",
        "  saida.digitosAMais = await ecraCom('2193639311');",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("finalizar-nif"), "montar-finalizar-nif.js"
    )


def test_o_ecra_DIZ_a_operadora_que_aquele_numero_nao_e_um_NIF(finalizar_com_nif):
    """A frase que faltava. Antes, o ecrã não tinha estado nenhum entre «NIF
    por terminar» e «cliente válido»: nove dígitos errados apareciam a negrito,
    formatados, exactamente como um NIF bom."""
    ecra = finalizar_com_nif["telefone"]
    assert "219 363 931" in ecra["visivel"], (
        "Não é o ecrã de finalizar com o NIF da queixa que está montado. "
        "O que lá ficou: %r" % ecra["visivel"][:400]
    )
    # A frase do CARTÃO, palavra por palavra, e não «não é um NIF válido» solto:
    # essa também sai do rodapé do EMITIR, e um guarda que a procurasse no ecrã
    # inteiro ficava verde com o cartão de volta a mostrar o telefone a negrito,
    # como cliente válido — que é exactamente o estado da queixa.
    assert "Este número não é um NIF válido — confirme-o com o cliente." in ecra["visivel"], (
        "O cartão do Cliente não diz nada sobre o número que ela escreveu — "
        "mostra-o como se fosse um cliente. O ecrã: %r" % ecra["visivel"][:400]
    )
    assert "Corrigir o NIF" in ecra["visivel"], (
        "As duas saídas não estão no cartão fechado: ela tem de descobrir "
        "sozinha que o problema se resolve dentro do lápis."
    )


def test_o_EMITIR_esta_MORTO_com_o_telefone_escrito(finalizar_com_nif):
    """A frase sem o botão travado não vale nada: era exactamente assim que o
    219 363 931 chegava ao Vendus."""
    assert finalizar_com_nif["telefone"]["emitir"] == "sim", (
        "O EMITIR DOCUMENTO continua aceso com um telefone escrito no lugar do "
        "NIF — o defeito da queixa está de pé."
    )


def test_um_NIF_a_SERIO_nao_leva_aviso_nenhum_e_o_EMITIR_acende(finalizar_com_nif):
    """**O guarda contra o crivo apertado de mais.** Um aviso que aparecesse a
    toda a gente ensinava a operadora a passar-lhe por cima, e um EMITIR
    cinzento por uma razão que o servidor aceitaria é pior do que o defeito
    que se está a corrigir. É o mesmo número da queixa com o dígito de
    controlo certo."""
    ecra = finalizar_com_nif["aSerio"]
    assert "219 363 935" in ecra["visivel"]
    assert "não é um NIF válido" not in ecra["visivel"], (
        "O ecrã recusa um NIF que a aritmética aceita. %r" % ecra["visivel"][:400]
    )
    assert ecra["emitir"] == "nao", "O EMITIR ficou morto com um NIF válido."


def test_com_o_NIF_A_MEIO_a_frase_e_a_OUTRA(finalizar_com_nif):
    """**A ordem das duas frases.** Com «2193» escrito ninguém pode levar «não
    é um NIF válido» — ela ainda não acabou de o escrever, e dizer-lhe a coisa
    errada cedo de mais ensina-a a passar por cima do aviso todo. Sem este
    caso, trocar as duas frases de lugar não partia teste nenhum."""
    ecra = finalizar_com_nif["aMeio"]
    assert "por terminar" in ecra["visivel"], (
        "O NIF a meio deixou de ter a sua frase. %r" % ecra["visivel"][:400]
    )
    assert "não é um NIF válido" not in ecra["visivel"], (
        "Com quatro dígitos escritos o ecrã já diz que o número não existe. %r"
        % ecra["visivel"][:400]
    )
    assert ecra["emitir"] == "sim"


def test_um_NIF_com_digitos_a_MAIS_nao_manda_acrescentar_mais(finalizar_com_nif):
    """Dez dígitos guardados de antes deste remendo (o campo já não os deixa
    escrever). O ecrã dizia «10 de 9 dígitos» e «faltam -1» — a mandá-la
    acrescentar a um número que já tinha demais, sem uma tecla que o fizesse."""
    ecra = finalizar_com_nif["digitosAMais"]
    assert "não é um NIF válido" in ecra["visivel"]
    assert "de 9 dígitos" not in ecra["visivel"], (
        "O ecrã continua a contar até nove sobre um número que tem dez. %r"
        % ecra["visivel"][:400]
    )
    assert ecra["emitir"] == "sim"


def test_sem_NIF_continua_a_ser_Consumidor_Final(finalizar_com_nif):
    """A maioria esmagadora das vendas. Um crivo que tratasse o campo vazio
    como erro fechava o balcão."""
    ecra = finalizar_com_nif["semNif"]
    assert "Consumidor Final" in ecra["visivel"]
    assert "não é um NIF válido" not in ecra["visivel"]
    assert ecra["emitir"] == "nao", (
        "O EMITIR ficou morto numa venda sem NIF — é a venda mais comum de todas."
    )


# --- O leitor de QR com o foco no campo do NIF --------------------------------
#
# Os pontos L'Açaí passam a ganhar-se a mostrar o QR da app na caixa, e o
# leitor do POS HP é um TECLADO: escreve `LQ` + 22 letras e dígitos, uma tecla
# de cada vez, e dá Enter. Com o foco no NIF por engano, cada tecla chega ao
# `onChange` sozinha — e ignorar só as alterações com letras deixava entrar os
# dígitos do código, um a um, no NIF da fatura. Uma fatura real à AT com um
# NIF feito de pedaços de um QR.

_CODIGO_DO_QR = "LQ7K2MN8P3QRSTUV4WXYZ9AB"


def _no_campo(inicial, teclas, tmp_path):
    """Corre o `escritaNoNif` do próprio ecrã sobre `teclas` —
    `[[tecla, ms desde a anterior], ...]` — como o browser as entrega: cada
    uma acrescentada ao que o campo tem. Devolve o que fica no campo."""
    ecra = _ler(_POS_FINALIZAR)
    saida = _montar_no_node("\n".join([
        _corpo_da_funcao(ecra, "const nifAteNove = (texto) =>", _POS_FINALIZAR),
        _corpo_da_seta(ecra, "const ESPERA_DO_LEITOR_MS =", _POS_FINALIZAR),
        _corpo_da_funcao(
            ecra, "const escritaNoNif = (texto, agora, fechadoAte) =>", _POS_FINALIZAR),
        "let campo = %s;" % json.dumps(inicial),
        "let fechadoAte = 0;",
        "let agora = 1000;",
        "for (const [tecla, passou] of %s) {" % json.dumps(teclas),
        "  agora += passou;",
        "  const escrita = escritaNoNif(campo + tecla, agora, fechadoAte);",
        "  fechadoAte = escrita.fechadoAte;",
        "  if (escrita.texto !== null) campo = escrita.texto;",
        "}",
        "process.stdout.write(JSON.stringify({ campo }));",
    ]), tmp_path, "escrita-no-nif.js")
    return saida["campo"]


@pytest.mark.parametrize("inicial", ["", "5175"])
def test_o_QR_escrito_pelo_leitor_no_campo_do_NIF_nao_deixa_la_nenhum_digito(inicial, tmp_path):
    """A rajada do leitor: 15 ms entre teclas. Nem as letras nem os dígitos do
    código entram — com o NIF vazio ou a meio."""
    teclas = [[tecla, 15] for tecla in _CODIGO_DO_QR]
    assert _no_campo(inicial, teclas, tmp_path) == inicial, (
        "Os dígitos do QR entraram no NIF da fatura.")


def test_depois_de_uma_letra_por_engano_a_mao_volta_a_escrever_passado_meio_segundo(tmp_path):
    """O fecho não pode prender quem escreveu uma letra à mão: meio segundo
    depois, o campo aceita outra vez."""
    assert _no_campo("5175", [["a", 0], ["6", 600]], tmp_path) == "51756"


def test_digitos_e_espacos_escritos_a_mao_continuam_a_entrar(tmp_path):
    """O guarda contra o crivo apertado de mais: a escrita normal, aos grupos
    de três, com o ritmo de um dedo."""
    teclas = [[tecla, 150] for tecla in "219 363 935"]
    assert _no_campo("", teclas, tmp_path) == "219 363 935"


@pytest.fixture(scope="module")
def leitor_no_nif(tmp_path_factory):
    """O `PosFinalizar` montado com o editor do NIF ABERTO — o sítio errado
    para o leitor escrever. Primeiro uma tecla à mão (a prova de que escrever
    no campo funciona nesta montagem: sem ela, um campo que não aceitasse
    nada deixava o guarda verde), depois a rajada do QR."""
    cenario = "\n".join([
        _COMPONENTES_COM_ID,
        # O teclado do NIF vem do PosCampoValor, que o preâmbulo substitui por
        # uma marca; sem o verdadeiro, abrir o editor rebentava.
        "SUBSTITUIDOS.delete(path.join(POS, 'PosCampoValor.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "const Finalizar = carregar(path.join(POS, 'PosFinalizar.js')).default;",
        "function escrever(el, valor) {",
        "  Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value')",
        "    .set.call(el, valor);",
        "  el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));",
        "}",
        "(async () => {",
        "  sessionStorage.clear();",
        "  lib.guardarNifDaConta('v1', '5175');",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(Finalizar, {",
        "    venda: %s," % _VENDA,
        "    tiposPagamento: [{ id: 't1', nome: 'Dinheiro', pronto: true }],",
        "    onVoltar: () => {}, onEmitir: () => {}, onAplicarDesconto: () => {},",
        "  })); });",
        "  await act(async () => {});",
        "  const terminar = [...alvo.querySelectorAll('button')]",
        "    .find((b) => (b.textContent || '').includes('Terminar o NIF'));",
        "  if (!terminar) throw new Error('sem o botão Terminar o NIF: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  await act(async () => { terminar.click(); });",
        "  const campo = () => alvo.querySelector('#nif-cliente');",
        "  if (!campo()) throw new Error('o editor do NIF não abriu: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  await act(async () => { escrever(campo(), campo().value + '6'); });",
        "  const aMao = campo().value;",
        "  for (const tecla of %s) {" % json.dumps(_CODIGO_DO_QR),
        "    await act(async () => { escrever(campo(), campo().value + tecla); });",
        "  }",
        "  const depoisDoLeitor = campo().value;",
        "  await act(async () => { raiz.unmount(); });",
        "  process.stdout.write(JSON.stringify({ aMao, depoisDoLeitor }));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("leitor-no-nif"), "montar-leitor-no-nif.js")


def test_no_ecra_montado_uma_tecla_a_mao_entra_no_NIF(leitor_no_nif):
    assert leitor_no_nif["aMao"] == "51756", (
        "Escrever no campo não funciona nesta montagem — o guarda seguinte "
        "mediria o vazio.")


def test_no_ecra_montado_o_QR_do_leitor_nao_mexe_no_NIF(leitor_no_nif):
    """O fio entre a regra e o campo: um `onChange` que voltasse a chamar o
    `nifAteNove` directamente punha aqui `517567283`."""
    assert leitor_no_nif["depoisDoLeitor"] == "51756", (
        "O leitor escreveu no NIF: %r" % leitor_no_nif["depoisDoLeitor"])
