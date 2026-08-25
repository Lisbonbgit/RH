"""**As gavetas da grelha do POS** — montadas e carregadas, não lidas.

O dono pediu subcategorias dentro de cada categoria para arrumar a grelha do
balcão. Do lado do ecrã são uma segunda linha de botões dentro do separador
aberto, e as regras que interessam são as que decidem quando ela NÃO aparece:

1. no separador "Todos" não há gavetas (uma subcategoria é de UMA categoria);
2. uma gaveta vazia não aparece — é um toque perdido ao balcão;
3. "Outros" só existe quando há mesmo produtos por arrumar;
4. sem subcategorias nenhumas, a grelha fica exactamente como era.

E a que decide se o trabalho serve para alguma coisa: carregar numa gaveta
mostra os produtos dela, e só esses.
"""
import json

import pytest

from faturacao.pos_catalogo import _produto_publico

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_CAT = {"id": "cat-1", "nome": "Venda ao Público", "ordem": 0, "ativa": True}
_SUB_ACAIS = {"id": "sub-acais", "categoria_id": "cat-1", "nome": "Açaís", "ordem": 0}
_SUB_SALGADOS = {"id": "sub-salgados", "categoria_id": "cat-1", "nome": "Salgados", "ordem": 1}


def _produto(id_, nome, preco, subcategoria_id=None):
    return _produto_publico({
        "id": id_, "nome": nome, "categoria_id": "cat-1",
        "subcategoria_id": subcategoria_id, "preco": preco, "tax_id": "INT",
        "foto_url": None, "grupos_personalizacao": [], "ativo": True,
    })


def _cenario(catalogo, toques):
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "SUBSTITUIDOS.delete(path2.join(POS, 'PosVenda.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: 'Loja' });",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosVenda = carregar(path2.join(POS, 'PosVenda.js')).default;",
        "RESPOSTAS_POS['/pos/catalogo'] = () => ({ data: %s });"
        % json.dumps(catalogo, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/tipos-pagamento'] = () => ({ data: [] });",
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: null });",
        "RESPOSTAS_POS['/pos/venda/repartidas'] = () => ({ data: { grupos: [] } });",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "RESPOSTAS_POS['/pos/impressao/estado'] = () => ({ data:"
        " { ha_programa: true, por_sair: 0, falhados: 0 } });",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(PosVenda, {",
        "  operador: { id: 'o1', nome: 'Ana' }, caixa: { id: 'c1', nome: 'Balcão' },",
        "  sessao: { id: 's1', fundo: 50 }, lojaNome: 'Loja',",
        "  onSair: () => {}, onCaixaFechada: () => {}, modo: 'normal' })); });",
        "await act(async () => {});",
        "await act(async () => {});",
        # O botão EXACTO (não "contém"): "Todos" e "Todas" partilham prefixo, e
        # apanhar o separador quando se queria a gaveta media outra coisa.
        "const botao = (texto) => [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').trim() === texto);",
        "const carregar_em = async (texto) => {",
        "  const b = botao(texto);",
        "  if (!b) throw new Error('sem botão \\'' + texto + '\\' — no ecrã: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  await act(async () => { b.click(); });",
        "  await act(async () => {});",
        "};",
        "const registo = {};",
        toques,
        "process.stdout.write(JSON.stringify(registo));",
    ])


def _correr(catalogo, toques, tmp_path_factory, nome):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _cenario(catalogo, toques), tmp_path_factory.mktemp(nome), "montar-%s.js" % nome)


_COM_GAVETAS = {
    "categorias": [_CAT],
    "subcategorias": [_SUB_ACAIS, _SUB_SALGADOS],
    "produtos": [
        _produto("p1", "Açaí Regular", 8.99, "sub-acais"),
        _produto("p2", "Coxinha", 3.10, "sub-salgados"),
        _produto("p3", "Água", 1.00),
    ],
    "grupos_personalizacao": [],
    "produtos_ocultos_categoria_inativa": 0,
}


@pytest.fixture(scope="module")
def gavetas(tmp_path_factory):
    return _correr(_COM_GAVETAS, "\n".join([
        "registo.emTodos = textoVisivel(alvo);",
        "await carregar_em('Venda ao Público');",
        "registo.noSeparador = textoVisivel(alvo);",
        "await carregar_em('Açaís');",
        "registo.emAcais = textoVisivel(alvo);",
        "await carregar_em('Outros');",
        "registo.emOutros = textoVisivel(alvo);",
    ]), tmp_path_factory, "gavetas")


def test_no_separador_TODOS_nao_ha_gavetas(gavetas):
    """Uma subcategoria é de UMA categoria: em "Todos" não há nenhuma que
    faça sentido, e uma linha de botões que filtrasse metade da grelha seria
    pior do que não existir."""
    assert "Açaí Regular" in gavetas["emTodos"] and "Coxinha" in gavetas["emTodos"]
    assert "Açaís" not in gavetas["emTodos"], gavetas["emTodos"][:400]


def test_dentro_da_categoria_aparecem_as_gavetas(gavetas):
    for nome in ("Todas", "Açaís", "Salgados", "Outros"):
        assert nome in gavetas["noSeparador"], (nome, gavetas["noSeparador"][:400])


def test_carregar_numa_gaveta_mostra_so_os_produtos_dela(gavetas):
    assert "Açaí Regular" in gavetas["emAcais"]
    assert "Coxinha" not in gavetas["emAcais"], gavetas["emAcais"][:400]
    assert "Água" not in gavetas["emAcais"], gavetas["emAcais"][:400]


def test_OUTROS_e_a_gaveta_de_quem_ninguem_arrumou(gavetas):
    assert "Água" in gavetas["emOutros"]
    assert "Açaí Regular" not in gavetas["emOutros"], gavetas["emOutros"][:400]


@pytest.fixture(scope="module")
def sem_subcategorias(tmp_path_factory):
    catalogo = dict(_COM_GAVETAS, subcategorias=[], produtos=[
        _produto("p1", "Açaí Regular", 8.99), _produto("p3", "Água", 1.00)])
    return _correr(catalogo, "\n".join([
        "await carregar_em('Venda ao Público');",
        "registo.noSeparador = textoVisivel(alvo);",
    ]), tmp_path_factory, "sem-subcategorias")


def test_sem_subcategorias_a_grelha_fica_como_era(sem_subcategorias):
    """Enquanto ninguém criar uma subcategoria, o ecrã não muda — nem uma
    linha de botões a mais, nem um "Outros" a dizer que há arrumação por
    fazer."""
    assert "Açaí Regular" in sem_subcategorias["noSeparador"]
    assert "Todas" not in sem_subcategorias["noSeparador"], \
        sem_subcategorias["noSeparador"][:400]
    assert "Outros" not in sem_subcategorias["noSeparador"], \
        sem_subcategorias["noSeparador"][:400]


@pytest.fixture(scope="module")
def gaveta_vazia(tmp_path_factory):
    catalogo = dict(_COM_GAVETAS, produtos=[_produto("p1", "Açaí Regular", 8.99, "sub-acais")])
    return _correr(catalogo, "\n".join([
        "await carregar_em('Venda ao Público');",
        "registo.noSeparador = textoVisivel(alvo);",
    ]), tmp_path_factory, "gaveta-vazia")


def test_uma_gaveta_sem_produtos_nao_aparece(gaveta_vazia):
    """"Salgados" existe no backoffice mas não tem nada à frente. Um botão que
    só pode mostrar uma grelha vazia é um toque perdido ao balcão."""
    assert "Açaís" in gaveta_vazia["noSeparador"]
    assert "Salgados" not in gaveta_vazia["noSeparador"], \
        gaveta_vazia["noSeparador"][:400]
    assert "Outros" not in gaveta_vazia["noSeparador"], (
        "com tudo arrumado, não há 'Outros': %s" % gaveta_vazia["noSeparador"][:400]
    )
