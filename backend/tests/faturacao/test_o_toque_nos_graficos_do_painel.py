"""**Passar o rato por cima do gráfico e ler o valor daquele dia.**

O dono mostrou os gráficos do Vendus: o cursor sobre a curva e um balão a
dizer «10-08 · € 1.819,97», com uma linha vertical a marcar o dia. Pediu o
mesmo no painel dele.

Os gráficos já cá estavam — curva suave, gradiente, barras arredondadas. O que
faltava era o TOQUE: sem ele, a única leitura possível é a olho contra o eixo,
e um pico a meio de trinta dias não tem data nenhuma.

Montado a sério (React + jsdom), com o rato a mexer-se de verdade. Duas
armadilhas que só um teste destes apanha:

1. **a conta das coordenadas.** O SVG desenha-se num `viewBox` de 720 e é
   mostrado com a largura que o cartão tiver. Converter a posição do rato de
   uma escala para a outra é onde isto se engana — e um balão que aponta para
   o dia errado é PIOR do que balão nenhum: parece que está certo. Por isso o
   teste dá ao SVG uma caixa de medidas conhecidas e confere o dia que sai;
2. **o teclado.** Um valor que só se lê com o rato deixa de fora quem navega
   por tabulação. As barras têm de dar o mesmo balão ao receberem o foco.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

# Quatro dias com valores bem diferentes: assim o balão que sai identifica
# sem ambiguidade o ponto que o rato escolheu.
_DIAS = [
    {"data": "2026-08-23", "valor": 100.0},
    {"data": "2026-08-24", "valor": 900.0},
    {"data": "2026-08-25", "valor": 400.0},
    {"data": "2026-08-26", "valor": 1819.97},
]
_MESES = [
    {"mes": "2026-06", "valor": 12724.45},
    {"mes": "2026-07", "valor": 56112.67},
    {"mes": "2026-08", "valor": 41819.82},
]
_CARTAO = {"valor": 977.38, "valor_comparado": 1213.05, "variacao": -19.45,
           "comparacao": "Hoje contra ontem"}
_DASHBOARD = {
    "ha_vendas": True,
    "cartoes": {"hoje": _CARTAO, "mensal": _CARTAO, "anual": _CARTAO},
    "serie_diaria": _DIAS,
    "ultimos_6_meses": _MESES,
    "por_loja": [],
    "mais_vendidos": [],
    "mais_rentaveis": [],
}

# As medidas do gráfico de área, LIDAS do ecrã (a constante `AREA`, em
# `FatDashboard.js`) e não escritas aqui à mão.
#
# Escritas à mão, foi o que aconteceu: o desenho passou de 720x260 para
# 1400x250 e estes testes continuaram VERDES — a tolerância do «ponto mais
# perto» tapou a diferença, e a conversão de coordenadas, que é o que eles
# existem para medir, deixou de ser medida sem ninguém dar por isso.
def _medidas_do_ecra():
    from pathlib import Path
    import re
    ecra = (Path(__file__).resolve().parents[2].parent / "frontend" / "src" /
            "pages" / "admin" / "faturacao" / "FatDashboard.js").read_text(encoding="utf-8")
    bloco = ecra[ecra.index("const AREA = {"):]
    bloco = bloco[:bloco.index("};")]
    return {c: int(v) for c, v in re.findall(r"(\w+):\s*(\d+)", bloco)}


_AREA = _medidas_do_ecra()
_LARGURA_VIEWBOX = _AREA["largura"]
_X_ESQ, _X_DIR = _AREA["xLeft"], _AREA["xRight"]
# A caixa que o teste dá ao SVG: o dobro do desenho, para a escala ser 2 e a
# conversão de coordenadas ficar afirmável com uma multiplicação simples.
_CAIXA_L, _CAIXA_A = _LARGURA_VIEWBOX * 2, _AREA["altura"] * 2


def _x_do_ponto(indice, total=len(_DIAS)):
    """O x, no viewBox, do ponto `indice` — a MESMA conta do `buildArea`."""
    return _X_ESQ + (indice / (total - 1)) * (_X_DIR - _X_ESQ)


def _guiao(passos):
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const Painel = carregar(path2.join(ADMIN, 'FatDashboard.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/dashboard'] = () => ({ data: %s });"
        % json.dumps(_DASHBOARD, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(Painel)); });",
        "await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector('[data-testid=\"' + t + '\"]');",
        "const texto = (t) => { const n = porTestid(t); return n ? n.textContent : null; };",
        # O jsdom não faz layout: `getBoundingClientRect` devolve tudo a zero,
        # e a conversão de coordenadas ficava a dividir por zero. Dá-se ao SVG
        # uma caixa de medidas CONHECIDAS — é o que torna a conta afirmável:
        # 720 unidades de viewBox mostradas em 1440 pixels, ou seja, escala 2.
        "const daCaixa = (no, caixa) => Object.defineProperty(",
        "  no, 'getBoundingClientRect', { value: () => caixa, configurable: true });",
        "const svgArea = porTestid('fat-dashboard-area');",
        "daCaixa(svgArea, { left: 0, top: 0, width: %d, height: %d, "
        "right: %d, bottom: %d, x: 0, y: 0 });"
        % (_CAIXA_L, _CAIXA_A, _CAIXA_L, _CAIXA_A),
        # O rato mexe-se sobre a MOLDURA do gráfico (é ela que apanha o
        # movimento em toda a área, e não só onde há tinta pintada).
        "const moldura = porTestid('fat-dashboard-area-moldura');",
        "const mover = async (xNoViewBox) => {",
        "  await act(async () => {",
        "    const ev = new dom.window.Event('pointermove', { bubbles: true });",
        "    ev.clientX = xNoViewBox * 2;",  # a caixa e' o dobro do desenho
        "    ev.clientY = 100;",
        "    moldura.dispatchEvent(ev);",
        "  });",
        "  await act(async () => {});",
        "};",
        # Sair: dispara-se o `pointerout`, que é o que o browser manda
        # primeiro e de onde o React sintetiza o `onPointerLeave`. Mandar
        # o `pointerleave` cru não passa por essa maquinaria e o teste
        # media uma coisa que no browser não acontece assim.
        "const sair = async () => {",
        "  await act(async () => { moldura.dispatchEvent(",
        "    new dom.window.Event('pointerout', { bubbles: true })); });",
        "  await act(async () => {});",
        "};",
        "const saida = {};",
    ] + passos + [
        "process.stdout.write(JSON.stringify(saida));",
    ])


def _monta(passos, tmp, nome):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _guiao(passos), tmp, nome)


# --- A curva dos 30 dias -----------------------------------------------------


@pytest.fixture(scope="module")
def area(tmp_path_factory):
    return _monta([
        "saida.antes = texto('fat-area-balao');",
        # Em cima do 2.º dia (o pico de 900) — e depois um bocadinho AO LADO
        # dele, para provar que o balão se agarra ao ponto mais perto e não
        # exige pontaria em cima do pixel certo.
        "await mover(%.1f);" % _x_do_ponto(1),
        "saida.em_cima = texto('fat-area-balao');",
        "saida.tem_linha = !!porTestid('fat-area-linha');",
        "await mover(%.1f);" % (_x_do_ponto(1) + 40),
        "saida.ao_lado = texto('fat-area-balao');",
        "await mover(%.1f);" % _x_do_ponto(3),
        "saida.ultimo_dia = texto('fat-area-balao');",
        "await sair();",
        "saida.depois_de_sair = texto('fat-area-balao');",
    ], tmp_path_factory.mktemp("area"), "toque-area.js")


def test_sem_o_rato_em_cima_NAO_ha_balao(area):
    """Um balão sempre visível tapa o desenho e deixa de ser uma resposta a
    uma pergunta — passa a ser ruído."""
    assert area["antes"] is None, area["antes"]


def test_o_rato_em_cima_de_um_dia_DIZ_o_dia_e_o_valor(area):
    """O que o dono viu no Vendus: «10-08 · € 1.819,97»."""
    assert area["em_cima"], "Não apareceu balão nenhum sobre o gráfico."
    assert "24-08" in area["em_cima"], area["em_cima"]
    assert "900" in area["em_cima"], area["em_cima"]


def test_ha_uma_LINHA_vertical_a_marcar_o_dia(area):
    """Sem a linha, o balão flutua e não se sabe a que ponto da curva
    pertence — sobretudo num gráfico de trinta dias."""
    assert area["tem_linha"], "Não há linha vertical a marcar o ponto."


def test_o_balao_agarra_se_ao_ponto_MAIS_PERTO(area):
    """Ninguém acerta num ponto de 2 px. O rato aponta para uma zona e o
    gráfico decide qual é o dia — é o que faz isto usável com o rato de um PC
    de loja."""
    assert area["ao_lado"] == area["em_cima"], (
        "40 unidades ao lado do pico já mudou de dia: %r vs %r"
        % (area["ao_lado"], area["em_cima"]))


def test_a_conta_das_COORDENADAS_nao_se_engana_no_ultimo_dia(area):
    """A borda direita é onde uma conversão de escala errada se nota primeiro
    — e um balão que aponta o dia errado é pior do que balão nenhum, porque
    parece certo."""
    assert "26-08" in (area["ultimo_dia"] or ""), area["ultimo_dia"]
    assert "819,97" in (area["ultimo_dia"] or ""), area["ultimo_dia"]


def test_tirar_o_rato_LIMPA_o_balao(area):
    assert area["depois_de_sair"] is None, area["depois_de_sair"]


# --- As barras dos 6 meses ---------------------------------------------------


@pytest.fixture(scope="module")
def barras(tmp_path_factory):
    return _monta([
        "const toque = (i) => porTestid('fat-bar-toque-' + i);",
        "saida.tem_alvos = [0,1,2].every((i) => !!toque(i));",
        # `pointerover` e não `pointerenter`: é o primeiro que o browser
        # manda, e é dele que o React sintetiza o `onPointerEnter`. O
        # `pointerenter` cru não sobe até à maquinaria do React.
        "await act(async () => { toque(1).dispatchEvent(",
        "  new dom.window.Event('pointerover', { bubbles: true })); });",
        "await act(async () => {});",
        "saida.com_rato = texto('fat-bars-balao');",
        "saida.marcada = (porTestid('fat-bar-1') || {}).getAttribute",
        "  ? porTestid('fat-bar-1').getAttribute('data-em-foco') : null;",
        "saida.outra_marcada = (porTestid('fat-bar-0') || {}).getAttribute",
        "  ? porTestid('fat-bar-0').getAttribute('data-em-foco') : null;",
        # O teclado: focar o alvo tem de dar exactamente o mesmo balão.
        # `focusin` pela mesma razão: o `focus` não borbulha, e o React
        # ouve o `focusin` para servir o `onFocus`.
        "await act(async () => { toque(2).dispatchEvent(",
        "  new dom.window.Event('focusin', { bubbles: true })); });",
        "await act(async () => {});",
        "saida.com_teclado = texto('fat-bars-balao');",
        "saida.alcancavel_por_tabulacao = toque(2).getAttribute('tabindex');",
    ], tmp_path_factory.mktemp("barras"), "toque-barras.js")


def test_cada_barra_tem_o_seu_ALVO_de_toque(barras):
    """O alvo é maior do que a barra pintada de propósito: uma barra de um mês
    fraco é uma tira fina, e ninguém lhe acerta."""
    assert barras["tem_alvos"], "Falta o alvo de toque de alguma barra."


def test_o_rato_numa_barra_DIZ_o_mes_e_o_valor(barras):
    assert barras["com_rato"], "A barra não deu balão nenhum."
    assert "Jul" in barras["com_rato"], barras["com_rato"]
    assert "112,67" in barras["com_rato"], barras["com_rato"]


def test_a_barra_apontada_RESPONDE_ao_rato(barras):
    """Sem a barra reagir, o balão podia estar a falar de outra qualquer — e
    com seis barras encostadas isso acontece de certeza."""
    assert barras["marcada"] == "sim", barras["marcada"]
    assert barras["outra_marcada"] != "sim", barras["outra_marcada"]


def test_o_TECLADO_da_o_mesmo_que_o_rato(barras):
    """Um valor que só se lê com o rato deixa de fora quem navega por
    tabulação — e o balão é, aqui, a única forma de ler o valor exacto de um
    mês."""
    assert barras["alcancavel_por_tabulacao"] == "0", barras["alcancavel_por_tabulacao"]
    assert barras["com_teclado"], "Focar a barra pelo teclado não mostrou balão."
    assert "Ago" in barras["com_teclado"], barras["com_teclado"]
    assert "819,82" in barras["com_teclado"], barras["com_teclado"]


# --- Os dois defeitos que só apareceram ao OLHAR para o desenho -------------
#
# Os testes acima estavam todos verdes e o ecrã tinha estes dois. Nenhum deles
# se deduz do código: aparecem quando se desenha a página com o CSS a sério e
# se olha para ela. Ficam aqui presos para não voltarem.


@pytest.fixture(scope="module")
def bordas(tmp_path_factory):
    return _monta([
        # A barra mais alta é a que empurra o balão contra o topo do cartão.
        "const toque = (i) => porTestid('fat-bar-toque-' + i);",
        "await act(async () => { toque(1).dispatchEvent(",
        "  new dom.window.Event('pointerover', { bubbles: true })); });",
        "await act(async () => {});",
        "saida.balao_da_barra_alta = porTestid('fat-bars-balao')",
        "  .getAttribute('data-por-baixo');",
        # E um ponto lá em baixo na curva, que tem espaço por cima de sobra.
        "await mover(%.1f);" % _x_do_ponto(0),
        "saida.balao_do_ponto_baixo = porTestid('fat-area-balao')",
        "  .getAttribute('data-por-baixo');",
        # As etiquetas do eixo dos dias, com a ancoragem de cada uma.
        "saida.ancoras = Array.from(porTestid('fat-dashboard-area')",
        "  .querySelectorAll('text')).filter((t) => (t.textContent || '').length === 5",
        "    && (t.textContent || '').charAt(2) === '-')",
        "  .map((t) => ({ x: Number(t.getAttribute('x')), ancora: t.getAttribute('text-anchor') }));",
    ], tmp_path_factory.mktemp("bordas"), "bordas.js")


def test_o_balao_de_uma_barra_ALTA_passa_para_baixo_do_ponto(bordas):
    """Encostado ao topo não há para onde o empurrar: por cima, o balão da
    barra mais alta saía do cartão e ia tapar o título do gráfico. Apanhado a
    olho, com o CSS a sério — nenhum dos outros testes o via."""
    assert bordas["balao_da_barra_alta"] == "sim", bordas["balao_da_barra_alta"]


def test_um_ponto_com_espaco_por_cima_MANTEM_o_balao_por_cima(bordas):
    """A troca é só para quem não cabe. Passar todos para baixo tapava a curva
    logo a seguir ao ponto — trocava um defeito por outro."""
    assert bordas["balao_do_ponto_baixo"] == "nao", bordas["balao_do_ponto_baixo"]


def test_a_ULTIMA_etiqueta_do_eixo_nao_fica_cortada(bordas):
    """Centrada em x=710 num desenho de 720, metade da etiqueta cai fora do
    `viewBox` e lia-se «26-0». Quem está encostado à borda alinha-se por ela."""
    assert bordas["ancoras"], "Não se encontraram as etiquetas dos dias."
    ultima = max(bordas["ancoras"], key=lambda a: a["x"])
    assert ultima["x"] > 700, ultima
    assert ultima["ancora"] == "end", ultima
    # E as do meio continuam centradas — a correcção não pode desalinhar tudo.
    meio = [a for a in bordas["ancoras"] if 20 <= a["x"] <= 700]
    assert meio and all(a["ancora"] == "middle" for a in meio), bordas["ancoras"]


# --- «Tem todos os dias do mês. Fica menor.» ---------------------------------


def test_o_eixo_mostra_TODOS_os_dias_e_nao_seis(tmp_path_factory):
    """O dono, com o painel do Vendus ao lado: «tem todos os dias do mês».

    Mostrávamos seis datas porque a letra saía a 19 px — o desenho tinha 720
    unidades esticadas para ~1400 px. Com 1400 unidades a letra sai a 10 px e
    as trinta datas cabem."""
    saida = _monta([
        "saida.datas = Array.from(porTestid('fat-dashboard-area')",
        "  .querySelectorAll('text')).map((t) => t.textContent)",
        "  .filter((t) => (t || '').length === 5 && t.charAt(2) === '-');",
    ], tmp_path_factory.mktemp("eixo"), "eixo.js")
    assert len(saida["datas"]) == len(_DIAS), (
        "O eixo mostra %d datas de %d dias." % (len(saida["datas"]), len(_DIAS)))
    assert saida["datas"][0] == "23-08"
    assert saida["datas"][-1] == "26-08"


def test_o_desenho_e_BAIXO_e_nao_quase_quadrado():
    """«fica menor, não fica tão grande como o nosso.»

    A altura de um SVG com `viewBox` e largura de 100% é a largura a dividir
    pela proporção. A 720x260 (2,8:1) um cartão de 1400 px dava 505 px de
    gráfico; o do Vendus é quase 6,5:1 e por isso fica baixo.

    Afirmado sobre a PROPORÇÃO e não sobre os números: o que não pode voltar é
    um gráfico que ocupa meio ecrã."""
    proporcao = _AREA["largura"] / _AREA["altura"]
    assert proporcao >= 5, (
        "O gráfico voltou a ser alto: %.1f:1 — num cartão de 1400 px são %d px "
        "de altura." % (proporcao, 1400 / proporcao))


def test_as_medidas_do_desenho_vivem_num_SITIO_SO():
    """Espalhadas por seis números soltos no JSX, uma mudança de proporção
    obrigava a acertar todos à mão — e falhar um deixava a linha da grelha ou
    a mira fora do sítio, sem nada partir."""
    from pathlib import Path
    ecra = (Path(__file__).resolve().parents[2].parent / "frontend" / "src" /
            "pages" / "admin" / "faturacao" / "FatDashboard.js").read_text(encoding="utf-8")
    assert 'viewBox={`0 0 ${AREA.largura} ${AREA.altura}`}' in ecra
    assert "x1={AREA.xLeft}" in ecra and "x2={AREA.xRight}" in ecra
    assert "/ AREA.largura}" in ecra, "O balão voltou a dividir por um número escrito à mão."
