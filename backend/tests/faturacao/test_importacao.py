"""Importação do catálogo Vendus (Task 21) — sem rede, sem Mongo: duplo do
ClienteVendus (uma lista Python — a paginação em si já está testada em
test_vendus_cliente.py) e um duplo de colecção COM ESTADO (ColeccaoMemoria).

Porquê um duplo COM estado, ao contrário do ColeccaoFalsa "enlatado" que o
resto do módulo usa (test_catalogo.py, test_lojas.py, ...): a idempotência
só se prova a sério correndo a importação DUAS VEZES sobre a MESMA base —
um duplo que só devolve respostas fixas não distingue "não duplicou" de
"nunca gravou nada".
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import importacao as importacao_mod
from faturacao.db import COLECOES
from faturacao.importacao import (
    _extrair_preco,
    _extrair_tax_id,
    _sincronizar_categorias,
    _sincronizar_produtos,
    importar_vendus,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados COM ESTADO ---------------------------------------


class ResultadoUpdate:
    def __init__(self, matched_count):
        self.matched_count = matched_count


class CursorMemoria:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, campo, direcao=1):
        self._docs = sorted(self._docs, key=lambda d: d.get(campo, ""), reverse=(direcao == -1))
        return self

    async def to_list(self, limite):
        return list(self._docs)[:limite]


class ColeccaoMemoria:
    """Duplo de colecção Mongo com estado real: insert_one fica visível a um
    find_one/find seguinte — ao contrário do ColeccaoFalsa "enlatado" do
    resto do módulo."""

    def __init__(self, documentos=None):
        self.documentos = [dict(d) for d in (documentos or [])]

    def _filtrar(self, filtro):
        filtro = filtro or {}
        return [d for d in self.documentos if all(d.get(k) == v for k, v in filtro.items())]

    def find(self, filtro=None, projecao=None):
        return CursorMemoria(self._filtrar(filtro))

    async def find_one(self, filtro, projecao=None):
        achados = self._filtrar(filtro)
        return dict(achados[0]) if achados else None

    async def insert_one(self, doc):
        self.documentos.append(dict(doc))
        return None

    async def update_one(self, filtro, atualizacao):
        achados = self._filtrar(filtro)
        if not achados:
            return ResultadoUpdate(0)
        achados[0].update(atualizacao.get("$set", {}))
        return ResultadoUpdate(1)


class DbMemoria:
    def __init__(self):
        self.colecoes = {
            COLECOES["categorias"]: ColeccaoMemoria(),
            COLECOES["produtos"]: ColeccaoMemoria(),
        }

    def __getitem__(self, nome):
        return self.colecoes[nome]

    @property
    def categorias(self):
        return self.colecoes[COLECOES["categorias"]]

    @property
    def produtos(self):
        return self.colecoes[COLECOES["produtos"]]


# --- Extracção de preço/IVA de um produto Vendus -----------------------------


def test_extrai_preco_de_gross_price():
    assert _extrair_preco({"gross_price": "8.99"}) == 8.99


def test_extrai_preco_cai_para_price_se_sem_gross_price():
    assert _extrair_preco({"price": 8.5}) == 8.5


def test_extrai_preco_ausente_devolve_none():
    assert _extrair_preco({}) is None


def test_extrai_tax_id_direto():
    assert _extrair_tax_id({"tax_id": "NOR"}) == "NOR"


def test_extrai_tax_id_de_taxa_aninhada():
    assert _extrair_tax_id({"tax": {"rate": 13}}) == "INT"


def test_extrai_tax_id_desconhecido_devolve_none_nunca_inventa():
    """A regra que não se negoceia (Task 20, precos.py): sem IVA
    reconhecível, None — nunca um valor por omissão."""
    assert _extrair_tax_id({}) is None
    assert _extrair_tax_id({"tax_id": "XPTO"}) is None


# --- Categorias: idempotência -------------------------------------------------


def test_sincroniza_categorias_cria_as_que_faltam():
    db = DbMemoria()
    categorias_vendus = [{"id": "1", "title": "Venda ao Público"}]

    mapa, problemas = _corre(_sincronizar_categorias(db, categorias_vendus))

    assert problemas == []
    assert len(db.categorias.documentos) == 1
    doc = db.categorias.documentos[0]
    assert doc["nome"] == "Venda ao Público"
    assert mapa == {"1": doc["id"]}


def test_sincroniza_categorias_duas_vezes_nao_duplica_e_preserva_ordem_ativa():
    db = DbMemoria()
    categorias_vendus = [{"id": "1", "title": "Venda ao Público"}]
    _corre(_sincronizar_categorias(db, categorias_vendus))

    # O dono reordena/desliga a categoria à mão no backoffice, ENTRE as duas
    # importações — a Task 19 não dá a estes campos equivalente no Vendus.
    db.categorias.documentos[0]["ordem"] = 9
    db.categorias.documentos[0]["ativa"] = False

    mapa2, problemas2 = _corre(_sincronizar_categorias(db, categorias_vendus))

    assert len(db.categorias.documentos) == 1  # não duplicou
    doc = db.categorias.documentos[0]
    assert doc["ordem"] == 9 and doc["ativa"] is False  # preservado, não pisado
    assert mapa2 == {"1": doc["id"]}
    assert problemas2 == []


def test_sincroniza_categorias_sem_id_ou_nome_e_ignorada_com_problema():
    db = DbMemoria()
    resultado = _corre(_sincronizar_categorias(db, [{"title": "Sem id"}, {"id": "2"}]))
    mapa, problemas = resultado
    assert mapa == {}
    assert len(problemas) == 2
    assert db.categorias.documentos == []


# --- Produtos: criação, actualização e idempotência ---------------------------


def test_sincroniza_produtos_cria_produto_novo():
    db = DbMemoria()
    mapa_categorias = {"10": "cat-local-1"}
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "gross_price": 8.99, "tax_id": "NOR",
         "category_id": "10"}
    ]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, mapa_categorias))

    assert resultado["lidos"] == 1
    assert resultado["criados"] == 1
    assert resultado["atualizados"] == 0
    assert resultado["problemas"] == []
    doc = db.produtos.documentos[0]
    assert doc["vendus_ref"] == "500"
    assert doc["nome"] == "Açaí Regular"
    assert doc["preco"] == 8.99
    assert doc["tax_id"] == "NOR"
    assert doc["categoria_id"] == "cat-local-1"
    assert doc["ativo"] is True
    assert doc["grupos_personalizacao"] == []


def test_sincroniza_produtos_duas_vezes_nao_duplica():
    db = DbMemoria()
    mapa_categorias = {"10": "cat-local-1"}
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "gross_price": 8.99, "tax_id": "NOR",
         "category_id": "10"}
    ]
    _corre(_sincronizar_produtos(db, produtos_vendus, mapa_categorias))

    resultado2 = _corre(_sincronizar_produtos(db, produtos_vendus, mapa_categorias))

    assert len(db.produtos.documentos) == 1  # não duplicou
    assert resultado2["criados"] == 0
    assert resultado2["atualizados"] == 1


def test_reimportar_atualiza_nome_preco_iva_mas_preserva_foto_grupos_e_ativo():
    """A decisão de idempotência da Task 21: o Vendus é a fonte de verdade
    para nome/preço/IVA/categoria (o que o dono pode ter mudado LÁ);
    foto_url, grupos_personalizacao e ativo são configuração feita só no
    nosso backoffice — nunca vieram do Vendus — e uma reimportação não os
    pode apagar nem reactivar/desligar à revelia."""
    db = DbMemoria()
    mapa_categorias = {"10": "cat-local-1"}
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "gross_price": 8.99, "tax_id": "NOR",
         "category_id": "10"}
    ]
    _corre(_sincronizar_produtos(db, produtos_vendus, mapa_categorias))

    # Configuração feita SÓ no nosso backoffice, que o Vendus não conhece:
    doc = db.produtos.documentos[0]
    doc["foto_url"] = "https://cdn.exemplo/acai.jpg"
    doc["grupos_personalizacao"] = ["grupo-toppings"]
    doc["ativo"] = False

    # O dono muda o nome e o preço NO VENDUS:
    produtos_vendus_v2 = [
        {"id": "500", "title": "Açaí Regular Grande", "gross_price": 9.99, "tax_id": "NOR",
         "category_id": "10"}
    ]
    resultado = _corre(_sincronizar_produtos(db, produtos_vendus_v2, mapa_categorias))

    assert resultado["criados"] == 0 and resultado["atualizados"] == 1
    doc = db.produtos.documentos[0]
    assert doc["nome"] == "Açaí Regular Grande"  # actualizado (vem do Vendus)
    assert doc["preco"] == 9.99  # actualizado (vem do Vendus)
    assert doc["foto_url"] == "https://cdn.exemplo/acai.jpg"  # preservado
    assert doc["grupos_personalizacao"] == ["grupo-toppings"]  # preservado
    assert doc["ativo"] is False  # preservado


def test_sincroniza_produtos_sem_iva_reconhecido_e_ignorado_com_problema():
    db = DbMemoria()
    produtos_vendus = [{"id": "500", "title": "Misterioso", "gross_price": 5, "category_id": "10"}]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert resultado["criados"] == 0
    assert db.produtos.documentos == []
    assert any("IVA" in p for p in resultado["problemas"])


def test_sincroniza_produtos_categoria_desconhecida_e_ignorado_com_problema():
    db = DbMemoria()
    produtos_vendus = [
        {"id": "500", "title": "Órfão", "gross_price": 5, "tax_id": "NOR", "category_id": "999"}
    ]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert resultado["criados"] == 0
    assert db.produtos.documentos == []
    assert any("categoria" in p.lower() for p in resultado["problemas"])


def test_sincroniza_produtos_sem_preco_e_ignorado_com_problema():
    db = DbMemoria()
    produtos_vendus = [{"id": "500", "title": "Sem preço", "tax_id": "NOR", "category_id": "10"}]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert resultado["criados"] == 0
    assert any("preço" in p.lower() for p in resultado["problemas"])


def test_sincroniza_produtos_sem_id_vendus_e_ignorado():
    db = DbMemoria()
    produtos_vendus = [{"title": "Sem id", "gross_price": 5, "tax_id": "NOR", "category_id": "10"}]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert resultado["criados"] == 0
    assert db.produtos.documentos == []


# --- Endpoint: sem chave configurada -------------------------------------


def test_importar_sem_vendus_accounts_devolve_400_com_mensagem_clara(monkeypatch):
    monkeypatch.delenv("VENDUS_ACCOUNTS", raising=False)
    monkeypatch.delenv("FAT_NIF", raising=False)

    with pytest.raises(HTTPException) as excinfo:
        _corre(importar_vendus(_={}))

    assert excinfo.value.status_code == 400
    assert "VENDUS_ACCOUNTS" in excinfo.value.detail


def test_importar_com_nif_sem_conta_configurada_devolve_400(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"k","company_nif":"111111111"}]')
    monkeypatch.setenv("FAT_NIF", "517542510")

    with pytest.raises(HTTPException) as excinfo:
        _corre(importar_vendus(_={}))

    assert excinfo.value.status_code == 400
    assert "517542510" in excinfo.value.detail


# --- Endpoint: fluxo completo com duplo do ClienteVendus -----------------


class ClienteFalso:
    """Duplo do ClienteVendus — a paginação em si já está testada em
    test_vendus_cliente.py; aqui só importa que o endpoint pede as duas
    listas e as encaminha por inteiro para a sincronização."""

    instancias = []

    def __init__(self, chave):
        self.chave = chave
        ClienteFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def listar_categorias(self):
        return [{"id": "1", "title": "Venda ao Público"}]

    def listar_produtos(self):
        # 237 produtos — o mesmo número da "armadilha das 3 páginas" em
        # test_vendus_cliente.py — para o relatório do endpoint provar que o
        # número que chega ao dono bate com o que foi mesmo lido, não fica
        # preso nos 100 da primeira página.
        return [
            {"id": str(i), "title": "Produto %d" % i, "gross_price": 1.0, "tax_id": "NOR",
             "category_id": "1"}
            for i in range(1, 238)
        ]


def test_importar_vendus_fluxo_completo_e_idempotente(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"chave-teste","company_nif":"517542510"}]')
    monkeypatch.setenv("FAT_NIF", "517542510")
    db = DbMemoria()
    monkeypatch.setattr(importacao_mod, "obter_db", lambda: db)
    monkeypatch.setattr(importacao_mod, "ClienteVendus", ClienteFalso)
    ClienteFalso.instancias.clear()

    resultado = _corre(importar_vendus(_={}))

    assert ClienteFalso.instancias[0].chave == "chave-teste"
    assert resultado["categorias_lidas"] == 1
    assert resultado["produtos_lidos"] == 237  # não ficou preso na 1ª página
    assert resultado["produtos_criados"] == 237
    assert resultado["problemas"] == []

    # Corre outra vez: idempotente de ponta a ponta.
    resultado2 = _corre(importar_vendus(_={}))
    assert resultado2["produtos_criados"] == 0
    assert resultado2["produtos_atualizados"] == 237
    assert len(db.produtos.documentos) == 237  # continuam 237, não 474
