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
from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import catalogo as catalogo_mod
from faturacao.catalogo import (
    CategoriaEntrada,
    GrupoPersonalizacaoEntrada,
    OpcaoEntrada,
    ProdutoEntrada,
    ProdutoEstado,
    apagar_categoria,
    apagar_grupo,
    apagar_produto,
    criar_categoria,
    criar_grupo,
    criar_produto,
    editar_categoria,
    editar_grupo,
    editar_produto,
    listar_categorias,
    listar_grupos,
    listar_produtos,
    mudar_estado_produto,
    obter_produto,
    produtos_sem_iva,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ---------------------------------------------------
# Mesmo padrão de test_lojas.py: regista as chamadas e devolve resultados à
# escolha do teste.


def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find`/`find_one` reais descodificam BSON de fresco a cada chamada: o
    resultado NUNCA está ligado ao que está no Mongo, e duas leituras nunca
    devolvem o MESMO objecto. Um duplo enlatado que devolve sempre o
    dicionário do teste deixa passar por ALIASING uma asserção sobre a fixture
    que o código de produção mutou sem ter escrito nada. Já apanhou um caso
    real neste módulo (`cancelar_venda`, em faturacao/venda.py).

    Cópia FUNDA, não `dict(d)`: aqui é obrigatório e não por precaução — os
    grupos de personalização trazem `opcoes` (uma lista de dicionários por
    onde passa `_opcoes_com_id`) e os produtos trazem `grupos_personalizacao`.
    Uma cópia rasa partilhava essas listas com a fixture e o aliasing voltava
    uma camada abaixo, onde é ainda mais difícil de ver.
    """
    return deepcopy(documento)


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
        return CursorFalso([_como_o_motor(d) for d in self._find_devolve])

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return _como_o_motor(self._find_one_devolve)

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


def test_opcao_com_preco_negativo_e_recusada():
    """Deixado em aberto na Task 19: sem esta guarda, um topping a -2€ baixava
    o total da linha em vez de o subir."""
    with pytest.raises(ValidationError):
        OpcaoEntrada(nome="Desconto fantasma", preco=-2)


def test_opcao_com_preco_infinito_e_recusada():
    """MINOR: Infinity não é negativo nem tem casas decimais — passava por
    todas as outras guardas, e o `json` do Python aceita o literal
    `Infinity` sem se queixar."""
    with pytest.raises(ValidationError):
        OpcaoEntrada(nome="Topping", preco=float("inf"))


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


def test_min_select_negativo_e_recusado():
    """Mesma guarda de sinal do `preco` (Field(ge=0)) — é nestes dois números
    que vive toda a semântica de selecção (0=ilimitado, 1=escolha única)."""
    with pytest.raises(ValidationError):
        GrupoPersonalizacaoEntrada(nome="Toppings", min_select=-3)


def test_max_select_negativo_e_recusado():
    with pytest.raises(ValidationError):
        GrupoPersonalizacaoEntrada(nome="Toppings", min_select=-3, max_select=-5)


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


# --- Produtos: modelo -----------------------------------------------------------


def _dados_produto(**over):
    base = dict(nome="Açaí Regular", categoria_id="cat-1", preco=8.99, tax_id="INT")
    base.update(over)
    return base


def test_produto_minimo():
    p = ProdutoEntrada(**_dados_produto())
    assert p.nome == "Açaí Regular"
    assert p.preco == 8.99
    assert p.tax_id == "INT"
    assert p.foto_url is None
    assert p.grupos_personalizacao == []
    assert p.ativo is True
    assert p.vendus_ref is None


def test_produto_sem_tax_id_e_recusado():
    """A regra que não se negoceia: sem valor por omissão nenhum — ver o
    cabeçalho de precos.py sobre a app antiga que faturava a 13% em silêncio."""
    dados = _dados_produto()
    del dados["tax_id"]
    with pytest.raises(ValidationError):
        ProdutoEntrada(**dados)


def test_produto_tax_id_vazio_e_recusado():
    with pytest.raises(ValidationError):
        ProdutoEntrada(**_dados_produto(tax_id=""))


def test_produto_tax_id_desconhecido_e_recusado():
    with pytest.raises(ValidationError) as e:
        ProdutoEntrada(**_dados_produto(tax_id="XYZ"))
    assert "IVA" in str(e.value)


@pytest.mark.parametrize("tax_id", ["NOR", "INT", "RED", "ISE"])
def test_produto_tax_id_valido_do_vendus_e_aceite(tax_id):
    assert ProdutoEntrada(**_dados_produto(tax_id=tax_id)).tax_id == tax_id


def test_produto_sem_categoria_e_recusado():
    dados = _dados_produto()
    del dados["categoria_id"]
    with pytest.raises(ValidationError):
        ProdutoEntrada(**dados)


def test_produto_com_preco_negativo_e_recusado():
    """Guarda de sinal também no preço do produto, não só nas opções."""
    with pytest.raises(ValidationError):
        ProdutoEntrada(**_dados_produto(preco=-1))


def test_produto_com_preco_de_3_casas_e_recusado():
    with pytest.raises(ValidationError) as e:
        ProdutoEntrada(**_dados_produto(preco=8.995))
    assert "8.995" in str(e.value)


@pytest.mark.parametrize("preco", [8.99, 8.9, 9, 0, 0.0])
def test_produto_com_preco_valido_e_aceite(preco):
    assert ProdutoEntrada(**_dados_produto(preco=preco)).preco == preco


def test_produto_com_preco_infinito_e_recusado():
    """MINOR: Infinity não é negativo nem tem casas decimais — passava por
    todas as outras guardas."""
    with pytest.raises(ValidationError):
        ProdutoEntrada(**_dados_produto(preco=float("inf")))


def test_produto_com_grupos_de_personalizacao():
    p = ProdutoEntrada(**_dados_produto(grupos_personalizacao=["g1", "g2"]))
    assert p.grupos_personalizacao == ["g1", "g2"]


def test_produto_estado_minimo():
    assert ProdutoEstado(ativo=False).ativo is False


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


def test_apagar_grupo_atribuido_a_produtos_e_recusado_409(monkeypatch):
    """Deixado em aberto na Task 19 (o campo que liga produtos a grupos só
    nasce agora): mesmo padrão do apagar_loja com as caixas e do apagar de
    categorias — um grupo atribuído não pode desaparecer debaixo dos produtos."""
    registo = []
    db = DbFalsa(
        {
            "fat_produtos": ColeccaoFalsa(registo, count_documents_devolve=2),
            "fat_grupos_personalizacao": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_grupo("g1", _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "delete_one" for chamada in registo)


def test_apagar_grupo_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa(
        {
            "fat_produtos": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_grupos_personalizacao": ColeccaoFalsa(registo, delete_one_devolve=0),
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_grupo("nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_grupo_existente_e_apagado(monkeypatch):
    registo = []
    db = DbFalsa(
        {
            "fat_produtos": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_grupos_personalizacao": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_grupo("g1", _={}))
    assert resultado == {"apagado": True}


# --- Produtos: endpoints ---------------------------------------------------------

_PRODUTO = ProdutoEntrada(nome="Açaí Regular", categoria_id="cat-1", preco=8.99, tax_id="INT")

_DADOS_CATEGORIA_OK = {"id": "cat-1", "nome": "Venda ao Público", "ordem": 1, "ativa": True}
_DADOS_GRUPO_1 = {"id": "g1", "nome": "Toppings"}
_DADOS_GRUPO_2 = {"id": "g2", "nome": "Tamanho"}


def _db_produtos(
    registo,
    produtos_find_devolve=None,
    produtos_find_one_devolve=None,
    produtos_update_one_matched=0,
    produtos_delete_one_devolve=0,
    categoria_find_one_devolve=_DADOS_CATEGORIA_OK,
    grupos_find_devolve=None,
):
    """Monta a DbFalsa com as 3 colecções de que os endpoints de produto
    precisam: produtos (CRUD), categorias e grupos (validação de referências)."""
    return DbFalsa(
        {
            "fat_produtos": ColeccaoFalsa(
                registo,
                find_devolve=produtos_find_devolve,
                find_one_devolve=produtos_find_one_devolve,
                update_one_matched=produtos_update_one_matched,
                delete_one_devolve=produtos_delete_one_devolve,
            ),
            "fat_categorias": ColeccaoFalsa(registo, find_one_devolve=categoria_find_one_devolve),
            "fat_grupos_personalizacao": ColeccaoFalsa(
                registo, find_devolve=grupos_find_devolve or []
            ),
        }
    )


def test_listar_produtos_sem_filtro(monkeypatch):
    registo = []
    dados = [
        {"id": "p2", "nome": "Batido", "categoria_id": "cat-1"},
        {"id": "p1", "nome": "Açaí Regular", "categoria_id": "cat-1"},
    ]
    db = _db_produtos(registo, produtos_find_devolve=dados)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(listar_produtos(categoria_id=None, texto=None, _={}))
    assert [p["nome"] for p in resultado] == ["Açaí Regular", "Batido"]


def test_listar_produtos_filtra_por_categoria(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_find_devolve=[])
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    _corre(listar_produtos(categoria_id="cat-2", texto=None, _={}))
    chamada_find = next(c for c in registo if c[0] == "find")
    assert chamada_find[1]["categoria_id"] == "cat-2"


def test_listar_produtos_filtra_por_texto(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_find_devolve=[])
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    _corre(listar_produtos(categoria_id=None, texto="açaí", _={}))
    chamada_find = next(c for c in registo if c[0] == "find")
    assert "nome" in chamada_find[1]


def test_criar_produto_atribui_id(monkeypatch):
    registo = []
    db = _db_produtos(registo)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(criar_produto(_PRODUTO, _={}))
    assert resultado["id"]
    assert resultado["nome"] == "Açaí Regular"
    assert any(chamada[0] == "insert_one" for chamada in registo)


def test_criar_produto_com_categoria_inexistente_e_recusado_422(monkeypatch):
    registo = []
    db = _db_produtos(registo, categoria_find_one_devolve=None)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(criar_produto(_PRODUTO, _={}))
    assert excinfo.value.status_code == 422
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_criar_produto_com_grupo_inexistente_e_recusado_422(monkeypatch):
    registo = []
    dados = ProdutoEntrada(
        nome="Açaí Regular",
        categoria_id="cat-1",
        preco=8.99,
        tax_id="INT",
        grupos_personalizacao=["g1", "g-fantasma"],
    )
    db = _db_produtos(registo, grupos_find_devolve=[_DADOS_GRUPO_1])
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(criar_produto(dados, _={}))
    assert excinfo.value.status_code == 422
    assert "g-fantasma" in excinfo.value.detail
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_criar_produto_com_grupos_existentes_e_criado(monkeypatch):
    registo = []
    dados = ProdutoEntrada(
        nome="Açaí Regular",
        categoria_id="cat-1",
        preco=8.99,
        tax_id="INT",
        grupos_personalizacao=["g1", "g2"],
    )
    db = _db_produtos(registo, grupos_find_devolve=[_DADOS_GRUPO_1, _DADOS_GRUPO_2])
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(criar_produto(dados, _={}))
    assert resultado["grupos_personalizacao"] == ["g1", "g2"]


def test_obter_produto_inexistente_devolve_404(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_find_one_devolve=None)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(obter_produto("nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_obter_produto_existente(monkeypatch):
    registo = []
    dados_produto = {"id": "p1", "nome": "Açaí Regular", "categoria_id": "cat-1"}
    db = _db_produtos(registo, produtos_find_one_devolve=dados_produto)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(obter_produto("p1", _={}))
    assert resultado["nome"] == "Açaí Regular"


def test_editar_produto_inexistente_devolve_404(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_update_one_matched=0)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_produto("nao-existe", _PRODUTO, _={}))
    assert excinfo.value.status_code == 404


def test_editar_produto_com_categoria_inexistente_e_recusado_422(monkeypatch):
    registo = []
    db = _db_produtos(registo, categoria_find_one_devolve=None)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_produto("p1", _PRODUTO, _={}))
    assert excinfo.value.status_code == 422
    assert not any(chamada[0] == "update_one" for chamada in registo)


def test_editar_produto_existente_e_editado(monkeypatch):
    registo = []
    dados_produto = {"id": "p1", "nome": "Açaí Regular", "categoria_id": "cat-1"}
    db = _db_produtos(
        registo, produtos_update_one_matched=1, produtos_find_one_devolve=dados_produto
    )
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(editar_produto("p1", _PRODUTO, _={}))
    assert resultado["nome"] == "Açaí Regular"


def test_apagar_produto_inexistente_devolve_404(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_delete_one_devolve=0)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_produto("nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_produto_existente_e_apagado(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_delete_one_devolve=1)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_produto("p1", _={}))
    assert resultado == {"apagado": True}


def test_mudar_estado_produto_inexistente_devolve_404(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_update_one_matched=0)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(mudar_estado_produto("nao-existe", ProdutoEstado(ativo=False), _={}))
    assert excinfo.value.status_code == 404


def test_mudar_estado_produto_desativa(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_update_one_matched=1)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(mudar_estado_produto("p1", ProdutoEstado(ativo=False), _={}))
    assert resultado == {"ativo": False}
    escrita = next(c for c in registo if c[0] == "update_one")
    assert escrita[2]["$set"] == {"ativo": False}


def test_produtos_sem_iva_devolve_so_os_incompletos(monkeypatch):
    """O endpoint apoia-se em erros_do_produto (precos.py) — não reimplementa
    a regra do que falta a um produto para poder ser vendido."""
    registo = []
    dados = [
        {"id": "p1", "nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT"},
        {"id": "p2", "nome": "Refrigerante", "preco": 2.5},
        {"id": "p3", "nome": "Sem preço nem IVA"},
    ]
    db = _db_produtos(registo, produtos_find_devolve=dados)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    resultado = _corre(produtos_sem_iva(_={}))
    nomes = {p["nome"] for p in resultado}
    assert nomes == {"Refrigerante", "Sem preço nem IVA"}
    refrigerante = next(p for p in resultado if p["nome"] == "Refrigerante")
    assert refrigerante["erros"] == ["Sem IVA definido"]


def test_produtos_sem_iva_vazio_quando_todos_completos(monkeypatch):
    registo = []
    dados = [{"id": "p1", "nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT"}]
    db = _db_produtos(registo, produtos_find_devolve=dados)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    assert _corre(produtos_sem_iva(_={})) == []


# --- O vendus_ref não se apaga sozinho ----------------------------------------
#
# Este campo passou de "ajuda a importação a não duplicar" a "é o que impede o
# catálogo do Vendus de encher": é o id que a emissão manda em cada linha da
# fatura (precos.linha_de_venda) para o Vendus LIGAR a linha ao produto que já
# lá existe. Sem ele, o Vendus não casa por nome e cria um produto novo A CADA
# VENDA — foi assim que a conta real ficou com 14 "Açaí Mini", 13 deles lixo
# sem categoria, com referências VACA…
#
# O PUT substitui o registo inteiro e `ProdutoEntrada.vendus_ref` tem `= None`
# por omissão, por isso um pedido que não o repita apagava-o. O backoffice
# reenvia-o à mão (FatProdutos.js), mas essa defesa vive no browser: um script
# ou um curl desligava a correcção em silêncio.


def _set_do_update(registo):
    """O que foi mesmo pedido ao Mongo — é aqui que se vê se o campo seguiu."""
    for op in registo:
        if op[0] == "update_one":
            return op[2]["$set"]
    raise AssertionError("não houve update_one nenhum")


def test_editar_produto_sem_falar_do_vendus_ref_nao_lhe_toca(monkeypatch):
    registo = []
    db = _db_produtos(registo, produtos_update_one_matched=1,
                      produtos_find_one_devolve={"id": "p1"})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    # O corpo NÃO fala do vendus_ref — é o caso do script e do curl.
    _corre(editar_produto("p1", ProdutoEntrada(
        nome="Açaí Mini", categoria_id="cat-1", preco=6.20, tax_id="INT"), _={}))

    alteracoes = _set_do_update(registo)
    assert alteracoes["preco"] == 6.20, "a alteração pedida tem de passar na mesma"
    assert "vendus_ref" not in alteracoes, (
        "o PUT ia gravar vendus_ref=None por omissão — a partir daí cada venda "
        "deste artigo cria um produto novo no Vendus"
    )


def test_editar_produto_ainda_desliga_a_ligacao_quando_lho_pedem(monkeypatch):
    """A guarda protege o esquecimento, não impede a decisão: quem MANDA o
    campo, manda mesmo, inclusive a nulo."""
    registo = []
    db = _db_produtos(registo, produtos_update_one_matched=1,
                      produtos_find_one_devolve={"id": "p1"})
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)

    _corre(editar_produto("p1", ProdutoEntrada(
        nome="Açaí Mini", categoria_id="cat-1", preco=5.85, tax_id="INT",
        vendus_ref=None), _={}))

    alteracoes = _set_do_update(registo)
    assert "vendus_ref" in alteracoes and alteracoes["vendus_ref"] is None
