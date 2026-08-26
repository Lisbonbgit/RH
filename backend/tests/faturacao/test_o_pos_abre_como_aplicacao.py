"""**O POS tem de abrir COMO APLICAÇÃO no PC da loja, e não num separador.**

O dono pôs o POS num PC de loja, mandou o browser abri-lo como aplicação, e
ao fechar e voltar a abrir o ícone apareceu-lhe o browser normal — com barra
de endereço, separadores e o resto. O Vendus, no mesmo PC, abre como
aplicação.

A diferença não é magia: o Vendus tem um **manifesto**. Sem manifesto o
browser não tem nada para "instalar" — só sabe fazer um atalho, e um atalho
abre uma janela normal.

Este ficheiro guarda o manifesto porque ele avaria **em silêncio**: nada
rebenta, nada fica vermelho, o ecrã funciona na mesma. Só o PC da loja é que
deixa de abrir como aplicação, e isso ninguém descobre a partir daqui. As
avarias que já estavam à espera:

- pedir `/manifest.json` a este servidor devolvia **200 com o index.html lá
  dentro** (o `try_files` do nginx manda qualquer caminho desconhecido para o
  React Router). Um 200 que não é JSON é pior do que um 404: parece que está
  lá;
- `start_url` a apontar para um caminho que já não existe — a aplicação abre
  no ecrã em branco do React Router;
- os ícones num caminho errado (`/icons/` em vez de `/icones/`): a instalação
  fica sem ícone, ou o browser recusa-a.
"""
import json
import struct
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[3]
_PUBLICO = _RAIZ / "frontend" / "public"
_MANIFESTO = _PUBLICO / "manifest.json"


@pytest.fixture(scope="module")
def manifesto():
    assert _MANIFESTO.exists(), (
        "Sem frontend/public/manifest.json o browser não tem o que instalar, e "
        "o POS volta a abrir num separador no PC da loja.")
    # Lido como JSON de propósito: um ficheiro com uma vírgula a mais é
    # exactamente o mesmo silêncio — o browser ignora-o e ninguém dá por nada.
    return json.loads(_MANIFESTO.read_text(encoding="utf-8"))


def test_o_manifesto_pede_JANELA_PROPRIA(manifesto):
    """`display` é o campo que decide isto e mais nenhum. Com `browser` (ou
    sem campo), o browser abre um separador — que é precisamente o sintoma que
    o dono descreveu."""
    assert manifesto.get("display") in ("standalone", "fullscreen", "minimal-ui"), (
        "display=%r abre em separador." % manifesto.get("display"))


def test_o_manifesto_ABRE_NO_POS_e_nao_na_raiz_do_portal(manifesto):
    """O PC da loja é do balcão. Abrir a aplicação na raiz do portal obrigava
    a operadora a navegar até ao POS a cada arranque."""
    assert manifesto.get("start_url") == "/faturacao/pos", manifesto.get("start_url")


def test_o_start_url_e_uma_ROTA_QUE_EXISTE_no_ecra():
    """Confrontado com o `App.js`, e não afirmado duas vezes. Renomear a rota
    do POS deixaria o manifesto a apontar para o vazio: a aplicação abriria
    num ecrã em branco, sem nada partir e sem nenhum teste ficar vermelho."""
    manifesto = json.loads(_MANIFESTO.read_text(encoding="utf-8"))
    app = (_RAIZ / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    caminho = manifesto["start_url"]
    assert 'path="%s"' % caminho in app, (
        "O App.js não tem nenhuma rota %r — o manifesto abriria no vazio." % caminho)


def test_os_ICONES_do_manifesto_existem_mesmo(manifesto):
    """O engano clássico é o caminho (`/icons/` vs `/icones/`): o manifesto
    fica válido, a instalação fica sem ícone, e no PC da loja aparece um
    quadrado em branco na barra de tarefas."""
    icones = manifesto.get("icons") or []
    assert icones, "Um manifesto sem ícones não é instalável."
    for icone in icones:
        caminho = _PUBLICO / icone["src"].lstrip("/")
        assert caminho.exists(), "%s não existe em frontend/public/" % icone["src"]


def _tamanho_do_png(caminho: Path):
    """A largura e a altura, lidas do cabeçalho IHDR do próprio ficheiro.

    Sem Pillow de propósito: o backend não o tem, e um `importorskip` deixava
    este guarda SALTADO — que é o mesmo que não existir. São 8 bytes num sítio
    fixo do formato (assinatura de 8 + 4 do tamanho + 4 de "IHDR"), e a
    assinatura é conferida para um ficheiro que não seja PNG não ser lido como
    se fosse."""
    dados = caminho.read_bytes()
    assert dados[:8] == b"\x89PNG\r\n\x1a\n", "%s não é um PNG" % caminho.name
    largura, altura = struct.unpack(">II", dados[16:24])
    return largura, altura


def test_os_ICONES_tem_o_tamanho_que_dizem_ter(manifesto):
    """Um `sizes` que mente é a mesma avaria silenciosa: o browser pede 512 e
    recebe 192, e a instalação fica com um ícone borratado ou é recusada.
    Medido no ficheiro, e não lido do campo que o descreve."""
    for icone in manifesto["icons"]:
        medido = _tamanho_do_png(_PUBLICO / icone["src"].lstrip("/"))
        assert "%dx%d" % medido == icone["sizes"], (
            "%s tem %dx%d mas diz %s"
            % (icone["src"], medido[0], medido[1], icone["sizes"]))


def test_ha_um_tamanho_de_192_e_um_de_512(manifesto):
    """Os dois que os browsers exigem para considerar o site instalável."""
    tamanhos = {i["sizes"] for i in manifesto["icons"]}
    assert "192x192" in tamanhos, tamanhos
    assert "512x512" in tamanhos, tamanhos


def test_ha_um_icone_MASKABLE(manifesto):
    """O Windows e o Android recortam o ícone à sua maneira. Sem um `maskable`
    (com a margem de segurança), o "POS" fica cortado nos cantos."""
    proposi = {i.get("purpose") for i in manifesto["icons"]}
    assert "maskable" in proposi, proposi


def test_o_INDEX_LIGA_o_manifesto():
    """Sem o `<link rel="manifest">` o ficheiro está no servidor e ninguém o
    pede — que é exactamente o estado em que isto estava."""
    index = (_PUBLICO / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in index, "O index.html não liga o manifesto."
    assert 'href="/manifest.json"' in index, index[:400]
