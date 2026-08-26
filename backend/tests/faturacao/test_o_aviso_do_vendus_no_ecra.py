"""**«Estão todos os artigos ligados a um produto no Vendus?»** — a pergunta do
dono, respondida no ecrã e não um produto de cada vez.

A resposta já existia: um ícone de corrente ao lado do nome, na tabela dos
produtos. Ver 200 produtos à procura de correntes em falta é a mesma coisa que
não saber, e foi por isso que a conta real do Vendus chegou a ter 14 "Açaí
Mini", 13 deles sem categoria nenhuma. Uma linha de fatura sem `id` faz o
Vendus CRIAR um artigo novo — não casa por nome.

Este ficheiro monta o `FatProdutos` a sério (React, jsdom, o mesmo `carregar`
dos outros ecrãs) e mede o que se VÊ, porque duas vezes um ecrã do POS foi
para produção a compilar e a mentir. As três coisas que interessam:

1. o aviso aparece, e diz quantos são;
2. carregar em «Ver produtos» deixa na tabela SÓ esses;
3. quem está ligado não leva aviso nenhum — um aviso que aparece sempre é um
   aviso que se deixa de ler.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _CATEGORIA, _COMPONENTES

# O que o servidor devolve — o `ativo` incluído, porque é ele que separa «isto
# está à venda e cria lixo a cada venda» de «isto está desligado».
_LIGADO = {
    "id": "p-ligado", "nome": "Açaí Regular", "categoria_id": "cat-1",
    "preco": 8.99, "tax_id": "INT", "vendus_ref": "171258472",
    "grupos_personalizacao": [], "ativo": True,
}
_SOLTO = {
    "id": "p-solto", "nome": "Brigadeiro", "categoria_id": "cat-1",
    "preco": 1.50, "tax_id": "NOR", "grupos_personalizacao": [], "ativo": True,
}
_SOLTO_LIXO = {
    "id": "p-lixo", "nome": "Água das Pedras", "categoria_id": "cat-1",
    "preco": 1.20, "tax_id": "INT", "vendus_ref": "VACA123",
    "grupos_personalizacao": [], "ativo": True,
}
_SOLTO_DESLIGADO = {
    "id": "p-desligado", "nome": "Açaí de Verão", "categoria_id": "cat-1",
    "preco": 7.00, "tax_id": "INT", "grupos_personalizacao": [], "ativo": False,
}

_TODOS = [_LIGADO, _SOLTO, _SOLTO_LIXO, _SOLTO_DESLIGADO]
# O que o `/produtos/sem-vendus` devolveria para estes quatro — pela regra da
# emissão: o que não tem campo, e o `VACA123`, que é texto e não um id.
_SEM_VENDUS = [_SOLTO, _SOLTO_LIXO, _SOLTO_DESLIGADO]


def _guiao(passos):
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatProdutos = carregar(path2.join(ADMIN, 'FatProdutos.js')).default;",
        "const RESP = RESPOSTAS_GESTAO;",
        "RESP['/faturacao/produtos'] = () => ({ data: %s });"
        % json.dumps(_TODOS, ensure_ascii=False),
        "RESP['/faturacao/produtos/sem-iva'] = () => ({ data: [] });",
        "RESP['/faturacao/produtos/sem-vendus'] = () => ({ data: %s });"
        % json.dumps(_SEM_VENDUS, ensure_ascii=False),
        "RESP['/faturacao/categorias'] = () => ({ data: [%s] });"
        % json.dumps(_CATEGORIA, ensure_ascii=False),
        "RESP['/faturacao/subcategorias'] = () => ({ data: [] });",
        "RESP['/faturacao/grupos-personalizacao'] = () => ({ data: [] });",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatProdutos)); });",
        "await act(async () => {});",
        "const linhas = () => Array.from(alvo.querySelectorAll('[data-testid]'))",
        "  .map((n) => n.getAttribute('data-testid'))",
        "  .filter((t) => t && t.indexOf('produto-row-') === 0);",
        "const saida = {};",
    ] + passos + [
        "process.stdout.write(JSON.stringify(saida));",
    ])


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    """Monta o ecrã, lê o aviso, e carrega no «Ver produtos» para ver o que
    sobra na tabela."""
    passos = [
        "saida.aviso = !!alvo.querySelector('[data-testid=\"alerta-sem-vendus\"]');",
        "saida.texto_do_aviso = (alvo.querySelector(",
        "  '[data-testid=\"alerta-sem-vendus\"]') || {}).textContent || '';",
        "saida.linhas_antes = linhas();",
        "const ver = alvo.querySelector('[data-testid=\"ver-produtos-sem-vendus-btn\"]');",
        "saida.tem_botao = !!ver;",
        "await act(async () => { ver.click(); });",
        "await act(async () => {});",
        "saida.linhas_depois = linhas();",
        "saida.tem_pastilha = !!alvo.querySelector(",
        "  '[data-testid=\"limpar-filtro-sem-vendus\"]');",
        # E o caminho de volta: a pastilha limpa o filtro.
        "await act(async () => {",
        "  alvo.querySelector('[data-testid=\"limpar-filtro-sem-vendus\"]').click(); });",
        "await act(async () => {});",
        "saida.linhas_no_fim = linhas();",
    ]
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _guiao(passos),
        tmp_path_factory.mktemp("aviso-vendus"), "montar-aviso-vendus.js")


def test_o_ecra_AVISA_que_ha_artigos_sem_ligacao_ao_vendus(ecra):
    """Sem isto a resposta à pergunta do dono era percorrer a tabela à procura
    de correntes em falta — na prática, «não sei»."""
    assert ecra["aviso"], "O ecrã dos produtos não avisa que há artigos por ligar."


def test_o_aviso_CONTA_so_os_que_estao_a_venda(ecra):
    """Três produtos sem ligação, mas um está desligado — não está na grelha do
    POS e não cria artigo nenhum. Contá-lo era assustar por causa de coisa que
    ninguém vende."""
    assert "2 produtos" in ecra["texto_do_aviso"], ecra["texto_do_aviso"]


def test_o_aviso_DIZ_o_que_acontece_se_nao_se_fizer_nada(ecra):
    """«2 produtos sem ligação» não move ninguém. O que move é saber que cada
    venda deixa lixo no catálogo do Vendus — e qual é o botão que resolve."""
    texto = ecra["texto_do_aviso"]
    assert "cria um artigo novo a cada venda" in texto, texto
    assert "Importar do Vendus" in texto, texto


def test_VER_PRODUTOS_deixa_na_tabela_so_os_que_nao_ligam(ecra):
    """Um aviso que não leva a lado nenhum obriga a procurar à mão o que ele
    acabou de contar."""
    assert ecra["tem_botao"], "O aviso não tem por onde ver os produtos."
    assert set(ecra["linhas_antes"]) == {
        "produto-row-p-ligado", "produto-row-p-solto",
        "produto-row-p-lixo", "produto-row-p-desligado"}
    assert set(ecra["linhas_depois"]) == {
        "produto-row-p-solto", "produto-row-p-lixo", "produto-row-p-desligado"}, (
        "A tabela filtrada devia mostrar os que não ligam — e o ligado devia sair.")


def test_a_pastilha_DESFAZ_o_filtro(ecra):
    """Filtrar sem saber como voltar atrás obriga a recarregar o ecrã."""
    assert ecra["tem_pastilha"], "Não há pastilha a dizer que o filtro está ligado."
    assert len(ecra["linhas_no_fim"]) == 4


@pytest.fixture(scope="module")
def ecra_limpo(tmp_path_factory):
    """O outro lado: com tudo ligado, o ecrã não avisa de nada."""
    guiao = _guiao([
        "saida.aviso = !!alvo.querySelector('[data-testid=\"alerta-sem-vendus\"]');",
        "saida.texto = textoVisivel(alvo);",
    ]).replace(
        "RESP['/faturacao/produtos/sem-vendus'] = () => ({ data: %s });"
        % json.dumps(_SEM_VENDUS, ensure_ascii=False),
        "RESP['/faturacao/produtos/sem-vendus'] = () => ({ data: [] });",
    )
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % guiao,
        tmp_path_factory.mktemp("aviso-vendus-limpo"), "montar-sem-aviso.js")


def test_com_tudo_ligado_NAO_ha_aviso_nenhum(ecra_limpo):
    """Um aviso que aparece sempre deixa de se ler — e o dia em que aparecer a
    sério passa despercebido."""
    assert not ecra_limpo["aviso"], (
        "O aviso aparece mesmo com todos os produtos ligados ao Vendus.")
    assert "sem ligação ao Vendus" not in ecra_limpo["texto"]
