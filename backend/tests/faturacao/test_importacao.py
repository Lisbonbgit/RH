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
from copy import deepcopy

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


def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find`/`find_one` reais descodificam BSON de fresco a cada chamada: o
    resultado NUNCA está ligado ao que está no Mongo. Um duplo que devolvesse
    o próprio objecto guardado deixa um teste passar por ALIASING — o código
    de produção muta o que "leu", o Mongo falso muda sozinho, e a asserção
    fica verde sem que nenhuma escrita tenha acontecido. Já apanhou um caso
    real neste módulo (`cancelar_venda`, em faturacao/venda.py).

    Aqui isto pesa mais do que noutros ficheiros: `_sincronizar_categorias`
    lê as categorias existentes uma única vez (`find`) e guarda-as em
    `por_ref`/`por_nome` durante a importação inteira, escrevendo-lhes
    `vendus_ref` à mão depois do `update_one`. Com aliasing, esse `update_one`
    podia desaparecer sem nenhum teste se queixar — a atribuição em memória
    fazia o trabalho dele.

    Cópia FUNDA, não `dict(d)`: os produtos trazem `grupos_personalizacao`,
    que a reimportação tem de PRESERVAR — é o campo cuja preservação estes
    testes existem para provar, e uma cópia rasa deixava-o partilhado com o
    documento guardado.
    """
    return deepcopy(documento)


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
        return CursorMemoria([_como_o_motor(d) for d in self._filtrar(filtro)])

    async def find_one(self, filtro, projecao=None):
        achados = self._filtrar(filtro)
        return _como_o_motor(achados[0]) if achados else None

    async def insert_one(self, doc):
        self.documentos.append(deepcopy(doc))
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


def test_extrai_preco_nao_cai_para_price_liquido_sem_gross_price():
    """`price` no Vendus é o preço LÍQUIDO (sem IVA) — não é `gross_price`
    com outro nome. Um açaí a €8,99 (IVA 13%) tem `price` perto de 7,96;
    gravá-lo como preço de venda faturaria sem o IVA embutido, em silêncio.
    Sem `gross_price`, o produto fica por resolver (None) — nunca com o
    líquido a fingir de preço final."""
    assert _extrair_preco({"price": 8.5}) is None


def test_extrai_preco_ausente_devolve_none():
    assert _extrair_preco({}) is None


def test_extrai_preco_gross_price_com_mais_de_2_casas_devolve_none():
    """Antes, `round(bruto, 2)` fazia o valor 'parecer limpo' e o crivo das 2
    casas decimais do resto do módulo nunca chegava a disparar neste
    caminho. Agora usa o mesmo crivo (precos._tem_mais_de_2_casas_decimais):
    um preço com mais de 2 casas fica por resolver, não é arredondado às
    escondidas."""
    assert _extrair_preco({"gross_price": 8.995}) is None


def test_extrai_preco_gross_price_invalido_devolve_none():
    assert _extrair_preco({"gross_price": "não é um número"}) is None


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


def test_sincroniza_categorias_cria_categoria_nova_com_vendus_ref():
    db = DbMemoria()
    mapa, problemas = _corre(_sincronizar_categorias(db, [{"id": "7", "title": "Vendas Aplicações"}]))
    assert problemas == []
    doc = db.categorias.documentos[0]
    assert doc["vendus_ref"] == "7"
    assert mapa == {"7": doc["id"]}


def test_sincroniza_categorias_liga_vendus_ref_a_categoria_existente_por_nome_na_primeira_vez():
    """Uma categoria criada no backoffice antes desta ligação existir (sem
    vendus_ref) não pode ser duplicada — o nome serve de reserva só nesta
    primeira ligação (ver docstring do módulo)."""
    db = DbMemoria()
    db.categorias.documentos.append(
        {"id": "cat-antiga-1", "nome": "Venda ao Público", "ordem": 0, "ativa": True,
         "vendus_ref": None}
    )

    mapa, problemas = _corre(_sincronizar_categorias(db, [{"id": "1", "title": "Venda ao Público"}]))

    assert problemas == []
    assert len(db.categorias.documentos) == 1  # não duplicou
    doc = db.categorias.documentos[0]
    assert doc["id"] == "cat-antiga-1"
    assert doc["vendus_ref"] == "1"  # ligado
    assert mapa == {"1": "cat-antiga-1"}


def test_renomear_categoria_no_backoffice_nao_causa_duplicado_na_reimportacao():
    """IMPORTANT: antes, casar por nome fazia uma categoria renomeada no
    backoffice ser 'perdida' na reimportação seguinte — o Vendus recriava-a
    com o nome de lá, arrastava-lhe os produtos todos e deixava a antiga
    vazia, com a ordem que o dono tinha arrumado perdida. Guardar
    vendus_ref e casar por ele resolve: o nome muda-se aqui, o vendus_ref
    no Vendus não muda, a categoria continua a ser a mesma."""
    db = DbMemoria()
    categorias_vendus = [{"id": "1", "title": "Venda ao Público"}]
    _corre(_sincronizar_categorias(db, categorias_vendus))
    categoria_id = db.categorias.documentos[0]["id"]

    # O dono renomeia a categoria e reordena-a no backoffice:
    db.categorias.documentos[0]["nome"] = "Loja Física"
    db.categorias.documentos[0]["ordem"] = 5

    mapa2, problemas2 = _corre(_sincronizar_categorias(db, categorias_vendus))

    assert len(db.categorias.documentos) == 1  # não duplicou
    doc = db.categorias.documentos[0]
    assert doc["id"] == categoria_id
    assert doc["nome"] == "Loja Física"  # preservado, não pisado pelo Vendus
    assert doc["ordem"] == 5
    assert mapa2 == {"1": categoria_id}
    assert problemas2 == []


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


def test_reimportar_preserva_a_SUBCATEGORIA_que_alguem_escolheu():
    """**A arrumação da grelha do POS é nossa e o Vendus não a conhece.** A
    reimportação grava o produto INTEIRO por cima; sem estar na lista do que
    sobrevive, a subcategoria desaparecia na importação seguinte — e o dono só
    dava por isso ao ver a grelha desarrumada, sem nada que ligasse uma coisa
    à outra."""
    db = DbMemoria()
    mapa_categorias = {"10": "cat-local-1"}
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "gross_price": 8.99, "tax_id": "NOR",
         "category_id": "10"}
    ]
    _corre(_sincronizar_produtos(db, produtos_vendus, mapa_categorias))

    db.produtos.documentos[0]["subcategoria_id"] = "sub-acais"

    resultado = _corre(_sincronizar_produtos(db, [
        {"id": "500", "title": "Açaí Regular", "gross_price": 9.49, "tax_id": "NOR",
         "category_id": "10"}
    ], mapa_categorias))

    assert resultado["atualizados"] == 1
    assert db.produtos.documentos[0]["subcategoria_id"] == "sub-acais"
    assert db.produtos.documentos[0]["preco"] == 9.49


def test_um_produto_que_MUDA_DE_CATEGORIA_no_vendus_perde_a_subcategoria():
    """Uma subcategoria pertence a uma categoria só. Com o produto a mudar de
    categoria no Vendus, ela deixa de lhe pertencer — e um produto com a
    subcategoria de outra categoria não cabe em separador nenhum da grelha:
    desaparecia do ecrã com o artigo à venda na loja. Limpa-se, e a importação
    diz qual foi."""
    db = DbMemoria()
    _corre(_sincronizar_produtos(db, [
        {"id": "500", "title": "Coca-Cola", "gross_price": 1.15, "tax_id": "NOR",
         "category_id": "10"}
    ], {"10": "cat-local-1", "20": "cat-local-2"}))
    db.produtos.documentos[0]["subcategoria_id"] = "sub-bebidas"

    resultado = _corre(_sincronizar_produtos(db, [
        {"id": "500", "title": "Coca-Cola", "gross_price": 1.15, "tax_id": "NOR",
         "category_id": "20"}
    ], {"10": "cat-local-1", "20": "cat-local-2"}))

    doc = db.produtos.documentos[0]
    assert doc["categoria_id"] == "cat-local-2"
    assert doc["subcategoria_id"] is None
    assert any("sem subcategoria" in p for p in resultado["problemas"]), \
        resultado["problemas"]


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


def test_sincroniza_produtos_so_com_price_liquido_vai_para_problemas_nao_e_criado():
    """CRITICAL: `price` é o preço LÍQUIDO no Vendus, `gross_price` é o preço
    COM IVA — não são o mesmo número com nomes diferentes. Um produto que só
    tenha `price` (sem `gross_price`) tem de ficar por resolver em
    `problemas`, nunca criado com o líquido a fazer de preço de venda."""
    db = DbMemoria()
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "price": 7.9558, "tax_id": "NOR",
         "category_id": "10"}
    ]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert resultado["criados"] == 0
    assert db.produtos.documentos == []
    assert any("preço" in p.lower() for p in resultado["problemas"])


def test_sincroniza_produtos_sem_vendus_ref_liga_por_nome_e_categoria_em_vez_de_duplicar():
    """Um produto criado à mão no backoffice (vendus_ref=None) com o mesmo
    nome e categoria de um produto do Vendus não pode ser duplicado — o
    ecrã vazio convida precisamente a isso ('Importe do Vendus ou crie o
    primeiro produto'). Em vez de criar um segundo, liga-se o vendus_ref ao
    que já lá está, preservando a foto e os grupos de personalização que o
    dono já tinha atribuído."""
    db = DbMemoria()
    db.produtos.documentos.append({
        "id": "prod-mao-1",
        "nome": "Açaí Regular",
        "categoria_id": "cat-local-1",
        "preco": 8.99,
        "tax_id": "NOR",
        "foto_url": "https://cdn.exemplo/acai.jpg",
        "grupos_personalizacao": ["grupo-toppings"],
        "ativo": True,
        "vendus_ref": None,
    })
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "gross_price": 8.99, "tax_id": "NOR",
         "category_id": "10"}
    ]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert len(db.produtos.documentos) == 1  # não duplicou
    assert resultado["criados"] == 0
    assert resultado["ligados"] == 1
    doc = db.produtos.documentos[0]
    assert doc["id"] == "prod-mao-1"
    assert doc["vendus_ref"] == "500"  # ligado
    assert doc["foto_url"] == "https://cdn.exemplo/acai.jpg"  # preservado
    assert doc["grupos_personalizacao"] == ["grupo-toppings"]  # preservado


def test_sincroniza_produtos_liga_por_nome_so_dentro_da_mesma_categoria():
    """O nome sozinho não basta — duas categorias podem legitimamente ter um
    produto com o mesmo nome (spec: 'Açaí Regular' na Venda ao Público E nas
    Vendas Aplicações). Sem bater a categoria também, cria-se um novo em vez
    de roubar o de outra categoria."""
    db = DbMemoria()
    db.produtos.documentos.append({
        "id": "prod-mao-2",
        "nome": "Açaí Regular",
        "categoria_id": "cat-outra-categoria",
        "preco": 8.99,
        "tax_id": "NOR",
        "foto_url": None,
        "grupos_personalizacao": [],
        "ativo": True,
        "vendus_ref": None,
    })
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "gross_price": 8.99, "tax_id": "NOR",
         "category_id": "10"}
    ]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert resultado["criados"] == 1
    assert resultado["ligados"] == 0
    assert len(db.produtos.documentos) == 2  # não ligou ao de outra categoria


def test_sincroniza_produtos_nao_rouba_produto_ja_ligado_a_outro_vendus_ref():
    """Um produto já ligado a outro vendus_ref (importação anterior) não é
    candidato à ligação por nome — só produtos sem vendus_ref (criados à
    mão) o são."""
    db = DbMemoria()
    db.produtos.documentos.append({
        "id": "prod-ja-ligado",
        "nome": "Açaí Regular",
        "categoria_id": "cat-local-1",
        "preco": 8.99,
        "tax_id": "NOR",
        "foto_url": None,
        "grupos_personalizacao": [],
        "ativo": True,
        "vendus_ref": "999",
    })
    produtos_vendus = [
        {"id": "500", "title": "Açaí Regular", "gross_price": 8.99, "tax_id": "NOR",
         "category_id": "10"}
    ]

    resultado = _corre(_sincronizar_produtos(db, produtos_vendus, {"10": "cat-local-1"}))

    assert resultado["criados"] == 1
    assert resultado["ligados"] == 0
    assert len(db.produtos.documentos) == 2


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


# --- A lista de artigos do Vendus, para a ficha do produto -------------------
#
# O dono: «na hora de criar um artigo, ter na ficha dele uma área de confirmar
# e ligar a um produto específico no Vendus — assim não teria erro». Até aqui
# só havia dois caminhos para um produto ter `vendus_ref`: vir da importação,
# ou o acaso de a importação lhe casar o nome. Um produto criado à mão ficava
# sem ligação nenhuma e, a partir daí, cada venda dele deixava um artigo novo
# no catálogo do Vendus.
#
# Esta leitura é o que enche o escolhedor da ficha. Devolve a lista do Vendus
# JÁ com quem, do nosso lado, já a está a usar — sem isso o dono ligaria dois
# produtos nossos ao mesmo artigo sem nunca o saber.


class ClienteSoProdutos:
    """Duplo do ClienteVendus com um catálogo pequeno e legível."""

    instancias = []
    erro = None

    def __init__(self, chave):
        self.chave = chave
        ClienteSoProdutos.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def listar_produtos(self):
        if ClienteSoProdutos.erro is not None:
            raise ClienteSoProdutos.erro
        return [
            {"id": 171258472, "title": "Açaí Mini", "reference": "ACM",
             "gross_price": 5.90, "tax_id": "INT", "category_id": "1"},
            {"id": 171258999, "title": "Água 33cl", "reference": "AG33",
             "gross_price": 1.00, "tax_id": "INT", "category_id": "1"},
            {"id": 0, "title": "Artigo estragado", "gross_price": 1.0},
        ]


def _prepara(monkeypatch, produtos_nossos=None):
    from faturacao.vendus.cliente import VendusErro  # noqa: F401  (usado pelos testes)

    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"chave-teste","company_nif":"517542510"}]')
    monkeypatch.setenv("FAT_NIF", "517542510")
    db = DbMemoria()
    for p in produtos_nossos or []:
        db.produtos.documentos.append(deepcopy(p))
    monkeypatch.setattr(importacao_mod, "obter_db", lambda: db)
    monkeypatch.setattr(importacao_mod, "ClienteVendus", ClienteSoProdutos)
    ClienteSoProdutos.instancias.clear()
    ClienteSoProdutos.erro = None
    return db


def test_artigos_do_vendus_devolve_a_lista_para_escolher(monkeypatch):
    _prepara(monkeypatch)
    artigos = _corre(importacao_mod.artigos_do_vendus(_={}))

    assert ClienteSoProdutos.instancias[0].chave == "chave-teste"
    assert [a["id"] for a in artigos] == ["171258472", "171258999"]
    acai = artigos[0]
    assert acai["nome"] == "Açaí Mini"
    assert acai["referencia"] == "ACM"
    assert acai["preco"] == 5.90
    assert acai["tax_id"] == "INT"


def test_artigos_do_vendus_DEIXA_DE_FORA_o_que_a_emissao_nao_saberia_enviar(monkeypatch):
    """Um artigo com `id` 0 não é escolhível: a linha da fatura sairia sem
    `id` na mesma (ver `precos.id_vendus_do_produto`), e o escolhedor teria
    prometido uma ligação que não existe. A regra é a mesma da emissão."""
    _prepara(monkeypatch)
    artigos = _corre(importacao_mod.artigos_do_vendus(_={}))
    assert "Artigo estragado" not in {a["nome"] for a in artigos}


def test_artigos_do_vendus_DIZ_quem_ja_esta_a_usar_cada_artigo(monkeypatch):
    """Dois produtos nossos ligados ao mesmo artigo do Vendus não partem a
    emissão, mas baralham o catálogo de lá para sempre — e o dono não tinha
    como o ver antes de escolher."""
    _prepara(monkeypatch, produtos_nossos=[
        {"id": "p1", "nome": "Açaí Mini", "vendus_ref": "171258472"},
    ])
    artigos = _corre(importacao_mod.artigos_do_vendus(_={}))
    por_id = {a["id"]: a for a in artigos}
    assert por_id["171258472"]["ligado_a"] == "Açaí Mini"
    assert por_id["171258999"]["ligado_a"] is None


def test_artigos_do_vendus_sem_conta_configurada_explica_se(monkeypatch):
    _prepara(monkeypatch)
    monkeypatch.setenv("VENDUS_ACCOUNTS", "[]")
    with pytest.raises(HTTPException) as e:
        _corre(importacao_mod.artigos_do_vendus(_={}))
    assert e.value.status_code == 400
    assert "Vendus" in e.value.detail


def test_artigos_do_vendus_com_o_vendus_em_baixo_nao_finge_lista_vazia(monkeypatch):
    """Uma lista vazia com ar de sucesso dizia ao dono «esta conta não tem
    artigos» — e ele criava o produto sem ligação a acreditar que não havia
    nenhum para escolher."""
    from faturacao.vendus.cliente import VendusErro

    _prepara(monkeypatch)
    ClienteSoProdutos.erro = VendusErro(500, "boom")
    with pytest.raises(HTTPException) as e:
        _corre(importacao_mod.artigos_do_vendus(_={}))
    assert e.value.status_code == 502


def test_a_rota_dos_artigos_do_vendus_existe_e_e_do_gestor():
    """Perguntado ao router, e não afirmado — um prefixo errado responde 404 e
    o escolhedor fica vazio para sempre, sem nada partir."""
    from faturacao import router
    from faturacao.auth import gestor_atual

    rotas = [r for r in router.routes
             if r.path == "/api/faturacao/vendus/artigos" and "GET" in r.methods]
    assert len(rotas) == 1, [r.path for r in router.routes if "vendus" in r.path]

    encontrados = set()

    def procura(d):
        for filha in d.dependencies:
            encontrados.add(filha.call)
            procura(filha)

    procura(rotas[0].dependant)
    assert gestor_atual in encontrados
