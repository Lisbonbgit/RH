"""**A ficha do produto passa a ligar-se a um artigo do Vendus, à mão.**

O pedido do dono, literalmente: «era bom na hora de criar um artigo ter na
ficha dele uma área de confirmar e ligar a um produto específico no Vendus.
assim não teria erro».

O erro que ele quer evitar tem nome: um produto criado no backoffice não tem
`vendus_ref`, a linha da fatura sai sem `id`, e o Vendus — que não casa por
nome — CRIA um artigo novo a cada venda. Até aqui o único caminho para a
ligação era a importação acertar no nome do produto; quando não acertava,
ninguém dava por nada até o catálogo do Vendus estar cheio de órfãos.

Montado a sério (React + jsdom), porque um ecrã que se lê é um ecrã que não se
viu. As perguntas que interessam:

1. a ficha DIZ em que estado está — e o que acontece se ficar assim;
2. escolher um artigo faz a ligação chegar ao servidor;
3. gravar sem tocar na ligação NÃO a corta (o defeito silencioso);
4. desligar de propósito é possível, e diz o que custa;
5. com o Vendus em baixo, o escolhedor não finge um catálogo vazio.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _CATEGORIA, _COMPONENTES

_SOLTO = {
    "id": "p-solto", "nome": "Brigadeiro", "categoria_id": "cat-1",
    "preco": 1.50, "tax_id": "NOR", "grupos_personalizacao": [], "ativo": True,
}
_LIGADO = {
    "id": "p-ligado", "nome": "Açaí Mini", "categoria_id": "cat-1",
    "preco": 5.90, "tax_id": "INT", "vendus_ref": "171258472",
    "grupos_personalizacao": [], "ativo": True,
}

_ARTIGOS = [
    {"id": "171258472", "nome": "Açaí Mini", "referencia": "ACM",
     "preco": 5.90, "tax_id": "INT", "ligado_a": "Açaí Mini"},
    {"id": "171258999", "nome": "Brigadeiro da casa", "referencia": "BRG",
     "preco": 1.50, "tax_id": "NOR", "ligado_a": None},
]


def _guiao(passos, artigos=None, artigos_falham=False):
    resposta_artigos = (
        "RESP['/faturacao/vendus/artigos'] = () => { const e = new Error('502');"
        " e.response = { status: 502, data: { detail: 'Vendus indisponível: boom' } };"
        " throw e; };"
        if artigos_falham else
        "RESP['/faturacao/vendus/artigos'] = () => ({ data: %s });"
        % json.dumps(_ARTIGOS if artigos is None else artigos, ensure_ascii=False)
    )
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatProdutos = carregar(path2.join(ADMIN, 'FatProdutos.js')).default;",
        "const RESP = RESPOSTAS_GESTAO;",
        "RESP['/faturacao/produtos'] = () => ({ data: %s });"
        % json.dumps([_SOLTO, _LIGADO], ensure_ascii=False),
        "RESP['/faturacao/produtos/sem-iva'] = () => ({ data: [] });",
        "RESP['/faturacao/produtos/sem-vendus'] = () => ({ data: [%s] });"
        % json.dumps(_SOLTO, ensure_ascii=False),
        "RESP['/faturacao/categorias'] = () => ({ data: [%s] });"
        % json.dumps(_CATEGORIA, ensure_ascii=False),
        "RESP['/faturacao/subcategorias'] = () => ({ data: [] });",
        "RESP['/faturacao/grupos-personalizacao'] = () => ({ data: [] });",
        resposta_artigos,
        "RESP['PUT /faturacao/produtos/p-solto'] = () => ({ data: {} });",
        "RESP['PUT /faturacao/produtos/p-ligado'] = () => ({ data: {} });",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatProdutos)); });",
        "await act(async () => {});",
        "const botaoDe = (texto) => Array.from(alvo.querySelectorAll('button'))",
        "  .find((b) => (b.textContent || '').includes(texto));",
        "const porTestid = (t) => alvo.querySelector('[data-testid=\"' + t + '\"]');",
        "const carregar_em = async (n) => { await act(async () => { n.click(); });",
        "  await act(async () => {}); };",
        "const zona = () => (porTestid('produto-ligacao-vendus') || {}).textContent || '';",
        "const editar = async (id) => {",
        "  await carregar_em(porTestid('edit-produto-' + id));",
        "};",
        # O «Guardar» é um `<Button type=\"submit\">` sem `onClick`: quem grava
        # e' o `onSubmit` do formulario. Nesta montagem o Botao esta'
        # substituido por um `<button type=\"button\">`, que nunca submete
        # nada — carregar nele nao provaria coisa nenhuma. Entao submete-se o
        # FORMULARIO, que e' exactamente o caminho do browser a serio.
        "const gravar = async () => {",
        "  const form = alvo.querySelector('form');",
        "  await act(async () => { form.dispatchEvent(",
        "    new dom.window.Event('submit', { bubbles: true, cancelable: true })); });",
        "  await act(async () => {});",
        "};",
        "const saida = {};",
    ] + passos + [
        "saida.pedidos = pedidos.map((p) => ({ metodo: p.metodo, url: p.url, corpo: p.corpo }));",
        "process.stdout.write(JSON.stringify(saida));",
    ])


def _monta(passos, tmp, nome, **kw):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _guiao(passos, **kw), tmp, nome)


def _corpo_do_put(saida, produto_id):
    puts = [p for p in saida["pedidos"]
            if p["metodo"] == "put" and p["url"].endswith("/produtos/%s" % produto_id)]
    assert puts, [p["url"] for p in saida["pedidos"]]
    return puts[-1]["corpo"]


# --- Um produto NOVO: o estado diz-se antes de haver estrago -----------------


@pytest.fixture(scope="module")
def ficha_nova(tmp_path_factory):
    return _monta([
        "await carregar_em(botaoDe('Novo produto'));",
        "saida.zona = zona();",
        "saida.tem_botao_escolher = !!porTestid('escolher-artigo-vendus-btn');",
    ], tmp_path_factory.mktemp("ficha-nova"), "ficha-nova.js")


def test_a_ficha_de_um_produto_NOVO_mostra_a_area_da_ligacao(ficha_nova):
    """«na hora de criar um artigo ter na ficha dele uma área» — literalmente
    o pedido. Antes não havia campo nenhum: a ligação só podia nascer da
    importação a acertar no nome."""
    assert ficha_nova["zona"], "A ficha do produto novo não tem área de ligação ao Vendus."
    assert ficha_nova["tem_botao_escolher"], "Não há por onde escolher o artigo."


def test_a_ficha_nova_DIZ_o_que_acontece_se_ficar_sem_ligacao(ficha_nova):
    """«Sem ligação» não diz nada a quem não conhece a mecânica. O que se tem
    de ler é a consequência: cada venda deixa um artigo novo no Vendus."""
    assert "cria um artigo novo a cada venda" in ficha_nova["zona"], ficha_nova["zona"]


# --- Escolher: a ligação chega mesmo ao servidor -----------------------------


@pytest.fixture(scope="module")
def escolha(tmp_path_factory):
    """Abre a ficha do produto sem ligação, escolhe o artigo do Vendus e grava.

    Pela EDIÇÃO e não pela criação: o formulário novo pede a categoria num
    `Select`, que nesta montagem está substituído; a edição chega com tudo
    preenchido e deixa o teste medir o que interessa — o corpo do pedido."""
    return _monta([
        "await editar('p-solto');",
        "saida.antes = zona();",
        "await carregar_em(porTestid('escolher-artigo-vendus-btn'));",
        "saida.lista = (porTestid('artigos-vendus-lista') || {}).textContent || '';",
        "await carregar_em(porTestid('artigo-vendus-171258999'));",
        "saida.depois = zona();",
        "await gravar();",
    ], tmp_path_factory.mktemp("escolha"), "escolha.js")


def test_o_escolhedor_MOSTRA_os_artigos_da_conta_vendus(escolha):
    assert "Brigadeiro da casa" in escolha["lista"], escolha["lista"]
    assert "Açaí Mini" in escolha["lista"], escolha["lista"]


def test_o_escolhedor_AVISA_quando_o_artigo_ja_esta_a_ser_usado(escolha):
    """Dois produtos nossos no mesmo artigo do Vendus não partem a emissão,
    mas baralham o catálogo de lá — e por engano, que é o que se evita."""
    assert "Açaí Mini" in escolha["lista"]
    assert "já ligado" in escolha["lista"].lower(), escolha["lista"]


def test_escolher_um_artigo_LIGA_o_produto_no_servidor(escolha):
    """O ecrã podia mostrar o artigo escolhido e não o mandar a lado nenhum —
    desenhava-se exactamente igual, e o produto continuava a criar lixo."""
    assert "Brigadeiro da casa" in escolha["depois"], escolha["depois"]
    assert _corpo_do_put(escolha, "p-solto")["vendus_ref"] == "171258999"


# --- O defeito silencioso: gravar não pode CORTAR a ligação ------------------


@pytest.fixture(scope="module")
def gravar_sem_tocar(tmp_path_factory):
    return _monta([
        "await editar('p-ligado');",
        "saida.zona = zona();",
        "await gravar();",
    ], tmp_path_factory.mktemp("sem-tocar"), "sem-tocar.js")


def test_a_ficha_de_um_produto_LIGADO_diz_a_que_artigo(gravar_sem_tocar):
    assert "171258472" in gravar_sem_tocar["zona"], gravar_sem_tocar["zona"]


def test_gravar_sem_tocar_na_ligacao_NAO_a_corta(gravar_sem_tocar):
    """O PUT substitui o registo inteiro: um formulário que não reenvie o
    `vendus_ref` põe-no a nulo em silêncio, e o produto passa a criar um
    artigo novo por venda sem ninguém ter pedido nada."""
    assert _corpo_do_put(gravar_sem_tocar, "p-ligado")["vendus_ref"] == "171258472"


# --- Desligar de propósito ---------------------------------------------------


@pytest.fixture(scope="module")
def desligar(tmp_path_factory):
    return _monta([
        "await editar('p-ligado');",
        "await carregar_em(porTestid('desligar-artigo-vendus-btn'));",
        "saida.zona = zona();",
        "await gravar();",
    ], tmp_path_factory.mktemp("desligar"), "desligar.js")


def test_desligar_do_vendus_e_possivel_e_CHEGA_ao_servidor(desligar):
    """Há razões legítimas (um artigo apagado no Vendus). O que não pode é
    acontecer sem se querer — por isso é um botão, e não um efeito lateral."""
    assert _corpo_do_put(desligar, "p-ligado")["vendus_ref"] is None
    assert "cria um artigo novo a cada venda" in desligar["zona"], desligar["zona"]


# --- O Vendus em baixo -------------------------------------------------------


@pytest.fixture(scope="module")
def vendus_em_baixo(tmp_path_factory):
    return _monta([
        "await editar('p-solto');",
        "await carregar_em(porTestid('escolher-artigo-vendus-btn'));",
        "saida.zona = zona();",
    ], tmp_path_factory.mktemp("vendus-baixo"), "vendus-baixo.js",
        artigos_falham=True)


def test_com_o_vendus_em_baixo_o_escolhedor_DIZ_O_QUE_SE_PASSA(vendus_em_baixo):
    """Uma lista vazia com ar de sucesso dizia «esta conta não tem artigos», e
    o dono gravava sem ligação a acreditar que não havia nada para escolher."""
    texto = vendus_em_baixo["zona"].lower()
    assert "vendus" in texto
    assert ("não foi possível" in texto or "indisponível" in texto), vendus_em_baixo["zona"]


@pytest.fixture(scope="module")
def sem_artigos(tmp_path_factory):
    return _monta([
        "await editar('p-solto');",
        "await carregar_em(porTestid('escolher-artigo-vendus-btn'));",
        "saida.zona = zona();",
    ], tmp_path_factory.mktemp("sem-artigos"), "sem-artigos.js", artigos=[])


def test_uma_conta_vendus_mesmo_vazia_diz_se(sem_artigos):
    assert "nenhum artigo" in sem_artigos["zona"].lower(), sem_artigos["zona"]
