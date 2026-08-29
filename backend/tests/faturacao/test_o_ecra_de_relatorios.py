"""**O ecrã dos relatórios** — montado e carregado, não lido.

Nove vistas da mesma tabela: o que este ficheiro prova é que trocar de vista
vai buscar a vista certa, que as colunas dos prints estão lá com o rodapé à
letra, e que o "—" aparece onde não há custo (em vez de um zero, que fazia o
lucro parecer total).
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_PRODUTOS = {
    "dimensao": "produto", "de": "2026-08-01", "ate": "2026-08-25",
    "com_quantidade": True, "truncado": False,
    "linhas": [
        {"chave": "p-acai", "rotulo": "Açaí Regular", "bruto": 10.20, "liquido": 9.03,
         "custo": 4.00, "resultado": 5.03, "custo_incompleto": False,
         "quantidade": 3, "faturas": 1, "rectificacoes": 0,
         "tamanhos": [{"nome": "Mini", "quantidade": 2}, {"nome": "Supreme", "quantidade": 1}]},
        {"chave": "p-cola", "rotulo": "Coca-Cola", "bruto": 1.15, "liquido": 0.93,
         "custo": None, "resultado": None, "custo_incompleto": True,
         "quantidade": 1, "faturas": 1, "rectificacoes": 0, "tamanhos": []},
    ],
    "total": {"chave": None, "rotulo": "TOTAL", "bruto": 11.35, "liquido": 9.96,
              "custo": None, "resultado": None, "custo_incompleto": True,
              "quantidade": 2, "faturas": 1, "rectificacoes": 0},
    # Uma série de DIAS, como o servidor a manda para esta vista — é ela que
    # o gráfico de área desenha.
    "serie": [{"rotulo": "2026-08-%02d" % d, "valor": 10.0 + d} for d in range(1, 26)],
}

_HORA = {
    "dimensao": "hora", "de": "2026-08-01", "ate": "2026-08-25",
    "com_quantidade": False, "truncado": False,
    "linhas": [
        {"chave": 17, "rotulo": "17h", "bruto": 57.54, "liquido": 50.92,
         "custo": 20.00, "resultado": 30.92, "custo_incompleto": False,
         "quantidade": None, "faturas": 5, "rectificacoes": 0},
    ],
    "total": {"chave": None, "rotulo": "TOTAL", "bruto": 57.54, "liquido": 50.92,
              "custo": 20.00, "resultado": 30.92, "custo_incompleto": False,
              "quantidade": None, "faturas": 5, "rectificacoes": 0},
    # A série de uma vista de BARRAS são as PRÓPRIAS linhas da tabela.
    "serie": [{"rotulo": "%dh" % h, "valor": 10.0 * h} for h in range(9, 21)],
}


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    cenario = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatRelatorios = carregar(path2.join(ADMIN, 'FatRelatorios.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: [] });",
        "RESPOSTAS_GESTAO['/faturacao/utilizadores'] = () => ({ data: [] });",
        "RESPOSTAS_GESTAO['/faturacao/categorias'] = () => ({ data: [] });",
        "RESPOSTAS_GESTAO['/faturacao/relatorios/produto'] = () => ({ data: %s });"
        % json.dumps(_PRODUTOS, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/relatorios/hora'] = () => ({ data: %s });"
        % json.dumps(_HORA, ensure_ascii=False),
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatRelatorios)); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const produtos = textoVisivel(alvo);",
        "const html_produtos = alvo.innerHTML;",
        "const trocar = alvo.querySelector('[data-testid=\"vista-hora\"]');",
        "if (!trocar) throw new Error('sem selector de vista: ' + produtos.slice(0, 300));",
        "await act(async () => { trocar.click(); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "process.stdout.write(JSON.stringify({",
        "  produtos, html_produtos, hora: textoVisivel(alvo),",
        "  html_hora: alvo.innerHTML,",
        "  pedidos: pedidos.map((p) => ({ url: p.url, params: p.params || null })),",
        "}));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp("relatorios"), "montar-relatorios.js")


def test_a_tabela_tem_as_colunas_dos_prints(ecra):
    for coluna in ("Vendas c/IVA", "Vendas", "Custos", "Resultado", "Quantidade",
                   "Nº Vendas", "Nº Rectificações"):
        assert coluna in ecra["produtos"], (coluna, ecra["produtos"][:500])


def test_o_rodape_explica_as_duas_contagens(ecra):
    """As duas contagens não se somam, e o rodapé dos prints diz porquê."""
    assert "Fatura Simplificada" in ecra["produtos"], ecra["produtos"][:600]
    assert "Nota de Crédito" in ecra["produtos"] or "Nota de Crédito".lower() in ecra["produtos"].lower()


def test_onde_nao_ha_custo_aparece_um_traco_e_nao_um_zero(ecra):
    """Um zero ali fazia o Resultado parecer lucro inteiro."""
    assert "—" in ecra["produtos"], ecra["produtos"][:600]
    assert "sem preço de custo" in ecra["produtos"], ecra["produtos"][:800]


def test_a_linha_TOTAL_esta_la(ecra):
    assert "TOTAL" in ecra["produtos"], ecra["produtos"][:600]
    assert "€ 11,35" in ecra["produtos"], ecra["produtos"][:600]


def test_trocar_de_vista_vai_buscar_a_vista_certa(ecra):
    assert any(p["url"].endswith("/faturacao/relatorios/hora") for p in ecra["pedidos"]), \
        ecra["pedidos"]
    assert "17h" in ecra["hora"], ecra["hora"][:400]
    # Por Hora não tem coluna Quantidade — é o que os prints mostram.
    assert "Quantidade" not in ecra["hora"], ecra["hora"][:600]


def test_os_filtros_vazios_NAO_viajam(ecra):
    relatorios = [p for p in ecra["pedidos"] if "/relatorios/" in p["url"]]
    assert relatorios, ecra["pedidos"]
    params = relatorios[0]["params"] or {}
    assert params.get("loja_id") is None and params.get("utilizador_id") is None
    assert params.get("de") and params.get("ate")


# --- os gráficos, que são o que o dono pediu ---------------------------------
#
# «Quero este mesmo tipo nas páginas de relatórios.» A curva do painel, aqui.
# E: «o por hora, dias da semana e mensal não estão bonitos» — esses são
# barras, porque entre «Segunda» e «Terça» não há nada e uma curva a ligá-las
# desenha uma subida que não existe.

def test_a_vista_de_PRODUTOS_desenha_a_CURVA_do_painel(ecra):
    assert 'data-testid="fat-relatorio-area"' in ecra["html_produtos"], "não é o gráfico de área"
    assert 'data-testid="fat-relatorio-barras"' not in ecra["html_produtos"]


def test_a_vista_POR_HORA_desenha_BARRAS_e_nao_uma_curva(ecra):
    assert 'data-testid="fat-relatorio-barras"' in ecra["html_hora"]
    assert 'data-testid="fat-relatorio-area"' not in ecra["html_hora"]


def test_a_curva_dos_relatorios_e_a_MESMA_do_painel(ecra):
    """A mesma caixa e a mesma grelha — é literalmente o mesmo componente. Se
    um dia forem dois desenhos, este número deixa de bater."""
    from .test_o_toque_nos_graficos_do_painel import _AREA
    assert 'viewBox="0 0 %d %d"' % (_AREA["largura"], _AREA["altura"]) in ecra["html_produtos"]


def test_os_TAMANHOS_do_acai_aparecem_por_baixo_do_artigo(ecra):
    """«Não esqueça do açaí que tem as personalizações de tamanhos.»"""
    assert "Mini 2 · Supreme 1" in ecra["produtos"], ecra["produtos"][:800]


def test_um_artigo_SEM_tamanhos_nao_ganha_linha_nenhuma(ecra):
    """A Coca-Cola não tem tamanho. Uma segunda linha vazia por baixo de cada
    artigo desalinhava a tabela inteira por causa de um caso que não existe."""
    assert 'data-testid="fat-relatorio-tamanhos-1"' not in ecra["html_produtos"]
    assert 'data-testid="fat-relatorio-tamanhos-0"' in ecra["html_produtos"]


def test_o_eixo_da_curva_escreve_DD_MM_e_nao_a_data_inteira(ecra):
    """O servidor manda `2026-08-01`. Escrito assim no eixo, trinta datas
    atropelavam-se — e a data inteira debaixo de cada ponto não é informação
    nenhuma que o dia e o mês não dêem."""
    assert ">01-08<" in ecra["html_produtos"], "o eixo mostra a data inteira"
    assert ">2026-08-01<" not in ecra["html_produtos"]


def test_as_BARRAS_tambem_tem_grelha_e_valores_no_eixo(ecra):
    """«O por hora, dias da semana e mensal não estão bonitos.» O que faltava
    era isto: eram barras a flutuar sem nada por trás nem escala à esquerda.
    São irmãs da curva — mesma caixa, mesma grelha, mesmo balão."""
    html = ecra["html_hora"]
    assert 'stroke="hsl(var(--border))"' in html, "sem linhas de grelha"
    assert "€" in html, "sem valores no eixo"
    # E os rótulos das horas, todos.
    for hora in ("9h", "14h", "20h"):
        assert ">%s<" % hora in html, hora


def test_as_barras_respondem_ao_dedo(ecra):
    """Uma barra de três píxeis (uma hora fraca) é impossível de apontar — e é
    justamente essa que se quer perguntar «quanto foi?». O alvo é a COLUNA."""
    assert 'data-testid="fat-relatorio-barras-toque-0"' in ecra["html_hora"]
