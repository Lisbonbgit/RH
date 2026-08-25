"""**As fotos dos produtos NOS ECRÃS** — montadas e tocadas, não lidas.

Os ecrãs deste POS desenham-se sem servidor nenhum, e dois defeitos foram a
produção exactamente assim. Aqui há três níveis, e nenhum é textual:

1. a **decisão** do endereço (`lib/fotos.js::urlDaFoto`) e a da redução
   (`dimensoesParaCaber`) correm em **Node**, extraídas do ficheiro — nunca uma
   cópia escrita aqui, que ficava verde com o ecrã errado;
2. a **grelha do POS** é montada em React sobre o que a função REAL do servidor
   (`pos_catalogo._produto_publico`) respondeu, com uma foto do Vendus e uma
   carregada por nós, e o que se afirma é o `src` que ficou no `<img>`;
3. o **campo do backoffice** é montado com o servidor fabricado à frente do
   axios: escolhe-se um ficheiro, o pedido sai, e a pré-visualização passa a
   mostrar o endereço que o servidor devolveu.

**O que este ficheiro NÃO cobre, dito com todas as letras.** O `jsdom` não tem
`canvas` nem `createImageBitmap`, por isso a REDUÇÃO em si (o desenho e o
`toBlob`) não corre em lado nenhum — o que se mede é a decisão de quanto
encolher. O que protege o servidor de uma imagem enorme não é essa função: é o
tecto de 512 KB do `fotos.py`, guardado em `test_fotos_dos_produtos.py`.
"""
import json

import pytest

from faturacao.pos_catalogo import _produto_publico

from .test_a_faixa_do_modo_no_ecra import _correr_no_node, _montar_no_node
from .test_arredondamento_do_ecra import _RAIZ, _corpo_da_funcao, _corpo_da_seta, _ler

_LIB_FOTOS = _RAIZ / "frontend" / "src" / "lib" / "fotos.js"

_ASSINATURA_URL = "export const urlDaFoto = (valor, base) =>"
_ASSINATURA_MEDIDA = "export const dimensoesParaCaber = (largura, altura, maximo) =>"


def _decisao_solta() -> str:
    lib = _ler(_LIB_FOTOS)
    return "\n".join([
        _corpo_da_funcao(lib, _ASSINATURA_URL, _LIB_FOTOS).replace("export ", "", 1),
        _corpo_da_funcao(lib, _ASSINATURA_MEDIDA, _LIB_FOTOS).replace("export ", "", 1),
    ])


def _correr(expressao, tmp_path, nome):
    return _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "process.stdout.write(JSON.stringify(%s));" % expressao,
        ]),
        tmp_path, nome,
    )


# --- Nível 1a: o endereço que vai parar ao `src` ------------------------------


def test_a_foto_do_VENDUS_ja_e_absoluta_e_fica_como_esta(tmp_path):
    assert _correr(
        "urlDaFoto('https://www.vendus.pt/foto/b906f77_m.png', '')",
        tmp_path, "vendus.js") == "https://www.vendus.pt/foto/b906f77_m.png"


def test_a_foto_NOSSA_e_relativa_e_resolve_se_contra_a_base(tmp_path):
    """O portal responde em dois domínios e a foto é gravada com um endereço
    relativo — no site a base é vazia e fica tal e qual; onde a API viva noutro
    anfitrião (um embrulho da app), fica absoluta e continua a desenhar-se."""
    nossa = "/api/faturacao/produtos/fotos/1111.webp"
    assert _correr("urlDaFoto(%s, '')" % json.dumps(nossa),
                   tmp_path, "nossa.js") == nossa
    assert _correr("urlDaFoto(%s, 'https://rh.lisbonb.com')" % json.dumps(nossa),
                   tmp_path, "nossa2.js") == "https://rh.lisbonb.com" + nossa


@pytest.mark.parametrize("valor", [
    "javascript:alert(1)",
    "data:image/png;base64,AAAA",
    "//outro-sitio.pt/x.png",
    "foto.png",
    "",
    "   ",
])
def test_o_que_NAO_e_um_endereco_dos_nossos_nao_se_desenha(tmp_path, valor):
    """**O `foto_url` chega do servidor, mas o servidor foi-o buscar ao
    VENDUS** — é uma fonte externa, e isto é um atributo `src`. O `//` sem
    esquema é o silencioso: num ecrã servido por https, vai buscar a imagem a
    outro sítio qualquer sem uma palavra."""
    assert _correr("urlDaFoto(%s, '')" % json.dumps(valor),
                   tmp_path, "recusa.js") is None


def test_um_foto_url_ausente_nao_rebenta_a_grelha(tmp_path):
    assert _correr("[urlDaFoto(null, ''), urlDaFoto(undefined, ''), urlDaFoto(0, '')]",
                   tmp_path, "ausente.js") == [None, None, None]


# --- Nível 1b: quanto é que a foto do telemóvel encolhe -----------------------


def test_uma_foto_de_telemovel_encolhe_para_o_lado_maior(tmp_path):
    """4032×3024 (a foto de um telemóvel) cabe em 640 no lado maior, com a
    proporção intacta — 640×480."""
    assert _correr("dimensoesParaCaber(4032, 3024, 640)", tmp_path, "medida.js") == {
        "largura": 640, "altura": 480}


def test_uma_imagem_que_JA_CABE_nao_se_estica(tmp_path):
    """Aumentar não acrescenta detalhe nenhum, só bytes — e uma imagem esticada
    fica pior do que a pequena."""
    assert _correr("dimensoesParaCaber(320, 240, 640)", tmp_path, "cabe.js") == {
        "largura": 320, "altura": 240}


def test_uma_imagem_ABSURDAMENTE_estreita_nunca_fica_com_lado_zero(tmp_path):
    """4000×3 encolhida por 0,16 dá altura 0 — e o `canvas` desenha nada: um
    ficheiro válido, VAZIO, gravado sem um erro."""
    assert _correr("dimensoesParaCaber(4000, 3, 640)", tmp_path, "estreita.js") == {
        "largura": 640, "altura": 1}


@pytest.mark.parametrize("caso", ["0, 100", "100, 0", "-5, 10", "NaN, 10", "'a', 'b'"])
def test_uma_medida_impossivel_devolve_nada_e_o_ficheiro_segue_inteiro(tmp_path, caso):
    assert _correr("dimensoesParaCaber(%s, 640)" % caso,
                   tmp_path, "impossivel.js") is None


# --- Nível 2: a grelha do POS, montada sobre a resposta do servidor -----------

_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled, type: 'button',",
    "  'data-testid': props['data-testid'],",
    "}, props.children);",
    "const Campo = (props) => React.createElement('input', {",
    "  id: props.id, value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, placeholder: props.placeholder,",
    "  disabled: props.disabled, 'data-testid': props['data-testid'],",
    "});",
    "const Caixa = (props) => (props.open",
    "  ? React.createElement('div', { 'data-dialogo': 'aberto' }, props.children)",
    "  : null);",
    # O `Div` é o que substitui TUDO o que não é Botão/Campo/Diálogo — e
    # passou a reencaminhar o `onClick` e o `data-testid`. Sem isso, uma
    # linha de tabela clicável (o ecrã de Documentos do backoffice) montava
    # muda: o teste não lhe podia tocar, e a única prova possível era ler o
    # ficheiro — que é exactamente o que estes testes existem para não ser.
    "const Div = (props) => React.createElement('div', {",
    "  onClick: props.onClick, 'data-testid': props['data-testid'],",
    "}, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button') return Botao;",
    "  if (nome === 'Input') return Campo;",
    "  if (nome === 'Dialog') return Caixa;",
    "  return Div;",
    "} });",
])

_CATEGORIA = {"id": "cat-1", "nome": "Venda ao Público", "ordem": 0, "ativa": True}

# Os produtos como o SERVIDOR os manda ao POS — pela função real
# (`pos_catalogo._produto_publico`), e não por um dicionário escrito à mão que
# podia divergir dela.
_DO_VENDUS = "https://www.vendus.pt/foto/b906f77_m.png"
_NOSSA = "/api/faturacao/produtos/fotos/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.webp"
_ENVENENADA = "javascript:alert(document.cookie)"


def _produto(id_, nome, preco, foto):
    return {
        "id": id_, "nome": nome, "categoria_id": "cat-1", "preco": preco,
        "tax_id": "INT", "foto_url": foto, "grupos_personalizacao": [],
        "ativo": True,
    }


@pytest.fixture(scope="module")
def catalogo_do_servidor():
    """A resposta do `GET /pos/catalogo`, montada pelas funções reais."""
    produtos = [
        _produto("p-vendus", "Açaí Regular", 10.20, _DO_VENDUS),
        _produto("p-nossa", "Açaí Grande", 11.35, _NOSSA),
        _produto("p-sem", "Água", 0.29, None),
        _produto("p-envenenada", "Coca-Cola", 1.15, _ENVENENADA),
    ]
    return {
        "categorias": [_CATEGORIA],
        "produtos": [_produto_publico(p) for p in produtos],
    }


@pytest.fixture(scope="module")
def grelha(catalogo_do_servidor, tmp_path_factory):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "SUBSTITUIDOS.delete(path2.join(POS, 'PosVenda.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: 'Loja' });",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosVenda = carregar(path2.join(POS, 'PosVenda.js')).default;",
        "RESPOSTAS_POS['/pos/catalogo'] = () => ({ data: %s });"
        % json.dumps(catalogo_do_servidor, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/tipos-pagamento'] = () => ({ data: [] });",
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: null });",
        "RESPOSTAS_POS['/pos/venda/repartidas'] = () => ({ data: { grupos: [] } });",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(PosVenda, {",
        "  operador: { id: 'o1', nome: 'Ana' }, caixa: { id: 'c1', nome: 'Balcão' },",
        "  sessao: { id: 's1', fundo: 50 }, lojaNome: 'Loja',",
        "  onSair: () => {}, onCaixaFechada: () => {}, modo: 'normal' })); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const imagens = Array.from(alvo.querySelectorAll('img')).map((i) => ({",
        "  src: i.getAttribute('src'), loading: i.getAttribute('loading'),",
        "  decoding: i.getAttribute('decoding'), alt: i.getAttribute('alt'),",
        "}));",
        "process.stdout.write(JSON.stringify({",
        "  imagens, visivel: textoVisivel(alvo), html: alvo.innerHTML }));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % guiao, tmp_path_factory.mktemp("grelha"), "montar-grelha.js")


def test_a_grelha_do_POS_esta_mesmo_montada(grelha):
    """Sem esta afirmação, os guardas a seguir mediam o vazio."""
    for nome in ("Açaí Regular", "Açaí Grande", "Água", "Coca-Cola"):
        assert nome in grelha["visivel"], grelha["visivel"][:400]


def test_a_foto_do_VENDUS_aparece_na_grelha(grelha):
    fontes = [i["src"] for i in grelha["imagens"]]
    assert _DO_VENDUS in fontes, fontes


def test_a_foto_CARREGADA_por_nos_aparece_na_grelha(grelha):
    fontes = [i["src"] for i in grelha["imagens"]]
    assert _NOSSA in fontes, fontes


def test_um_endereco_ENVENENADO_nunca_chega_a_um_atributo_src(grelha):
    """A foto vem do Vendus, que é uma fonte externa, e vai parar a um `src`."""
    fontes = [i["src"] for i in grelha["imagens"]]
    assert not any("javascript:" in (f or "") for f in fontes), fontes
    assert "javascript:" not in grelha["html"]


def test_um_produto_SEM_foto_nao_desenha_um_img_vazio(grelha):
    """Um `<img src="">` pede a PÁGINA outra vez ao servidor e desenha o ícone
    de imagem partida. Os quatro produtos estão na grelha e as imagens são
    DUAS — o da água e o envenenado caem no espaço de reserva."""
    assert all(i["src"] for i in grelha["imagens"])
    assert len(grelha["imagens"]) == 2, [i["src"] for i in grelha["imagens"]]


def test_a_grelha_carrega_as_fotos_a_MEDIDA_e_nao_todas_de_uma_vez(grelha):
    """**A grelha de um PC de loja.** Sem `loading="lazy"`, abrir o ecrã de
    venda pede as fotos TODAS de uma vez — as que se veem e as que estão dez
    ecrãs abaixo — e o PC do balcão passa esse tempo sem responder ao dedo."""
    for imagem in grelha["imagens"]:
        assert imagem["loading"] == "lazy", grelha["imagens"]
        assert imagem["decoding"] == "async", grelha["imagens"]


# --- Nível 3: o campo do backoffice, com o dedo a escolher um ficheiro --------


@pytest.fixture(scope="module")
def campo_do_backoffice(tmp_path_factory):
    """Monta o `FatProdutos`, abre o diálogo do produto e escolhe um ficheiro —
    o pedido sai mesmo, e a resposta do servidor volta ao ecrã."""
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatProdutos = carregar(path2.join(ADMIN, 'FatProdutos.js')).default;",
        "const RESP = RESPOSTAS_GESTAO;",
        "RESP['/faturacao/produtos'] = () => ({ data: [] });",
        "RESP['/faturacao/produtos/sem-iva'] = () => ({ data: [] });",
        "RESP['/faturacao/categorias'] = () => ({ data: [%s] });"
        % json.dumps(_CATEGORIA, ensure_ascii=False),
        "RESP['/faturacao/grupos-personalizacao'] = () => ({ data: [] });",
        "RESP['POST /faturacao/produtos/fotos'] = () => ({ data: { foto_url: %s } });"
        % json.dumps(_NOSSA),
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatProdutos)); });",
        "await act(async () => {});",
        "const botaoDe = (texto) => Array.from(alvo.querySelectorAll('button'))",
        "  .find((b) => (b.textContent || '').includes(texto));",
        "const saida = {};",
        "await act(async () => { botaoDe('Novo produto').click(); });",
        "await act(async () => {});",
        "saida.antes = textoVisivel(alvo);",
        # O convite a colar um endereço vive no `placeholder`, que é um
        # ATRIBUTO e não texto no ecrã — afirma-se como atributo, de propósito,
        # e não como coisa lida (ver o preâmbulo de montagem: um valor guardado
        # num atributo não é uma frase).
        "saida.endereco_placeholder = (alvo.querySelector(",
        "  '[data-testid=\"produto-foto-input\"]') || {}).getAttribute",
        "  ? alvo.querySelector('[data-testid=\"produto-foto-input\"]')",
        "      .getAttribute('placeholder') : null;",
        "saida.tem_campo_de_ficheiro = !!alvo.querySelector("
        "  '[data-testid=\"produto-foto-ficheiro\"]');",
        "saida.aceita = (alvo.querySelector("
        "  '[data-testid=\"produto-foto-ficheiro\"]') || {}).getAttribute",
        "  ? alvo.querySelector('[data-testid=\"produto-foto-ficheiro\"]')",
        "      .getAttribute('accept') : null;",
        # O dedo: um ficheiro escolhido no campo. O `File` do jsdom chega ao
        # `onChange`, e daí para o `reduzirImagem` (que sem `canvas` devolve o
        # ficheiro inteiro) e para o pedido.
        "const campo = alvo.querySelector('[data-testid=\"produto-foto-ficheiro\"]');",
        # O `File` do NODE, e não o do jsdom: o `FormData` global do Node
        # recusa um `Blob` de outra implementação («parameter 2 is not of type
        # Blob»), e o ecrã apanhava isso como um erro de carregamento — um
        # guarda verde a medir o `catch`. É um artefacto do ambiente; no
        # browser há uma implementação só.
        "const ficheiro = new File([new Uint8Array([255, 216, 255, 224])],",
        "  'acai.jpg', { type: 'image/jpeg' });",
        "Object.defineProperty(campo, 'files', { value: [ficheiro] });",
        "await act(async () => {",
        "  campo.dispatchEvent(new dom.window.Event('change', { bubbles: true }));",
        "});",
        "await act(async () => {});",
        "await act(async () => {});",
        "saida.depois = textoVisivel(alvo);",
        "saida.previsualizacao = (alvo.querySelector(",
        "  '[data-testid=\"produto-foto-previsualizacao\"]') || {}).getAttribute",
        "  ? alvo.querySelector('[data-testid=\"produto-foto-previsualizacao\"]')",
        "      .getAttribute('src') : null;",
        "saida.pedidos = pedidos.map((p) => p.url);",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % guiao, tmp_path_factory.mktemp("backoffice"), "montar-produtos.js")


def test_o_backoffice_OFERECE_escolher_um_ficheiro_do_computador(campo_do_backoffice):
    """**O pedido do dono, literalmente**: «ainda não consigo colocar as
    imagens dos produtos … deixe no backoffice a opção de fazer upload». Antes
    havia só um campo de texto a pedir um endereço."""
    assert campo_do_backoffice["tem_campo_de_ficheiro"], (
        "O formulário do produto não tem por onde escolher um ficheiro.")
    assert "Escolher ficheiro" in campo_do_backoffice["antes"]
    assert campo_do_backoffice["aceita"] == "image/jpeg,image/png,image/webp"


def test_o_endereco_continua_a_existir_para_quem_o_queira(campo_do_backoffice):
    """O caminho normal passa a ser o ficheiro; colar um endereço continua
    possível — uma foto que já viva noutro sítio não tem de ser recarregada."""
    assert "cole aqui um endereço" in (
        campo_do_backoffice["endereco_placeholder"] or "")


def test_escolher_um_ficheiro_ENVIA_O_PEDIDO_ao_servidor(campo_do_backoffice):
    """Um ecrã que ficasse com o ficheiro na mão sem o mandar a lado nenhum
    desenhava-se exactamente igual."""
    assert any("/faturacao/produtos/fotos" in u
               for u in campo_do_backoffice["pedidos"]), campo_do_backoffice["pedidos"]


def test_a_PREVISUALIZACAO_mostra_o_endereco_que_o_SERVIDOR_devolveu(campo_do_backoffice):
    """E não um `blob:` local: o que fica no formulário é o `foto_url` que vai
    ser gravado no produto, e por isso o que se vê é a foto REAL, servida pelo
    servidor. Um `blob:` desaparecia ao fechar o diálogo e escondia um envio
    que nunca chegou a acontecer."""
    assert campo_do_backoffice["previsualizacao"] == _NOSSA, (
        "A pré-visualização não está a mostrar a foto que o servidor gravou.")
    assert "Trocar a foto" in campo_do_backoffice["depois"], (
        "Depois de carregar a foto, o botão continua a convidar a escolher a "
        "primeira.")
