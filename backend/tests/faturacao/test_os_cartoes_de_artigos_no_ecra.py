"""**Os dois cartões de artigos, desenhados a sério** (React + jsdom).

A aritmética está provada em `test_o_topo_de_artigos_do_painel.py`, sem ecrã
nenhum. O que só se vê montando o ecrã é o que já custou dois defeitos neste
módulo (ver `faturacao-lacai-licoes`): **um cartão desenha-se sem servidor
nenhum**, e a resposta certa do backend com um nome de campo que o JSX não lê
não dá erro nenhum — dá uma lista de nomes com um espaço em branco ao lado.

Era exactamente o que ia acontecer: o ecrã lia `item.total`; o backend novo
manda `valor` e `resultado`.

E prende-se aqui a coisa que o cartão da margem existe para dizer. Com 0 de 33
artigos com preço de custo — o estado real das cinco lojas no dia em que isto
se escreveu — «Sem informação disponível» é verdade e não serve para nada: não
diz porquê nem o que fazer.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_CARTAO = {"valor": 290.75, "valor_comparado": 115.12, "variacao": 152.56,
           "comparacao": "Hoje contra ontem"}
_BASE = {
    "ha_vendas": True, "hora_de_corte": None,
    "cartoes": {"hoje": _CARTAO, "mensal": _CARTAO, "anual": _CARTAO},
    "serie_diaria": [{"data": "2026-08-28", "valor": 290.75}],
    "ultimos_6_meses": [], "por_loja": [],
    "mais_vendidos": [], "mais_rentaveis": [],
    "artigos_sem_custo": 0, "artigos_vendidos": 0,
    "documentos_por_repartir": 0,
}


def _monta(dashboard, leituras, tmp_path, nome):
    """Monta o painel com a resposta dada e devolve o que o cenário leu.

    **Dentro de um `MemoryRouter`** — como na aplicação a sério, onde este
    ecrã vive sempre dentro do router. Sem ele, o `<Link>` do estado vazio
    rebenta com «Cannot destructure property 'basename'» e leva o ficheiro
    inteiro consigo.
    """
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const { MemoryRouter } = require('react-router-dom');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const Painel = carregar(path2.join(ADMIN, 'FatDashboard.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/dashboard'] = () => ({ data: %s });"
        % json.dumps(dict(_BASE, **dashboard), ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(",
        "  React.createElement(MemoryRouter, null, React.createElement(Painel))); });",
        "await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const saida = {};",
    ] + leituras + [
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => { "
        "process.stderr.write(String(e && e.stack || e)); process.exit(1); });" % guiao,
        tmp_path, nome)


def test_o_cartao_esta_MESMO_montado(tmp_path):
    """A primeira asserção de qualquer teste de ecrã deste repo. Sem ela, um
    `querySelector` que devolve `null` passa por «não há nada escrito» e o
    teste fica verde a medir o vazio."""
    saida = _monta({}, [
        "saida.vendidos = !!porTestid('fat-mais-vendidos');",
        "saida.rentaveis = !!porTestid('fat-mais-rentaveis');",
    ], tmp_path, "montado.js")
    assert saida["vendidos"] and saida["rentaveis"]


def test_o_mais_vendidos_escreve_a_QUANTIDADE_e_o_dinheiro(tmp_path):
    """O contrato: o backend manda `quantidade` e `valor`. O ecrã lia `total`
    — um campo que já não existe — e desenhava o nome do produto com um espaço
    em branco ao lado, sem erro nenhum."""
    saida = _monta({
        "mais_vendidos": [
            {"produto_id": "p1", "nome": "Açaí", "quantidade": 25, "valor": 185.73},
            {"produto_id": "p2", "nome": "Água 50cl", "quantidade": 3, "valor": 4.35},
        ],
        "artigos_vendidos": 2,
    }, [
        "saida.linhas = [0, 1].map((i) => (porTestid(`fat-mais-vendido-${i}`) || {}).textContent);",
        "saida.barras = [0, 1].map((i) => {",
        "  const l = porTestid(`fat-mais-vendido-${i}`);",
        "  const barra = l && l.querySelector('div[style]');",
        "  return barra ? barra.style.width : null; });",
    ], tmp_path, "vendidos.js")
    assert "Açaí" in saida["linhas"][0]
    assert "25 un" in saida["linhas"][0], saida["linhas"][0]
    assert "185,73\u00a0€" in saida["linhas"][0], "o € leva espaço fino (U+00A0)"
    assert "3 un" in saida["linhas"][1] and "4,35\u00a0€" in saida["linhas"][1]
    # A barra do primeiro enche; a do segundo dá a proporção (3 em 25 = 12%).
    assert saida["barras"][0] == "100%"
    assert saida["barras"][1] == "12%"


def test_o_mais_rentaveis_escreve_a_MARGEM_e_a_percentagem(tmp_path):
    saida = _monta({
        "mais_rentaveis": [
            {"produto_id": "p1", "nome": "Açaí", "resultado": 64.39,
             "vendas": 164.39, "margem_pct": 39.2},
        ],
        "artigos_vendidos": 1,
    }, [
        "saida.linha = (porTestid('fat-mais-rentavel-0') || {}).textContent;",
        "saida.emFalta = !!porTestid('fat-rentaveis-em-falta');",
    ], tmp_path, "rentaveis.js")
    assert "Açaí" in saida["linha"]
    assert "64,39\u00a0€" in saida["linha"]
    assert "39,2%" in saida["linha"]
    assert saida["emFalta"] is False, "não falta custo nenhum"


def test_SEM_PRECOS_DE_CUSTO_o_cartao_diz_o_que_falta_e_leva_aos_produtos(tmp_path):
    """**O estado real das cinco lojas.** O cartão não pode limitar-se a dizer
    «Sem informação disponível»: tem de dizer que falta o preço de custo, e o
    caminho para o ir preencher."""
    saida = _monta({
        "mais_rentaveis": [], "artigos_sem_custo": 6, "artigos_vendidos": 6,
        "mais_vendidos": [{"produto_id": "p1", "nome": "Açaí", "quantidade": 25,
                           "valor": 185.73}],
    }, [
        "const vazio = porTestid('fat-sem-precos-de-custo');",
        "saida.texto = vazio ? vazio.textContent : null;",
        "saida.href = vazio ? (vazio.querySelector('a') || {}).getAttribute('href') : null;",
        # O outro cartão TEM de continuar a mostrar o top: os artigos
        # venderam-se, o que falta é só o custo.
        "saida.vendidosAindaLa = !!porTestid('fat-mais-vendido-0');",
    ], tmp_path, "sem-custo.js")
    assert "6 artigos vendidos hoje" in saida["texto"], saida["texto"]
    assert "preço de custo" in saida["texto"]
    assert saida["href"] == "/admin/faturacao/produtos/lista"
    assert saida["vendidosAindaLa"] is True


def test_com_ALGUNS_custos_em_falta_a_lista_aparece_E_diz_quantos_ficaram_de_fora(tmp_path):
    """O caso do meio, que é o que se vai ver enquanto o dono preenche os
    custos: uma lista curta que parece completa, e não é."""
    saida = _monta({
        "mais_rentaveis": [{"produto_id": "p1", "nome": "Açaí", "resultado": 64.39,
                            "vendas": 164.39, "margem_pct": 39.2}],
        "artigos_sem_custo": 4, "artigos_vendidos": 5,
    }, [
        "const nota = porTestid('fat-rentaveis-em-falta');",
        "saida.nota = nota ? nota.textContent : null;",
        "saida.temLista = !!porTestid('fat-mais-rentavel-0');",
        "saida.vazioEscondido = !porTestid('fat-sem-precos-de-custo');",
    ], tmp_path, "meio.js")
    assert saida["temLista"] and saida["vazioEscondido"]
    assert saida["nota"] == "4 artigos sem preço de custo ficaram de fora."


def test_sem_vendas_nenhumas_o_vazio_NAO_fala_de_precos_de_custo(tmp_path):
    """Dois vazios diferentes. «Ainda não se vendeu nada» e «faltam os preços
    de custo» não são a mesma coisa, e mandar o dono preencher custos às nove
    da manhã, quando o problema é só ainda não ter aberto a loja, é ruído."""
    saida = _monta({}, [
        "saida.semCusto = !!porTestid('fat-sem-precos-de-custo');",
        "saida.rentaveis = (porTestid('fat-mais-rentaveis') || {}).textContent;",
        "saida.vendidos = (porTestid('fat-mais-vendidos') || {}).textContent;",
    ], tmp_path, "sem-vendas.js")
    assert saida["semCusto"] is False
    assert "Ainda não se vendeu nada hoje" in saida["rentaveis"]
    assert "Ainda não se vendeu nada hoje" in saida["vendidos"]


def test_uma_fatura_POR_REPARTIR_e_dita_no_ecra(tmp_path):
    """O dinheiro dela está no cartão «Hoje» e não está no top. Dois números
    certos lado a lado, sem legenda, dão uma leitura falsa — foi o defeito que
    este painel já teve três vezes."""
    saida = _monta({
        "mais_vendidos": [{"produto_id": "p1", "nome": "Açaí", "quantidade": 2,
                           "valor": 20.00}],
        "documentos_por_repartir": 1, "artigos_vendidos": 1,
    }, [
        "const nota = porTestid('fat-por-repartir');",
        "saida.nota = nota ? nota.textContent : null;",
    ], tmp_path, "por-repartir.js")
    assert saida["nota"] is not None
    assert "1 fatura de hoje não se deixou repartir" in saida["nota"]
    assert "cartão Hoje" in saida["nota"]


def test_com_os_custos_TODOS_LA_e_sem_margem_o_ecra_NAO_manda_preencher_custos(tmp_path):
    """O dia em que se vendeu e se devolveu tudo: os custos estão todos
    preenchidos e a lista está na mesma vazia.

    A frase «faltam os preços de custo» mandava o dono procurar um problema
    que não existe — e o «ainda não se vendeu nada hoje» era falso, porque
    vendeu-se e devolveu-se."""
    saida = _monta({
        "mais_rentaveis": [], "artigos_sem_custo": 0, "artigos_vendidos": 3,
    }, [
        "const vazio = porTestid('fat-sem-precos-de-custo');",
        "saida.texto = vazio ? vazio.textContent : null;",
        "saida.temBotao = vazio ? !!vazio.querySelector('a') : null;",
    ], tmp_path, "sem-margem.js")
    assert saida["texto"] == "Nenhum artigo com margem para mostrar hoje."
    assert saida["temBotao"] is False, "não há custo nenhum para ir preencher"


def test_com_ALGUNS_custos_em_falta_e_sem_lista_a_frase_diz_QUANTOS_de_quantos(tmp_path):
    """Nem todos, nem nenhum. Dizer «nenhum dos 5 tem preço de custo» quando
    dois têm era mentira — e o dono, que preencheu esses dois, ia procurar o
    que já tinha feito."""
    saida = _monta({
        "mais_rentaveis": [], "artigos_sem_custo": 3, "artigos_vendidos": 5,
    }, [
        "const vazio = porTestid('fat-sem-precos-de-custo');",
        "saida.texto = vazio ? vazio.textContent : null;",
    ], tmp_path, "alguns.js")
    assert "3 dos 5 artigos vendidos hoje não têm preço de custo." in saida["texto"]


def test_um_artigo_VENDIDO_A_PERDER_nao_se_pinta_da_cor_do_lucro(tmp_path):
    """Visto a olho, com o CSS compilado, antes de existir este teste: a linha
    de −4,58 € saía no mesmo azul das que deram dinheiro, com uma barra igual.
    De relance, mais uma que correu bem."""
    saida = _monta({
        "mais_rentaveis": [
            {"produto_id": "p1", "nome": "Açaí", "resultado": 64.39,
             "vendas": 164.39, "margem_pct": 39.2},
            {"produto_id": "p9", "nome": "Promoção", "resultado": -4.58,
             "vendas": 4.42, "margem_pct": -103.6},
        ],
        "artigos_vendidos": 2,
    }, [
        "saida.classes = [0, 1].map((i) => {",
        "  const l = porTestid(`fat-mais-rentavel-${i}`);",
        "  const barra = l && l.querySelector('div[style]');",
        "  const numero = l && l.querySelector('span span');",
        "  return { barra: barra && barra.className, numero: numero && numero.className }; });",
    ], tmp_path, "a-perder.js")
    bom, mau = saida["classes"]
    assert "bg-primary" in bom["barra"] and "text-destructive" not in bom["numero"]
    assert "bg-destructive" in mau["barra"], mau
    assert "text-destructive" in mau["numero"], mau
