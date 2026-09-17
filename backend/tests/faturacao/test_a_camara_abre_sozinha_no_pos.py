"""**A câmara do QR abre sozinha — e cada caixa decide se quer isso.**

Pedido do dono a 2026-09-17: «não tem como já clicar no ler qr do cliente e
abrir direto a câmara do dispositivo? para ficar mais rápido». Com o cliente à
frente e a fila atrás, um clique a menos por venda conta.

O senão é que as 5 caixas não são iguais: numa lê-se com o leitor do POS HP, que
não tem câmara nenhuma. Abrir sozinha lá significava a funcionária levar com
«Não foi possível abrir a câmara» em TODAS as vendas, sobre uma coisa que nem
estava a tentar fazer. Daí as duas regras que este ficheiro guarda:

  1. a abertura AUTOMÁTICA falha em silêncio — o erro é só para quem carregou
     no botão de propósito;
  2. a preferência é DO PC (`localStorage`, como a escolha da câmara já era), e
     há um interruptor no próprio ecrã para a loja a desligar sem chamar
     ninguém.

**O que este ficheiro NÃO cobre:** que a imagem da câmara chegue mesmo ao jsQR
e descodifique um QR. Isso é vídeo a sério e não se monta aqui; prova-se na
loja.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_CODIGO = "LQ7K2MN8P3QRSTUV4WXYZ9AB"


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    cenario = "\n".join([
        _COMPONENTES,
        # A câmara, à mão: conta as vezes que lha pedem e obedece ao guião.
        "let pedidos_camera = 0;",
        "let deixar_abrir = false;",
        # **O `navigator` do Node NÃO se substitui por atribuição.** O
        # `global.navigator = dom.window.navigator` do preâmbulo é um no-op
        # silencioso desde o Node 21: o global é um getter `configurable` e a
        # atribuição não pega. Sem isto, o ecrã via o `navigator` do NODE (sem
        # `mediaDevices`) e a câmara falava com um objecto que não era o nosso —
        # o contador ficava a zero e o teste media o vazio.
        "Object.defineProperty(globalThis, 'navigator', {",
        "  configurable: true,",
        "  value: dom.window.navigator,",
        "});",
        "Object.defineProperty(dom.window.navigator, 'mediaDevices', {",
        "  configurable: true,",
        "  value: {",
        "    getUserMedia: async () => {",
        "      pedidos_camera += 1;",
        "      if (!deixar_abrir) throw new Error('NotFoundError');",
        "      return { getTracks: () => [{ stop: () => {} }] };",
        "    },",
        "    enumerateDevices: async () => [],",
        "  },",
        "});",
        # O jsdom não sabe tocar vídeo; sem isto o caminho FELIZ caía no erro.
        "dom.window.HTMLMediaElement.prototype.play = async () => {};",
        # O jsdom ATIRA ao atribuir `srcObject` (não o implementa). Sem isto, o
        # caminho FELIZ caía no mesmo `catch` do caminho da avaria e este
        # ficheiro estaria a medir sempre a mesma coisa.
        "Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'srcObject', {",
        "  configurable: true, set() {}, get() { return null; },",
        "});",
        # O jsdom só tem `requestAnimationFrame` com `pretendToBeVisual`, e o
        # ciclo da câmara chama-o. Sem ele é um ReferenceError que cai no mesmo
        # `catch`. Fica um no-op: o que este ficheiro mede é a ABERTURA, não a
        # descodificação de imagens — essa prova-se na loja.
        "globalThis.requestAnimationFrame = () => 1;",
        "globalThis.cancelAnimationFrame = () => {};",
        "let ultimoErro = null;",
        "const _err = console.error;",
        "console.error = (...a) => { ultimoErro = String(a[0]); };",
        "const PosLerQr = carregar(path.join(POS, 'PosLerQr.js')).default;",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "async function abrir() {",
        "  pedidos_camera = 0;",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(PosLerQr, {",
        "    vendaId: 'v-1', onLigada: () => {}, onFechar: () => {},",
        "  })); });",
        "  await act(async () => {});",
        "  return {",
        "    alvo, raiz,",
        "    pedidos: () => pedidos_camera,",
        "    visivel: () => textoVisivel(alvo),",
        "    auto: () => alvo.querySelector('[data-testid=\"qr-camera-auto\"]'),",
        "    botaoCamara: () => [...alvo.querySelectorAll('button')].find(",
        "      (b) => (b.textContent || '').includes('Usar câmara')),",
        "    fechar: async () => { await act(async () => { raiz.unmount(); });",
        "      alvo.innerHTML = ''; },",
        "  };",
        "}",
        "(async () => {",
        "  const saida = {};",
        "  {",
        "    deixar_abrir = true;",
        "    const e = await abrir();",
        "    saida.abriu = { pedidos: e.pedidos(), erro: ultimoErro,",
        "      temVideo: !!e.alvo.querySelector('video'), visivel: e.visivel() };",
        "    await e.fechar();",
        "    deixar_abrir = false;",
        "  }",
        # 1) Por omissão (nada guardado): pede a câmara SEM ninguém carregar.
        "  {",
        "    const e = await abrir();",
        "    saida.automatico = { pedidos: e.pedidos(), visivel: e.visivel(),",
        "      marcado: !!(e.auto() && e.auto().checked), temBotao: !!e.botaoCamara() };",
        "    await e.fechar();",
        "  }",
        # 2) Carregar no botão DE PROPÓSITO, com a câmara a falhar: aí vê-se o erro.
        "  {",
        "    const e = await abrir();",
        "    await act(async () => { e.botaoCamara().click(); });",
        "    await act(async () => {});",
        "    saida.pedida = { visivel: e.visivel() };",
        "    await e.fechar();",
        "  }",
        # 3) Desligar o interruptor: fica guardado e a câmara não é pedida.
        "  {",
        "    const e = await abrir();",
        "    await act(async () => {",
        "      e.auto().click();",
        "    });",
        "    await e.fechar();",
        "    const d = await abrir();",
        "    saida.desligado = { pedidos: d.pedidos(), marcado: !!(d.auto() && d.auto().checked),",
        "      guardado: localStorage.getItem('pos_camera_auto_do_qr') };",
        "    await d.fechar();",
        "  }",
        # 4) Voltar a ligar: guarda e volta a pedir.
        "  {",
        "    const e = await abrir();",
        "    await act(async () => {",
        "      e.auto().click();",
        "    });",
        "    await act(async () => {});",
        "    saida.religado = { pedidos: e.pedidos(),",
        "      guardado: localStorage.getItem('pos_camera_auto_do_qr') };",
        "    await e.fechar();",
        "  }",
        # 5) Com a câmara a abrir a sério, o vídeo entra no ecrã.
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(cenario, tmp_path_factory.mktemp("camara-qr"), "montar-camara-qr.js")


def test_a_camara_e_pedida_sem_ninguem_carregar(ecra):
    """O pedido do dono, em números: abrir a janela pede a câmara. Zero cliques."""
    assert ecra["automatico"]["pedidos"] == 1, ecra["automatico"]


def test_a_falha_AUTOMATICA_nao_grita_com_a_funcionaria(ecra):
    """Na caixa do leitor HP não há câmara. A janela abre, tenta, falha — e
    cala-se. Um aviso vermelho por cliente, sobre uma coisa que ninguém pediu,
    era pior do que o clique que se veio poupar."""
    visivel = ecra["automatico"]["visivel"]
    assert "Não foi possível abrir a câmara" not in visivel, visivel
    assert "Usar câmara" in visivel, visivel


def test_depois_de_falhar_o_botao_continua_la(ecra):
    """Falhar em silêncio não pode ser desistir: quem quiser tentar à mão tem
    de ter por onde."""
    assert ecra["automatico"]["temBotao"] is True


def test_quem_CARREGA_no_botao_merece_saber_que_falhou(ecra):
    """O silêncio é só para o que ninguém pediu. Um clique é um pedido."""
    assert "Não foi possível abrir a câmara" in ecra["pedida"]["visivel"], ecra["pedida"]


def test_o_interruptor_comeca_LIGADO(ecra):
    """É o que serve a maioria das caixas; quem não quer desliga uma vez."""
    assert ecra["automatico"]["marcado"] is True


def test_desligar_guarda_no_PC_e_a_camara_deixa_de_ser_pedida(ecra):
    """A loja do leitor desliga isto uma vez e nunca mais pensa no assunto —
    nem com F5, nem no dia seguinte."""
    assert ecra["desligado"]["guardado"] == "0"
    assert ecra["desligado"]["pedidos"] == 0, "desligado e continuou a pedir a câmara"
    assert ecra["desligado"]["marcado"] is False


def test_voltar_a_ligar_abre_JA_a_camara(ecra):
    """Sem isto, ligar o interruptor não fazia nada visível e parecia partido:
    só valeria na venda seguinte."""
    assert ecra["religado"]["guardado"] == "1"
    assert ecra["religado"]["pedidos"] >= 1, ecra["religado"]


def test_com_camara_a_serio_o_video_aparece_e_nao_ha_erro(ecra):
    assert ecra["abriu"]["pedidos"] == 1
    assert ecra["abriu"]["temVideo"] is True
    assert "Não foi possível abrir a câmara" not in ecra["abriu"]["visivel"]
