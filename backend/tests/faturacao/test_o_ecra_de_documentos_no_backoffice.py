"""**O ecrã de Documentos do backoffice** — montado e carregado, não lido.

Os ecrãs deste módulo desenham-se sem servidor nenhum e já foram dois defeitos
a produção assim: o `lib/pos.js` com o `baseURL` errado (sete chamadas a dar
404) e o PIN que entrava como outra pessoa. Por isso este ficheiro monta o
`FatDocumentos` a sério, com o servidor fabricado à frente do axios, CARREGA
nos filtros e afirma o pedido que sai e o que fica na tabela.

O que se guarda aqui é o que só se vê a correr:

1. os filtros "Todas as lojas"/"Todos" NÃO viajam — mandá-los como texto punha
   o servidor a procurar uma loja com o id "todas" e a lista vinha vazia;
2. a nota de crédito lê-se com um sinal MENOS na coluna do total, senão a
   soma da coluna à mão nunca bate com o resumo;
3. abrir uma linha vai buscar a fatura ao servidor e mostra-a.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_LOJAS = [{"id": "loja-1", "nome": "L'Açaí Alfragide"},
          {"id": "loja-2", "nome": "L'Açaí Belém"}]

_LISTA = {
    "documentos": [
        {"id": "d1", "numero": "FS 01P2026/17", "emitido_em": "2026-08-10T12:00:00+00:00",
         "total": 10.20, "tipo": "FS", "modo": "normal", "loja_id": "loja-1",
         "cliente_nif": None, "artigos": "Açaí Regular", "mais_artigos": 0,
         "pagamentos": [], "tem_venda": True, "atcud": "A-1"},
        {"id": "d2", "numero": "NC 01P2026/3", "emitido_em": "2026-08-10T13:00:00+00:00",
         "total": 1.15, "tipo": "NC", "modo": "normal", "loja_id": "loja-2",
         "cliente_nif": "517542510", "artigos": "Coca-Cola", "mais_artigos": 0,
         "pagamentos": [], "tem_venda": True, "atcud": "A-2"},
    ],
    "total": 2, "pagina": 1, "por_pagina": 50,
    "resumo": {"faturas": 1, "notas_credito": 1, "total": 9.05, "truncado": False},
}

_FATURA = {
    "id": "d1", "numero": "FS 01P2026/17", "atcud": "A-1", "tipo": "FS",
    "modo": "normal", "emitido_em": "2026-08-10T12:00:00+00:00",
    "cliente_nif": None, "tem_venda": True, "venda_id": "v1",
    "linhas": [{"titulo": "Açaí Regular (Nutella)", "quantidade": 1,
                "preco_unitario": 10.20, "desconto": 0.0, "total": 10.20}],
    "pagamentos": [{"nome": "Dinheiro", "valor": 10.20}],
    "mapa_imposto": [{"tax_id": "INT", "taxa": 13, "base": 9.03, "iva": 1.17, "total": 10.20}],
    "totais_imposto": {"base": 9.03, "iva": 1.17, "total": 10.20},
    "total": 10.20, "total_das_linhas": 10.20, "total_divergente": False,
    "tem_talao": True,
}


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    cenario = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatDocumentos = carregar(path2.join(ADMIN, 'FatDocumentos.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: %s });"
        % json.dumps(_LOJAS, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos'] = () => ({ data: %s });"
        % json.dumps(_LISTA, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos/d1'] = () => ({ data: %s });"
        % json.dumps(_FATURA, ensure_ascii=False),
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatDocumentos)); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const naLista = textoVisivel(alvo);",
        # Abrir a fatura: a linha da tabela é clicável.
        # Pela etiqueta e não pela tag: os componentes da casa (Table/TableRow)
        # entram substituídos por `div`s no duplo, e um `querySelectorAll('tr')`
        # não encontra nada.
        "const linha = alvo.querySelector('[data-testid=\"documento-d1\"]');",
        "if (!linha) throw new Error('sem linha da fatura: ' + naLista.slice(0, 400));",
        "await act(async () => { linha.click(); });",
        "await act(async () => {});",
        "process.stdout.write(JSON.stringify({",
        "  naLista, aberta: textoVisivel(alvo),",
        "  pedidos: pedidos.map((p) => ({ url: p.url, params: p.params || null })),",
        "}));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp("documentos"), "montar-documentos.js")


def test_a_lista_mostra_as_faturas_com_a_loja_e_o_cliente(ecra):
    assert "FS 01P2026/17" in ecra["naLista"], ecra["naLista"][:400]
    assert "L'Açaí Alfragide" in ecra["naLista"], ecra["naLista"][:400]
    assert "Consumidor Final" in ecra["naLista"], ecra["naLista"][:400]
    assert "517542510" in ecra["naLista"], ecra["naLista"][:400]


def test_os_filtros_vazios_NAO_viajam(ecra):
    """"Todas as lojas" e "Todos" são a AUSÊNCIA de filtro, não um valor. A
    mandá-los como texto, o servidor procurava uma loja com o id "todas" e a
    lista vinha sempre vazia — e o ecrã não tinha como o dizer."""
    lista = [p for p in ecra["pedidos"] if p["url"].endswith("/faturacao/documentos")]
    assert lista, ecra["pedidos"]
    params = lista[0]["params"] or {}
    assert params.get("loja_id") is None, params
    assert params.get("tipo") is None, params
    assert params.get("de") and params.get("ate"), (
        "o intervalo de datas TEM de viajar — sem ele o ecrã abria com tudo "
        "desde sempre: %s" % params
    )


def test_a_nota_de_credito_le_se_com_sinal_menos(ecra):
    """O resumo já traz a NC subtraída. Se a coluna a mostrasse positiva,
    quem somasse a coluna à mão nunca chegava ao total do resumo — e a
    primeira coisa que faz quem confere um relatório é somar a coluna."""
    assert "− € 1,15" in ecra["naLista"], ecra["naLista"][:400]
    assert "€ 9,05" in ecra["naLista"], ecra["naLista"][:400]


def test_abrir_uma_fatura_vai_busca_la_ao_servidor_e_mostra_a(ecra):
    assert any(p["url"].endswith("/faturacao/documentos/d1") for p in ecra["pedidos"]), \
        ecra["pedidos"]
    assert "Açaí Regular (Nutella)" in ecra["aberta"], ecra["aberta"][:400]
    # "IVA 13 %" com espaço: o `textoVisivel` junta os nós de texto com um
    # espaço, e o `%` é um nó à parte do `{linha.taxa}`.
    assert "IVA 13" in ecra["aberta"], ecra["aberta"][:400]
    assert "base € 9,03" in ecra["aberta"], ecra["aberta"][:400]
