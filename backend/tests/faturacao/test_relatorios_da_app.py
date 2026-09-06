"""**A fatura da app vale o que vale, também nos Relatórios.**

Sem isto, `_artigos_da_fatura` devolve `[]` a um documento sem venda
(relatorios.py:391) — e um `[]` não levanta excepção nenhuma, portanto o evento
é criado na mesma, com a soma de uma lista vazia: zero. O resultado media-se
assim: o cartão «Faturação Hoje» do Dashboard mostrava 6,85 € e as nove vistas
dos Relatórios mostravam 0,00 €, sem nenhum dos dois parecer errado.

A revisão desta repartição encontrou mais quatro coisas, e cada uma tem aqui o
seu teste:

- **a nota de crédito da app somava em vez de subtrair, e em dobro** — o sinal
  é de quem agrega, portanto o valor tem de chegar-lhe POSITIVO;
- **todos os artigos da app caíam numa linha só**, com o nome do primeiro;
- **a guarda que protege os documentos do POS** não tinha nada a prendê-la;
- **uma lista de artigos VAZIA voltava a valer 0,00 € em silêncio** — o mesmo
  defeito que esta repartição existe para matar.
"""
import asyncio

import pytest

from faturacao.db import COLECOES
from faturacao.relatorios import (
    _artigos_das_linhas_vendus, agregar, eventos_dos_documentos,
)

LINHAS = [{"qty": 1, "title": "Açaí Mini",
           "amounts": {"gross_total": "6.85", "net_total": "6.06"},
           "tax": {"id": "INT", "rate": 13}}]

DOC = {"id": "abc", "tipo": "FS", "emitido_em": "2026-09-01T13:43:25+00:00",
       "loja_id": "loja-app", "total_bruto": 6.85, "total_liquido": 6.06,
       "origem": "app", "linhas_vendus": LINHAS, "venda_id": None}


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Coleccao:
    """O mínimo de Mongo que `eventos_dos_documentos` usa: `find(...).to_list(n)`.

    Honra o `{"id": {"$in": [...]}}` de `_por_id` — sem isso, uma venda
    fabricada para um documento aparecia em TODOS eles."""

    def __init__(self, docs):
        self._docs = docs
        self._filtro = {}

    def find(self, filtro=None, _campos=None):
        self._filtro = filtro or {}
        return self

    async def to_list(self, _n):
        ids = (self._filtro.get("id") or {}).get("$in")
        if ids is None:
            return list(self._docs)
        return [d for d in self._docs if d.get("id") in ids]


class _DB:
    """`_DB(vendas=[...], produtos=[...])` — o resto das colecções vem vazio."""

    def __init__(self, **por_coleccao):
        self._por_coleccao = {COLECOES[k]: v for k, v in por_coleccao.items()}

    def __getitem__(self, nome):
        return _Coleccao(self._por_coleccao.get(nome) or [])


def test_o_dinheiro_da_linha_e_o_do_vendus():
    artigos = _artigos_das_linhas_vendus(DOC, {})
    assert len(artigos) == 1
    assert artigos[0]["bruto_c"] == 685
    assert artigos[0]["liquido_c"] == 606, "6,85 a 13% dá 6,06 de base"


def test_o_custo_e_none_e_nunca_zero():
    # Zero dava 100% de margem no relatório de rentabilidade. Não sabemos o
    # custo dos artigos da app: `None` é a verdade e o ecrã escreve "—".
    assert _artigos_das_linhas_vendus(DOC, {})[0]["custo_c"] is None


def test_a_quantidade_vem_da_linha():
    doc = dict(DOC, linhas_vendus=[dict(LINHAS[0], qty=3)])
    assert _artigos_das_linhas_vendus(doc, {})[0]["quantidade"] == 3


def test_o_artigo_fica_sem_definicao_e_nao_desaparece():
    a = _artigos_das_linhas_vendus(DOC, {})[0]
    assert a["produto_id"] is None
    assert a["produto_nome"] == "Açaí Mini"
    assert a["categoria_id"] is None


def test_um_documento_sem_linhas_nao_rebenta():
    assert _artigos_das_linhas_vendus(dict(DOC, linhas_vendus=[]), {}) == []


def test_o_evento_da_app_deixa_de_valer_zero():
    eventos = _corre(eventos_dos_documentos(_DB(), [DOC]))
    assert len(eventos) == 1
    assert eventos[0]["bruto_c"] == 685, "era 0 antes desta tarefa"
    assert eventos[0]["quantidade"] == 1
    assert eventos[0]["custo_c"] is None


# --- C1: a nota de crédito da app SUBTRAI, venha de onde vier o sinal ---------
#
# Quem aplica o sinal é `agregar` (`-1` se o documento é NC). Se as linhas
# chegarem já negativas — e a API do Vendus devolve-as assim, é o que o
# Financeiro documenta em `server.py::_fin_signed_amount`, que lê a MESMA API
# das MESMAS lojas —, o `-1 ×` é uma dupla negação: a devolução SOMA. Medido
# antes da correcção: uma FS de 6,85 € e a NC que a anula davam +13,70 € e
# quantidade 2 nas nove vistas, em vez de zero.

_NC_BASE = {"id": "nc-1", "tipo": "NC", "emitido_em": "2026-09-01T14:10:00+00:00",
            "loja_id": "loja-app", "origem": "app", "venda_id": None,
            "nota_credito_id": None}

_NC_NEGATIVA = [{"qty": -1, "title": "Açaí Mini",
                 "amounts": {"gross_total": "-6.85", "net_total": "-6.06"},
                 "tax": {"id": "INT", "rate": 13}}]
_NC_POSITIVA = [{"qty": 1, "title": "Açaí Mini",
                 "amounts": {"gross_total": "6.85", "net_total": "6.06"},
                 "tax": {"id": "INT", "rate": 13}}]


@pytest.mark.parametrize(
    "linhas_da_nota", [_NC_NEGATIVA, _NC_POSITIVA],
    ids=["a api devolve negativo", "a api devolve positivo"])
def test_a_nota_de_credito_da_app_anula_a_fatura(linhas_da_nota):
    """Os dois sinais têm de dar o MESMO resultado: zero.

    É esta igualdade que impede o relatório de depender de um detalhe da
    resposta da API que ninguém controla."""
    nota = dict(_NC_BASE, linhas_vendus=linhas_da_nota)
    eventos = _corre(eventos_dos_documentos(_DB(), [DOC, nota]))
    assert len(eventos) == 2

    tabela = agregar(eventos, "produto")
    assert tabela["total"]["bruto"] == 0.0, "a devolução subtrai — nunca soma"
    assert tabela["total"]["liquido"] == 0.0
    assert tabela["total"]["quantidade"] == 0
    # E as duas contagens do rodapé continuam a ser DUAS, não uma soma.
    assert tabela["total"]["faturas"] == 1
    assert tabela["total"]["rectificacoes"] == 1


def test_a_linha_negativa_de_uma_FATURA_nao_troca_de_sinal():
    """O `abs()` é SÓ da nota de crédito.

    Numa Fatura Simplificada uma linha negativa é um desconto legítimo, e
    normalizá-la transformava-o em receita — o erro simétrico do que C1
    corrige."""
    desconto = {"qty": 1, "title": "Desconto de campanha",
                "amounts": {"gross_total": "-1.00"},
                "tax": {"id": "INT", "rate": 13}}
    artigos = _artigos_das_linhas_vendus(dict(DOC, linhas_vendus=[desconto]), {})
    assert artigos[0]["bruto_c"] == -100


# --- I2: cada artigo da app é uma linha, com o nome dele ----------------------


def test_os_artigos_da_app_nao_se_fundem_numa_linha_so():
    """Sem `produto_id`, a identidade do artigo é o NOME.

    Com a chave a `None`, `linhas.setdefault` ficava com o rótulo do PRIMEIRO
    artigo e somava-lhe todos os outros: um açaí e duas águas apareciam nos
    Produtos e no cartão «Mais Vendidos» como «Açaí Mini, 3, 9,85 €». O
    dinheiro total estava certo; a atribuição por artigo é que mentia."""
    doc = dict(DOC, linhas_vendus=[
        LINHAS[0],
        {"qty": 2, "title": "Água 50cl",
         "amounts": {"gross_total": "3.00"}, "tax": {"id": "NOR", "rate": 23}},
    ])
    tabela = agregar(_corre(eventos_dos_documentos(_DB(), [doc])), "produto")

    por_nome = {l["rotulo"]: l for l in tabela["linhas"]}
    assert set(por_nome) == {"Açaí Mini", "Água 50cl"}
    assert por_nome["Açaí Mini"]["quantidade"] == 1
    assert por_nome["Açaí Mini"]["bruto"] == 6.85
    assert por_nome["Água 50cl"]["quantidade"] == 2
    assert por_nome["Água 50cl"]["bruto"] == 3.00
    # A soma continua a bater com o documento — separar não pode criar dinheiro.
    assert tabela["total"]["bruto"] == 9.85
    # E o documento conta UMA venda, não uma por artigo.
    assert tabela["total"]["faturas"] == 1


def test_a_categoria_nao_se_separa_por_nome():
    """O contrário da vista de Produtos: sem `categoria_id`, «Sem definição»
    é UMA coisa só. Separá-la pelo nome do artigo inventava categorias que o
    catálogo não tem."""
    doc = dict(DOC, linhas_vendus=[
        LINHAS[0],
        {"qty": 2, "title": "Água 50cl",
         "amounts": {"gross_total": "3.00"}, "tax": {"id": "NOR", "rate": 23}},
    ])
    tabela = agregar(_corre(eventos_dos_documentos(_DB(), [doc])), "categoria")
    assert [l["rotulo"] for l in tabela["linhas"]] == ["Sem definição"]


# --- I3: a guarda que protege os documentos do POS ---------------------------

_VENDA_DO_POS = {
    "id": "v-1", "operador_id": "op-1",
    "linhas": [{"produto_id": "p-acai", "produto_nome": "Açaí Supremo",
                "produto_preco": 10.20, "produto_tax_id": "INT",
                "quantidade": 1}],
}
_PRODUTO = {"id": "p-acai", "nome": "Açaí Supremo",
            "categoria_id": "cat-1", "preco_custo": 4.00}


def test_um_documento_com_venda_reparte_se_pela_VENDA_e_nao_pelo_vendus():
    """A guarda é `venda is None and doc.get("linhas_vendus")`, e o `venda is
    None` é a única coisa que impede a repartição nova de tocar nos documentos
    das cinco lojas.

    O cenário é artificial de propósito — um documento do POS com venda E com
    linhas do Vendus —, porque é ele que prende a guarda: sem o `venda is
    None`, este documento passava a valer 6,85 € sem produto e sem custo, em
    vez dos 10,20 € do açaí que se vendeu mesmo."""
    doc = dict(DOC, id="pos-1", origem="pos", venda_id="v-1")
    eventos = _corre(eventos_dos_documentos(
        _DB(vendas=[_VENDA_DO_POS], produtos=[_PRODUTO]), [doc]))

    assert len(eventos) == 1
    artigo = eventos[0]["artigos"][0]
    assert artigo["produto_id"] == "p-acai", "veio das linhas do Vendus, não da venda"
    assert artigo["produto_nome"] == "Açaí Supremo"
    assert eventos[0]["bruto_c"] == 1020, "6,85 seria o valor da linha do Vendus"
    assert eventos[0]["custo_c"] == 400, "o custo do catálogo perdia-se pelo outro caminho"


# --- I4: zero artigos não é um evento de 0,00 € ------------------------------


def test_um_documento_sem_artigos_nenhuns_fica_por_repartir():
    """`sincronizacao_app` grava `cru.get("items") or []`: um documento da app
    com a lista vazia entra na base na mesma.

    Sem esta guarda ele virava um evento de 0,00 € — o defeito exacto que esta
    repartição existe para matar —, com o valor certo no cartão do Dashboard
    (que lê `total_bruto`) e o contador «documentos por repartir» a ZERO, ou
    seja sem nada no ecrã a dizer que havia dinheiro por atribuir.

    O Dashboard conta `len(docs) - len(eventos)`: ficando de fora, o documento
    entra no aviso «N faturas de hoje não se deixaram repartir por artigo»."""
    vazio = dict(DOC, id="vazio", linhas_vendus=[])
    eventos = _corre(eventos_dos_documentos(_DB(), [DOC, vazio]))

    assert [e["id"] for e in eventos] == ["abc"]
    # É isto que o Dashboard mostra: 2 documentos, 1 evento, 1 por repartir.
    assert len([DOC, vazio]) - len(eventos) == 1
