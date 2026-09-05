"""**A fatura da app vale o que vale, também nos Relatórios.**

Sem isto, `_artigos_da_fatura` devolve `[]` a um documento sem venda
(relatorios.py:391) — e um `[]` não levanta excepção nenhuma, portanto o evento
é criado na mesma, com a soma de uma lista vazia: zero. O resultado media-se
assim: o cartão «Faturação Hoje» do Dashboard mostrava 6,85 € e as nove vistas
dos Relatórios mostravam 0,00 €, sem nenhum dos dois parecer errado.
"""
import asyncio

from faturacao.relatorios import _artigos_das_linhas_vendus, eventos_dos_documentos

LINHAS = [{"qty": 1, "title": "Açaí Mini",
           "amounts": {"gross_total": "6.85", "net_total": "6.06"},
           "tax": {"id": "INT", "rate": 13}}]

DOC = {"id": "abc", "tipo": "FS", "emitido_em": "2026-09-01T13:43:25+00:00",
       "loja_id": "loja-app", "total_bruto": 6.85, "total_liquido": 6.06,
       "origem": "app", "linhas_vendus": LINHAS, "venda_id": None}


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
    class _Col:
        def find(self, *a, **k):
            return self
        def __getattr__(self, _n):
            return lambda *a, **k: self
        async def to_list(self, _n):
            return []
    class _DB:
        def __getitem__(self, _n):
            return _Col()

    eventos = asyncio.get_event_loop().run_until_complete(
        eventos_dos_documentos(_DB(), [DOC]))
    assert len(eventos) == 1
    assert eventos[0]["bruto_c"] == 685, "era 0 antes desta tarefa"
    assert eventos[0]["quantidade"] == 1
    assert eventos[0]["custo_c"] is None
