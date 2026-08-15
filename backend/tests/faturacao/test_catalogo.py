"""Catálogo — Categorias e Grupos de Personalização (sem base de dados).

Nascem antes dos Produtos (Task 20): um produto vai apontar para uma categoria
e para grupos de personalização. Mesmo padrão de duplo de base de dados que
test_lojas.py e test_pagamentos_endpoints.py.

A substância está nas validações dos grupos (spec §9.1, modelo levantado da
app L'Açaí em produção): `min_select` maior do que o número de opções,
`min_select` maior do que `max_select`, e o preço de uma opção com mais de 2
casas decimais — o mesmo cêntimo que `round()` sobre binário come em
precos.py (`_tem_mais_de_2_casas_decimais`, reutilizado aqui e não reescrito).
"""
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import catalogo as catalogo_mod
from faturacao.catalogo import (
    CategoriaEntrada,
    GrupoPersonalizacaoEntrada,
    OpcaoEntrada,
    apagar_categoria,
    apagar_grupo,
    criar_categoria,
    criar_grupo,
    editar_categoria,
    editar_grupo,
    listar_categorias,
    listar_grupos,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ---------------------------------------------------
# Mesmo padrão de test_lojas.py: regista as chamadas e devolve resultados à
# escolha do teste.


class ResultadoUpdate:
    """Duplo do resultado de update_one do Motor — só o campo que o código usa."""

    def __init__(self, matched_count):
        self.matched_count = matched_count


class ResultadoDelete:
    """Duplo do resultado de delete_one do Motor — só o campo que o código usa."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class CursorFalso:
    """Duplo de um cursor Mongo: imita find().sort().to_list() do Motor. Só
    ordena os dados devolvidos se sort() tiver sido mesmo chamado."""

    def __init__(self, dados):
        self._dados = dados
        self._ordem = None  # Tuplo (campo, direcção)

    def sort(self, campo, direcção=1):
        self._ordem = (campo, direcção)
        return self

    async def to_list(self, limite):
        dados = list(self._dados)
        if self._ordem:
            campo, direcção = self._ordem
            dados.sort(key=lambda d: d.get(campo, ""), reverse=(direcção == -1))
        return dados


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: regista as chamadas e devolve resultados à escolha do teste."""

    def __init__(
        self,
        registo,
        find_devolve=None,
        find_one_devolve=None,
        update_one_matched=0,
        delete_one_devolve=0,
        count_documents_devolve=0,
    ):
        self.registo = registo
        self._find_devolve = find_devolve or []
        self._find_one_devolve = find_one_devolve
        self._update_one_matched = update_one_matched
        self._delete_one_devolve = delete_one_devolve
        self._count_documents_devolve = count_documents_devolve

    def find(self, filtro, projecao=None):
        self.registo.append(("find", filtro))
        return CursorFalso(self._find_devolve)

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return self._find_one_devolve

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        return None

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        return ResultadoUpdate(self._update_one_matched)

    async def delete_one(self, filtro):
        self.registo.append(("delete_one", filtro))
        return ResultadoDelete(self._delete_one_devolve)

    async def count_documents(self, filtro):
        self.registo.append(("count_documents", filtro))
        return self._count_documents_devolve


class DbFalsa:
    def __init__(self, colecoes):
        self._colecoes = colecoes

    def __getitem__(self, nome):
        return self._colecoes[nome]


# --- Categorias: modelo -------------------------------------------------------


def test_categoria_minima():
    c = CategoriaEntrada(nome="Venda ao Público")
    assert c.nome == "Venda ao Público"
    assert c.ordem == 0
    assert c.ativa is True


def test_categoria_sem_nome_e_recusada():
    with pytest.raises(ValidationError):
        CategoriaEntrada(nome="")


# --- Opções: modelo -------------------------------------------------------


def test_opcao_minima():
    o = OpcaoEntrada(nome="Banana")
    assert o.id is None
    assert o.preco == 0.0
    assert o.ativa is True


def test_opcao_sem_nome_e_recusada():
    with pytest.raises(ValidationError):
        OpcaoEntrada(nome="")


def test_opcao_com_preco_de_3_casas_e_recusada():
    """O mesmo crivo do precos.py: 0,995 perderia o cêntimo ao arredondar."""
    with pytest.raises(ValidationError) as e:
        OpcaoEntrada(nome="Nutella", preco=0.995)
    assert "0.995" in str(e.value)


@pytest.mark.parametrize("preco", [0.95, 0.9, 1, 0, 0.0])
def test_opcao_com_ate_2_casas_e_aceite(preco):
    assert OpcaoEntrada(nome="Nutella", preco=preco).preco == preco


# --- Grupos de personalização: modelo -----------------------------------------


def test_grupo_minimo():
    g = GrupoPersonalizacaoEntrada(nome="Toppings")
    assert g.min_select == 0
    assert g.max_select == 0
    assert g.opcoes == []
    assert g.ativo is True


def test_grupo_sem_nome_e_recusado():
    with pytest.raises(ValidationError):
        GrupoPersonalizacaoEntrada(nome="")


def test_grupo_nao_tem_campos_redundantes():
    """A semântica é derivada de min_select/max_select — não se acrescenta
    'obrigatorio' nem 'tipo', que seriam uma segunda fonte de verdade."""
    assert "obrigatorio" not in GrupoPersonalizacaoEntrada.model_fields
    assert "tipo" not in GrupoPersonalizacaoEntrada.model_fields


def test_min_select_maior_que_max_select_e_recusado():
    with pytest.raises(ValidationError) as e:
        GrupoPersonalizacaoEntrada(
            nome="Toppings",
            min_select=3,
            max_select=2,
            opcoes=[
                OpcaoEntrada(nome="A"),
                OpcaoEntrada(nome="B"),
                OpcaoEntrada(nome="C"),
            ],
        )
    assert "mínimo" in str(e.value).lower()


def test_min_select_igual_max_select_e_aceite():
    g = GrupoPersonalizacaoEntrada(
        nome="Tamanho",
        min_select=1,
        max_select=1,
        opcoes=[OpcaoEntrada(nome="Pequeno"), OpcaoEntrada(nome="Grande")],
    )
    assert g.min_select == g.max_select == 1


def test_max_select_zero_e_ilimitado_mesmo_com_min_select_alto():
    """max_select == 0 significa ilimitado — não há tecto para comparar com
    min_select, por isso min_select=2 e max_select=0 é válido."""
    g = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        min_select=2,
        max_select=0,
        opcoes=[OpcaoEntrada(nome="A"), OpcaoEntrada(nome="B")],
    )
    assert g.max_select == 0
    assert g.min_select == 2


def test_min_select_maior_que_numero_de_opcoes_e_recusado():
    with pytest.raises(ValidationError) as e:
        GrupoPersonalizacaoEntrada(
            nome="Toppings",
            min_select=3,
            opcoes=[OpcaoEntrada(nome="A"), OpcaoEntrada(nome="B")],
        )
    assert "opç" in str(e.value).lower()


def test_min_select_igual_ao_numero_de_opcoes_e_aceite():
    g = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        min_select=2,
        opcoes=[OpcaoEntrada(nome="A"), OpcaoEntrada(nome="B")],
    )
    assert g.min_select == 2


def test_min_select_zero_sem_opcoes_e_aceite():
    """Um grupo pode nascer vazio (opções acrescentadas depois) desde que não
    seja obrigatório."""
    g = GrupoPersonalizacaoEntrada(nome="Toppings")
    assert g.opcoes == []


def test_preco_de_opcao_dentro_do_grupo_com_3_casas_e_recusado():
    with pytest.raises(ValidationError) as e:
        GrupoPersonalizacaoEntrada(nome="Toppings", opcoes=[{"nome": "Nutella", "preco": 0.995}])
    assert "0.995" in str(e.value)


# --- Categorias: endpoints -----------------------------------------------------

_CATEGORIA = CategoriaEntrada(nome="Venda ao Público", ordem=1)


def test_listar_categorias_ordenadas_por_ordem(monkeypatch):
    registo = []
    dados = [
        {"id": "2", "nome": "Vendas Aplicações", "ordem": 2, "ativa": True},
        {"id": "1", "nome": "Venda ao Público", "ordem": 1, "ativa": True},
    ]
    db = DbFalsa({"fat_categorias": ColeccaoFalsa(registo, find_devolve=dados)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(listar_categorias(_={}))
    assert [c["ordem"] for c in resultado] == [1, 2]


def test_criar_categoria_atribui_id(monkeypatch):
    registo = []
    db = DbFalsa({"fat_categorias": ColeccaoFalsa(registo)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(criar_categoria(_CATEGORIA, _={}))
    assert resultado["id"]
    assert resultado["nome"] == "Venda ao Público"
    assert any(chamada[0] == "insert_one" for chamada in registo)


def test_editar_categoria_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa({"fat_categorias": ColeccaoFalsa(registo, update_one_matched=0)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_categoria("nao-existe", _CATEGORIA, _={}))
    assert excinfo.value.status_code == 404


def test_editar_categoria_existente_e_editada(monkeypatch):
    registo = []
    db = DbFalsa(
        {
            "fat_categorias": ColeccaoFalsa(
                registo,
                update_one_matched=1,
                find_one_devolve={"id": "1", "nome": "Venda ao Público", "ordem": 1, "ativa": True},
            )
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(editar_categoria("1", _CATEGORIA, _={}))
    assert resultado["nome"] == "Venda ao Público"


def test_apagar_categoria_com_produtos_e_recusada_409(monkeypatch):
    """A guarda central desta tarefa: apagar uma categoria com produtos não
    pode deixar produtos órfãos a apontar para uma categoria inexistente."""
    registo = []
    db = DbFalsa(
        {
            "fat_produtos": ColeccaoFalsa(registo, count_documents_devolve=3),
            "fat_categorias": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_categoria("1", _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "delete_one" for chamada in registo)


def test_apagar_categoria_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa(
        {
            "fat_produtos": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_categorias": ColeccaoFalsa(registo, delete_one_devolve=0),
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_categoria("nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_categoria_sem_produtos_e_apagada(monkeypatch):
    registo = []
    db = DbFalsa(
        {
            "fat_produtos": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_categorias": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_categoria("1", _={}))
    assert resultado == {"apagada": True}


# --- Grupos de personalização: endpoints ---------------------------------------


def test_listar_grupos_ordenados_por_nome(monkeypatch):
    registo = []
    dados = [
        {"id": "2", "nome": "Tamanho", "min_select": 1, "max_select": 1, "opcoes": [], "ativo": True},
        {"id": "1", "nome": "Açúcar", "min_select": 0, "max_select": 0, "opcoes": [], "ativo": True},
    ]
    db = DbFalsa({"fat_grupos_personalizacao": ColeccaoFalsa(registo, find_devolve=dados)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(listar_grupos(_={}))
    assert [g["nome"] for g in resultado] == ["Açúcar", "Tamanho"]


def test_criar_grupo_atribui_id_as_opcoes_sem_id(monkeypatch):
    registo = []
    db = DbFalsa({"fat_grupos_personalizacao": ColeccaoFalsa(registo)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings", opcoes=[OpcaoEntrada(nome="Nutella", preco=0.95)]
    )
    resultado = _corre(criar_grupo(dados, _={}))
    assert resultado["id"]
    assert resultado["opcoes"][0]["id"]
    assert resultado["opcoes"][0]["nome"] == "Nutella"


def test_editar_grupo_preserva_id_das_opcoes_existentes_e_atribui_as_novas(monkeypatch):
    """Uma opção que já existia mantém o id (o histórico de vendas continua a
    apontar para ela); uma opção nova recebe um id novo."""
    registo = []
    db = DbFalsa(
        {
            "fat_grupos_personalizacao": ColeccaoFalsa(
                registo,
                update_one_matched=1,
                find_one_devolve={
                    "id": "g1",
                    "nome": "Toppings",
                    "min_select": 0,
                    "max_select": 0,
                    "opcoes": [{"id": "opt-1", "nome": "Nutella", "preco": 0.95, "ativa": True}],
                    "ativo": True,
                },
            )
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    dados = GrupoPersonalizacaoEntrada(
        nome="Toppings",
        opcoes=[
            OpcaoEntrada(id="opt-1", nome="Nutella", preco=0.95),
            OpcaoEntrada(nome="Banana", preco=0.0),
        ],
    )
    _corre(editar_grupo("g1", dados, _={}))

    escrita = next(c for c in registo if c[0] == "update_one")
    opcoes_escritas = escrita[2]["$set"]["opcoes"]
    assert opcoes_escritas[0]["id"] == "opt-1"
    assert opcoes_escritas[1]["id"]
    assert opcoes_escritas[1]["id"] != "opt-1"


def test_editar_grupo_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa({"fat_grupos_personalizacao": ColeccaoFalsa(registo, update_one_matched=0)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    dados = GrupoPersonalizacaoEntrada(nome="Toppings")
    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_grupo("nao-existe", dados, _={}))
    assert excinfo.value.status_code == 404


def test_apagar_grupo_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa({"fat_grupos_personalizacao": ColeccaoFalsa(registo, delete_one_devolve=0)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_grupo("nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_grupo_existente_e_apagado(monkeypatch):
    registo = []
    db = DbFalsa({"fat_grupos_personalizacao": ColeccaoFalsa(registo, delete_one_devolve=1)})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_grupo("g1", _={}))
    assert resultado == {"apagado": True}
