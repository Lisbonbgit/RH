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
         "quantidade": 1, "faturas": 1, "rectificacoes": 0},
        {"chave": "p-cola", "rotulo": "Coca-Cola", "bruto": 1.15, "liquido": 0.93,
         "custo": None, "resultado": None, "custo_incompleto": True,
         "quantidade": 1, "faturas": 1, "rectificacoes": 0},
    ],
    "total": {"chave": None, "rotulo": "TOTAL", "bruto": 11.35, "liquido": 9.96,
              "custo": None, "resultado": None, "custo_incompleto": True,
              "quantidade": 2, "faturas": 1, "rectificacoes": 0},
    "serie": [{"rotulo": "2026-08-10", "valor": 11.35}],
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
    "serie": [{"rotulo": "17h", "valor": 57.54}],
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
        "const trocar = alvo.querySelector('[data-testid=\"vista-hora\"]');",
        "if (!trocar) throw new Error('sem selector de vista: ' + produtos.slice(0, 300));",
        "await act(async () => { trocar.click(); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "process.stdout.write(JSON.stringify({",
        "  produtos, hora: textoVisivel(alvo),",
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
