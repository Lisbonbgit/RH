"""**O ecrã de Clientes** — montado e carregado, não lido.

O que se guarda aqui é o que distingue este ecrã de uma agenda de contactos: a
lista vem das COMPRAS, o nome grava-se por NIF, e as faturas de um cliente são
as mesmas que o ecrã de Documentos mostra — pela mesma rota, com o NIF na
pesquisa. Duas maneiras de listar as faturas de alguém acabam a discordar.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_CLIENTES = {
    "clientes": [
        {"nif": "517542510", "nome": "Fordaimon Foods", "email": None, "telefone": None,
         "notas": None, "faturas": 3, "notas_credito": 1, "total": 128.40,
         "ultima_compra_em": "2026-08-24T18:00:00+00:00"},
        {"nif": "123456789", "nome": None, "email": None, "telefone": None, "notas": None,
         "faturas": 1, "notas_credito": 0, "total": 12.79,
         "ultima_compra_em": "2026-08-20T11:00:00+00:00"},
    ],
    "truncado": False,
}

_FATURAS = {
    "documentos": [
        {"id": "d1", "numero": "FS 01P2026/17", "emitido_em": "2026-08-24T18:00:00+00:00",
         "total": 40.00, "tipo": "FS", "modo": "normal", "loja_id": "loja-1",
         "cliente_nif": "517542510", "artigos": "Açaí", "mais_artigos": 0,
         "pagamentos": [], "tem_venda": True, "atcud": "A-1"},
    ],
    "total": 1, "pagina": 1, "por_pagina": 50,
    "resumo": {"faturas": 1, "notas_credito": 0, "total": 40.00, "truncado": False},
}


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    cenario = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatClientes = carregar(path2.join(ADMIN, 'FatClientes.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/clientes'] = () => ({ data: %s });"
        % json.dumps(_CLIENTES, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos'] = () => ({ data: %s });"
        % json.dumps(_FATURAS, ensure_ascii=False),
        "RESPOSTAS_GESTAO['PUT /faturacao/clientes/517542510'] = () => ({ data:"
        " Object.assign({}, %s, { nome: 'Fordaimon Foods, Lda' }) });"
        % json.dumps(_CLIENTES["clientes"][0], ensure_ascii=False),
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatClientes)); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const naLista = textoVisivel(alvo);",
        'const linha = alvo.querySelector(\'[data-testid="cliente-517542510"]\');',
        "if (!linha) throw new Error('sem linha do cliente: ' + naLista.slice(0, 400));",
        "await act(async () => { linha.click(); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "process.stdout.write(JSON.stringify({",
        "  naLista, aberto: textoVisivel(alvo),",
        "  pedidos: pedidos.map((p) => ({ metodo: p.metodo, url: p.url,",
        "    params: p.params || null })),",
        "}));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp("clientes"), "montar-clientes.js")


def test_a_lista_mostra_o_NIF_o_total_e_quem_ainda_nao_tem_nome(ecra):
    assert "517542510" in ecra["naLista"], ecra["naLista"][:400]
    assert "Fordaimon Foods" in ecra["naLista"], ecra["naLista"][:400]
    assert "€ 128,40" in ecra["naLista"], ecra["naLista"][:400]
    # Um NIF sem ficha não desaparece nem fica em branco: diz que não tem nome.
    assert "Sem nome" in ecra["naLista"], ecra["naLista"][:400]


def test_nao_ha_criar_cliente(ecra):
    """Um cliente nasce de uma COMPRA. Um botão de criar enchia isto de gente
    que nunca cá pôs os pés — e o servidor recusa (404) na mesma."""
    assert "Novo cliente" not in ecra["naLista"], ecra["naLista"][:400]
    assert "Criar cliente" not in ecra["naLista"], ecra["naLista"][:400]


def test_abrir_um_cliente_mostra_a_ficha_e_as_COMPRAS_dele(ecra):
    aberto = ecra["aberto"]
    assert "Compras" in aberto, aberto[:500]
    assert "FS 01P2026/17" in aberto, aberto[:500]
    assert "O NIF não se edita" in aberto, aberto[:500]


def test_as_faturas_vem_da_MESMA_rota_dos_documentos_com_o_NIF(ecra):
    """Uma segunda maneira de listar as faturas de alguém acaba a discordar da
    primeira — e a primeira é o ecrã de Documentos."""
    docs = [p for p in ecra["pedidos"] if p["url"].endswith("/faturacao/documentos")]
    assert docs, ecra["pedidos"]
    assert (docs[0]["params"] or {}).get("q") == "517542510", docs[0]
