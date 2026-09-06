"""**Os relatórios, da base de dados até à tabela** — a leitura, não a soma.

A soma está provada em `test_relatorios.py`, sem Mongo nenhum. O que se prova
aqui é o que só se vê com os documentos à frente:

1. o dinheiro de cada linha é o MESMO que a fatura mostra (o líquido de
   `mapa_imposto`, não `qtd × preço`, que numa conta com desconto é outro
   número);
2. uma **nota de crédito** volta a encontrar o ARTIGO que devolveu — pelo
   `indice` da linha na fatura de origem, porque a nota não tem venda própria;
3. o filtro de **categoria** muda o que se SOMA e não só o que se mostra: um
   relatório de Lojas filtrado por "Bebidas" não pode atribuir às bebidas o
   açaí que ia na mesma fatura.
"""
import pytest
from fastapi import HTTPException

from faturacao import relatorios as rel_mod
from faturacao.db import COLECOES
from faturacao.relatorios import relatorio

from .test_venda import ColeccaoFalsa, DbFalsa, _corre


def _linha(id_, produto_id, nome, preco, quantidade=1, tax="INT"):
    return {"id": id_, "produto_id": produto_id, "produto_nome": nome,
            "produto_preco": preco, "produto_tax_id": tax, "quantidade": quantidade,
            "opcoes": [], "respostas_texto": [], "preco_override": None,
            "tax_override": None, "desconto_pct": None, "desconto_eur": None}


_VENDA = {
    "id": "v1", "loja_id": "loja-1", "caixa_id": "c1", "sessao_id": "s1",
    "operador_id": "op-1", "estado": "emitida", "cliente_nif": "517542510",
    "desconto_global_pct": None, "desconto_global_eur": None,
    "linhas": [
        _linha("l1", "p-acai", "Açaí Regular", 10.20),
        _linha("l2", "p-cola", "Coca-Cola", 1.15, tax="NOR"),
    ],
}

_DOC_FS = {
    "id": "d1", "tipo": "FS", "numero": "FS 1/1", "total": 11.35,
    "emitido_em": "2026-08-10T12:00:00+00:00", "loja_id": "loja-1",
    "venda_id": "v1", "cliente_nif": "517542510", "modo": "normal",
}

# A nota credita SÓ a Coca-Cola — a SEGUNDA linha da fatura.
#
# `indice` conta a partir de UM (`nota_credito._linhas_creditaveis`, com
# `enumerate(itens, start=1)`): é o número da linha no talão. Esta fixture
# dizia `1` e chamava-lhe Coca-Cola, o que codificava a convenção ERRADA e
# mantinha verde um defeito a sério — devolver o açaí descontava-o na
# Coca-Cola. Ver `_artigos_da_nota`.
_NOTA = {
    "id": "n1", "loja_id": "loja-1", "documento_id": "d1", "venda_id": "v1",
    "operador": {"id": "op-2", "nome": "Wallison"},
    "linhas": [{"indice": 2, "titulo": "Coca-Cola", "tax_id": "NOR",
                "quantidade": 1, "total": 1.15}],
    "total": 1.15,
}
_DOC_NC = {
    "id": "d2", "tipo": "NC", "numero": "NC 1/1", "total": 1.15,
    "emitido_em": "2026-08-10T13:00:00+00:00", "loja_id": "loja-1",
    "nota_credito_id": "n1", "documento_origem_id": "d1", "modo": "normal",
}

_PRODUTOS = [
    {"id": "p-acai", "nome": "Açaí Regular", "categoria_id": "cat-1", "preco_custo": 4.00},
    {"id": "p-cola", "nome": "Coca-Cola", "categoria_id": "cat-2", "preco_custo": None},
]


def _db(monkeypatch, documentos=None, notas=None):
    registo = []
    db = DbFalsa({
        COLECOES["documentos"]: ColeccaoFalsa(registo, documentos if documentos is not None else [_DOC_FS]),
        COLECOES["vendas"]: ColeccaoFalsa(registo, [dict(_VENDA)]),
        COLECOES["notas_credito"]: ColeccaoFalsa(registo, notas or []),
        COLECOES["produtos"]: ColeccaoFalsa(registo, [dict(p) for p in _PRODUTOS]),
        COLECOES["categorias"]: ColeccaoFalsa(registo, [
            {"id": "cat-1", "nome": "Venda ao Público"}, {"id": "cat-2", "nome": "Bebidas"}]),
        COLECOES["lojas"]: ColeccaoFalsa(registo, [{"id": "loja-1", "nome": "Alfragide"}]),
        COLECOES["utilizadores"]: ColeccaoFalsa(registo, [
            {"id": "op-1", "nome": "Emily"}, {"id": "op-2", "nome": "Wallison"}]),
        COLECOES["clientes"]: ColeccaoFalsa(registo, [
            {"nif": "517542510", "nome": "Fordaimon Foods"}]),
    })
    monkeypatch.setattr(rel_mod, "obter_db", lambda: db)
    return db


def _correr(dimensao, monkeypatch, **filtros):
    return _corre(relatorio(dimensao, de="2026-08-01", ate="2026-08-31", _={}, **filtros))


def test_o_relatorio_de_produtos_le_o_dinheiro_da_FATURA(monkeypatch):
    _db(monkeypatch)
    r = _correr("produto", monkeypatch)
    por_rotulo = {l["rotulo"]: l for l in r["linhas"]}
    assert por_rotulo["Açaí Regular"]["bruto"] == 10.20
    assert por_rotulo["Coca-Cola"]["bruto"] == 1.15
    assert r["total"]["bruto"] == 11.35


def test_o_IVA_sai_do_valor_para_dar_as_vendas_sem_iva(monkeypatch):
    """10,20 € a 13 % são 9,03 € de base; 1,15 € a 23 % são 0,93 €."""
    _db(monkeypatch)
    por_rotulo = {l["rotulo"]: l for l in _correr("produto", monkeypatch)["linhas"]}
    assert por_rotulo["Açaí Regular"]["liquido"] == 9.03
    assert por_rotulo["Coca-Cola"]["liquido"] == 0.93


def test_o_custo_so_existe_onde_o_produto_o_tem(monkeypatch):
    _db(monkeypatch)
    por_rotulo = {l["rotulo"]: l for l in _correr("produto", monkeypatch)["linhas"]}
    assert por_rotulo["Açaí Regular"]["custo"] == 4.00
    assert por_rotulo["Açaí Regular"]["resultado"] == 5.03
    assert por_rotulo["Coca-Cola"]["custo"] is None
    assert por_rotulo["Coca-Cola"]["resultado"] is None


def test_a_nota_de_credito_volta_a_encontrar_o_ARTIGO_que_devolveu(monkeypatch):
    """A nota não tem venda própria: chega ao produto pelo `indice` da linha na
    fatura de origem. Sem isso, uma devolução não se atribuía a artigo nenhum e
    o relatório dizia que se vendeu o que foi devolvido."""
    _db(monkeypatch, documentos=[_DOC_FS, _DOC_NC], notas=[_NOTA])
    por_rotulo = {l["rotulo"]: l for l in _correr("produto", monkeypatch)["linhas"]}
    assert por_rotulo["Açaí Regular"]["bruto"] == 10.20
    assert por_rotulo["Coca-Cola"]["bruto"] == 0.0, "a devolução anulou a venda"
    assert por_rotulo["Coca-Cola"]["rectificacoes"] == 1


def test_a_nota_conta_para_o_UTILIZADOR_que_a_emitiu(monkeypatch):
    """Quem devolve não é quem vendeu — e o relatório de utilizadores tem de o
    dizer, senão a devolução aparecia contra a venda de outra pessoa."""
    _db(monkeypatch, documentos=[_DOC_FS, _DOC_NC], notas=[_NOTA])
    por_rotulo = {l["rotulo"]: l for l in _correr("utilizador", monkeypatch)["linhas"]}
    assert por_rotulo["Emily"]["faturas"] == 1
    assert por_rotulo["Wallison"]["rectificacoes"] == 1


def test_o_filtro_de_CATEGORIA_muda_o_que_se_soma(monkeypatch):
    """Um relatório de Lojas filtrado por "Bebidas" não pode atribuir às
    bebidas o açaí que ia na mesma fatura."""
    _db(monkeypatch)
    r = _correr("loja", monkeypatch, categoria_id="cat-2")
    assert r["total"]["bruto"] == 1.15, r["linhas"]


def test_o_filtro_de_UTILIZADOR_deixa_de_fora_as_vendas_dos_outros(monkeypatch):
    _db(monkeypatch, documentos=[_DOC_FS, _DOC_NC], notas=[_NOTA])
    r = _correr("loja", monkeypatch, utilizador_id="op-2")
    assert r["total"]["faturas"] == 0 and r["total"]["rectificacoes"] == 1


def test_o_cliente_aparece_com_o_NOME_da_ficha(monkeypatch):
    _db(monkeypatch)
    assert _correr("cliente", monkeypatch)["linhas"][0]["rotulo"] == "Fordaimon Foods"


def test_uma_dimensao_desconhecida_da_404(monkeypatch):
    _db(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _correr("cor-do-copo", monkeypatch)
    assert e.value.status_code == 404


def test_as_datas_ao_contrario_dao_422(monkeypatch):
    _db(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _corre(relatorio("dia", de="2026-08-31", ate="2026-08-01", _={}))
    assert e.value.status_code == 422


def test_o_grafico_das_vistas_de_tempo_sao_as_proprias_linhas(monkeypatch):
    _db(monkeypatch)
    r = _correr("hora", monkeypatch)
    assert r["serie"] == [{"rotulo": l["rotulo"], "valor": l["bruto"]} for l in r["linhas"]]


def test_o_grafico_das_outras_vistas_e_a_evolucao_diaria(monkeypatch):
    _db(monkeypatch)
    r = _correr("produto", monkeypatch)
    assert r["serie"] == [{"rotulo": "2026-08-10", "valor": 11.35}]


# --- o índice da linha creditada: conta a partir de UM ------------------------
#
# Encontrado a correr, não a ler: `_artigos_da_nota` fazia `linhas_origem[indice]`
# sobre um índice que `nota_credito._linhas_creditaveis` grava com
# `enumerate(itens, start=1)`. O dinheiro TOTAL do relatório continuava certo —
# é o que fez isto sobreviver — e só a atribuição por artigo é que mentia.

def test_a_nota_desconta_no_artigo_DEVOLVIDO_e_nao_no_seguinte(monkeypatch):
    """Devolve-se o AÇAÍ (a primeira linha da fatura).

    Antes, os 10,20 € do açaí eram descontados na Coca-Cola: o relatório de
    Produtos dizia que a Coca-Cola tinha vendido −9,05 € e que o açaí tinha
    vendido tudo. Duas linhas erradas por uma devolução."""
    nota = dict(_NOTA, id="n-acai", linhas=[
        {"indice": 1, "titulo": "Açaí Regular", "tax_id": "INT",
         "quantidade": 1, "total": 10.20}])
    _db(monkeypatch, documentos=[dict(_DOC_FS), dict(_DOC_NC, nota_credito_id="n-acai")],
        notas=[nota])
    por_rotulo = {l["rotulo"]: l for l in _correr("produto", monkeypatch)["linhas"]}
    assert por_rotulo["Açaí Regular"]["bruto"] == 0.0, "o açaí foi devolvido"
    assert por_rotulo["Coca-Cola"]["bruto"] == 1.15, "a Coca-Cola não foi tocada"


def test_creditar_a_ULTIMA_linha_nao_cria_um_artigo_FANTASMA(monkeypatch):
    """A última linha (índice 2 de 2) caía fora da guarda `0 <= i < len` e o
    artigo saía sem `produto_id` — uma segunda linha com o mesmo nome do
    produto, sem chave, ao lado da verdadeira."""
    _db(monkeypatch, documentos=[dict(_DOC_FS), dict(_DOC_NC)], notas=[dict(_NOTA)])
    linhas = _correr("produto", monkeypatch)["linhas"]
    assert None not in {l["chave"] for l in linhas}, "há uma linha sem produto"
    assert len(linhas) == 2, [l["rotulo"] for l in linhas]
    assert {l["rotulo"]: l["bruto"] for l in linhas} == {
        "Açaí Regular": 10.20, "Coca-Cola": 0.0}


# --- os TAMANHOS na vista de Produtos ----------------------------------------

def _venda_com_tamanho(tamanho, quantidade=1):
    return dict(_VENDA, linhas=[dict(
        _linha("l1", "p-acai", "Açaí Regular", 10.20, quantidade=quantidade),
        opcoes=[{"id": "o-" + tamanho.lower(), "grupo_id": "g-tam", "nome": tamanho,
                 "preco": 0, "nome_grupo": "Tamanho", "sai_na_fatura": True}],
    )])


def test_o_relatorio_de_PRODUTOS_reparte_o_acai_pelos_tamanhos(monkeypatch):
    """«Não esqueça do açaí que tem as personalizações de tamanhos.» A linha
    dizia «Açaí 3» — três de qual?"""
    db = _db(monkeypatch)
    db._coleccoes[COLECOES["vendas"]] = ColeccaoFalsa(
        [], [_venda_com_tamanho("Supreme", quantidade=3)])
    linha = next(l for l in _correr("produto", monkeypatch)["linhas"]
                 if l["rotulo"] == "Açaí Regular")
    assert linha["tamanhos"] == [{"nome": "Supreme", "quantidade": 3}]


def test_as_OUTRAS_vistas_nao_ganham_tamanhos(monkeypatch):
    """Repartir uma loja por tamanhos misturava o açaí com tudo o resto que
    essa loja vendeu. Um tamanho reparte um ARTIGO."""
    _db(monkeypatch)
    for dimensao in ("loja", "cliente", "categoria", "utilizador", "dia"):
        linhas = _correr(dimensao, monkeypatch)["linhas"]
        assert all("tamanhos" not in l for l in linhas), dimensao


def test_um_produto_SEM_tamanho_traz_a_lista_vazia_e_nao_falta_a_chave(monkeypatch):
    """O ecrã lê `linha.tamanhos` em todas as linhas da vista de Produtos. Uma
    chave em falta numas e presente noutras é a diferença entre não desenhar
    nada e rebentar."""
    _db(monkeypatch)
    linhas = _correr("produto", monkeypatch)["linhas"]
    assert linhas and all(l["tamanhos"] == [] for l in linhas)


def test_uma_fatura_ANULADA_nao_conta_no_relatorio(monkeypatch):
    """A mesma regra do Dashboard, que a soma dos nove relatórios não tinha.

    Desde que a sincronização da app passou a marcar `anulado: True` numa FS
    anulada no Vendus (`sincronizacao_rota._marcar_anulado`), o campo existe
    mesmo em `fat_documentos`. O Dashboard e o email da noite já lhe davam
    0,00 € (`dashboard._valor_documento`); este ecrã continuava a somá-la, e o
    dono ficava com dois números diferentes para o mesmo dia.
    """
    anulada = dict(_DOC_FS, id="d9", numero="FS 1/9", anulado=True)
    _db(monkeypatch, documentos=[_DOC_FS, anulada])
    r = _correr("produto", monkeypatch)
    assert r["total"]["bruto"] == 11.35, "só a fatura sã, e não as duas"
