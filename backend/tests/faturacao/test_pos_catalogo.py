"""Catálogo e tipos de pagamento em leitura para o ecrã do POS (Plano 2C).

Mesmo padrão de duplo de base de dados de test_caixa_endpoints.py e
test_venda.py: find()/find_one() filtram de facto pelos campos do filtro.
Nenhum teste liga a uma base de dados nem à rede.

O que estes testes defendem, além do óbvio: **nada desaparece do ecrã em
silêncio**. Um produto sem IVA continua na grelha (marcado), um tipo de
pagamento por mapear continua na lista (marcado), e um grupo que ficou sem
opções não é "corrigido" a caminho do balcão. Filtrar qualquer um deles
passaria os testes de "só o que está activo" à mesma — é por isso que cada
um tem aqui um teste próprio a exigir a PRESENÇA dele.

A protecção das duas rotas está também coberta, de fora, por
test_protecao_rotas.py: esse ficheiro varre `faturacao.router` inteiro e não
tem lista de rotas para actualizar à mão — as duas rotas novas caem lá
sozinhas por começarem em `/api/faturacao/pos/`.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import pos_catalogo as pos_catalogo_mod
from faturacao.db import COLECOES
from faturacao.pos_auth import operador_atual
from faturacao.pos_catalogo import catalogo_do_pos, router, tipos_pagamento_do_pos


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ----------------------------------------------------


def _corresponde(item, filtro):
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


class CursorFalso:
    """Duplo de um cursor do Motor, com duas diferenças deliberadas em
    relação aos duplos dos outros ficheiros de teste:

    - `sort` ordena MESMO. Um `sort` que devolvesse `self` sem tocar na
      lista deixava os testes de ordem passarem com o `.sort()` apagado do
      código de produção — um teste a defender o defeito, coisa que já
      aconteceu três vezes neste módulo.
    - `find` ignora a projecção e devolve os documentos como estão, `_id`
      incluído. Também de propósito: o que impede um `_id` de sair na
      resposta é a construção campo a campo em pos_catalogo.py, não a
      projecção do find — e é isso, não a projecção, que estes testes têm
      de provar.
    """

    def __init__(self, itens, registo):
        self._itens = itens
        self._registo = registo

    def sort(self, campo, direcao=1):
        self._registo.append(("sort", campo, direcao))
        self._itens = sorted(self._itens, key=lambda d: d.get(campo), reverse=direcao < 0)
        return self

    async def to_list(self, n=None):
        self._registo.append(("to_list", n))
        return self._itens[:n] if n is not None else self._itens


class ColeccaoFalsa:
    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", filtro, projecao))
        return CursorFalso(
            [d for d in self._documentos if _corresponde(d, filtro)], self.registo
        )


class DbFalsa:
    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoFalsa([]))


def _db(registo, categorias=None, produtos=None, grupos=None, tipos_pagamento=None):
    return DbFalsa({
        COLECOES["categorias"]: ColeccaoFalsa(registo, categorias),
        COLECOES["produtos"]: ColeccaoFalsa(registo, produtos),
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, grupos),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa(registo, tipos_pagamento),
    })


def _categoria(**over):
    c = {"_id": "mongo-cat", "id": "cat-1", "nome": "Venda ao Público", "ordem": 0,
         "ativa": True, "vendus_ref": None}
    c.update(over)
    return c


def _produto(**over):
    p = {"_id": "mongo-prod", "id": "prod-1", "nome": "Açaí Regular", "preco": 8.99,
         "tax_id": "INT", "categoria_id": "cat-1", "foto_url": None,
         "grupos_personalizacao": [], "ativo": True, "vendus_ref": None}
    p.update(over)
    return p


def _opcao(**over):
    o = {"id": "op-nutella", "nome": "Nutella", "preco": 0.95, "ativa": True}
    o.update(over)
    return o


def _grupo(**over):
    g = {"_id": "mongo-grupo", "id": "grupo-1", "nome": "Toppings", "min_select": 0,
         "max_select": 0, "opcoes": [_opcao()], "ativo": True}
    g.update(over)
    return g


def _tipo(**over):
    t = {"_id": "mongo-tipo", "id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU",
         "da_troco": True, "ordem": 0, "ativo": True,
         "vendus_payment_method_id": "316430468", "protegido": False}
    t.update(over)
    return t


def _monta(monkeypatch, **coleccoes):
    registo = []
    monkeypatch.setattr(pos_catalogo_mod, "obter_db", lambda: _db(registo, **coleccoes))
    return registo


# --- GET /pos/catalogo ---------------------------------------------------------


def test_catalogo_devolve_so_o_que_esta_activo(monkeypatch):
    """Categoria, produto e grupo desactivados no backoffice não chegam ao
    balcão. Repare-se no género do campo: a categoria tem `ativa`, o produto
    e o grupo têm `ativo` — trocar um pelo outro devolve tudo ou nada."""
    _monta(
        monkeypatch,
        categorias=[_categoria(), _categoria(id="cat-2", nome="Aplicações", ativa=False)],
        produtos=[_produto(), _produto(id="prod-2", nome="Açaí Descontinuado", ativo=False)],
        grupos=[_grupo(), _grupo(id="grupo-2", nome="Extras Antigos", ativo=False)],
    )

    resposta = _corre(catalogo_do_pos(_={}))

    assert [c["id"] for c in resposta["categorias"]] == ["cat-1"]
    assert [p["id"] for p in resposta["produtos"]] == ["prod-1"]
    assert [g["id"] for g in resposta["grupos_personalizacao"]] == ["grupo-1"]


def test_catalogo_ordena_categorias_por_ordem_e_produtos_por_nome(monkeypatch):
    """A ordem dos separadores é a que o gestor definiu (`ordem`); a da
    grelha é alfabética, como no backoffice — a operadora tem de encontrar o
    artigo sempre no mesmo sítio."""
    _monta(
        monkeypatch,
        categorias=[
            _categoria(id="cat-2", nome="Aplicações", ordem=2),
            _categoria(id="cat-1", nome="Venda ao Público", ordem=1),
        ],
        produtos=[
            _produto(id="prod-2", nome="Zumo de Laranja"),
            _produto(id="prod-1", nome="Açaí Regular"),
        ],
    )

    resposta = _corre(catalogo_do_pos(_={}))

    assert [c["id"] for c in resposta["categorias"]] == ["cat-1", "cat-2"]
    assert [p["nome"] for p in resposta["produtos"]] == ["Açaí Regular", "Zumo de Laranja"]


def test_produto_sem_iva_vem_marcado_e_continua_na_grelha(monkeypatch):
    """O teste central da rota: um artigo mal configurado NÃO é escondido.

    Vem com `vendavel: false` e a razão que `precos.erros_do_produto` dá (a
    mesma que `venda.py::juntar_linha` devolve num 422 e que o ecrã
    "Produtos sem IVA" do backoffice mostra). Escondê-lo fazia-o desaparecer
    sem ninguém saber que existia e estava mal."""
    _monta(
        monkeypatch,
        produtos=[
            _produto(),
            _produto(id="prod-2", nome="Água 50cl", tax_id=None),
            _produto(id="prod-3", nome="Brownie", preco=None),
        ],
    )

    produtos = {p["id"]: p for p in _corre(catalogo_do_pos(_={}))["produtos"]}

    assert set(produtos) == {"prod-1", "prod-2", "prod-3"}
    assert produtos["prod-1"]["vendavel"] is True
    assert produtos["prod-1"]["erros"] == []
    assert produtos["prod-2"]["vendavel"] is False
    assert produtos["prod-2"]["erros"] == ["Sem IVA definido"]
    assert produtos["prod-3"]["vendavel"] is False
    assert produtos["prod-3"]["erros"] == ["Sem preço definido"]


def test_produto_com_iva_desconhecido_tambem_vem_marcado(monkeypatch):
    """Um `tax_id` escrito à mão ('XPTO') não é IVA nenhum — a regra é a de
    `erros_do_produto`, não um "tem tax_id, logo vende-se"."""
    _monta(monkeypatch, produtos=[_produto(tax_id="XPTO")])

    produto = _corre(catalogo_do_pos(_={}))["produtos"][0]

    assert produto["vendavel"] is False
    assert produto["erros"] == ["Código de IVA desconhecido: XPTO"]


def test_catalogo_devolve_os_campos_do_produto_e_nenhum_id_do_mongo(monkeypatch):
    """O `_id` do Mongo não sai em lado nenhum — nem na categoria, nem no
    produto, nem no grupo. Os duplos deste ficheiro devolvem os documentos
    com `_id` de propósito (ver CursorFalso): quem o tira é a construção
    campo a campo, não a projecção do find."""
    _monta(
        monkeypatch,
        categorias=[_categoria()],
        produtos=[_produto(foto_url="/fotos/acai.jpg", grupos_personalizacao=["grupo-1"])],
        grupos=[_grupo()],
    )

    resposta = _corre(catalogo_do_pos(_={}))

    assert resposta["categorias"][0] == {
        "id": "cat-1", "nome": "Venda ao Público", "ordem": 0,
    }
    assert resposta["produtos"][0] == {
        "id": "prod-1", "nome": "Açaí Regular", "categoria_id": "cat-1", "preco": 8.99,
        "tax_id": "INT", "foto_url": "/fotos/acai.jpg",
        "grupos_personalizacao": ["grupo-1"], "vendavel": True, "erros": [],
    }
    assert resposta["grupos_personalizacao"][0] == {
        "id": "grupo-1", "nome": "Toppings", "min_select": 0, "max_select": 0,
        "opcoes": [{"id": "op-nutella", "nome": "Nutella", "preco": 0.95}],
    }
    assert "_id" not in resposta["grupos_personalizacao"][0]["opcoes"][0]


def test_opcoes_inactivas_nao_vem_mas_o_minimo_do_grupo_fica_como_esta(monkeypatch):
    """Um grupo com `min_select=1` cujas opções foram todas desactivadas
    fica impossível de satisfazer — e é assim que tem de chegar ao ecrã. Se
    o servidor baixasse o mínimo para 0, inventava uma configuração que o
    gestor não fez e o açaí saía sem o topping que alguém quis exigir."""
    _monta(
        monkeypatch,
        grupos=[
            _grupo(id="grupo-1", nome="Base obrigatória", min_select=1, max_select=1,
                   opcoes=[_opcao(id="op-morango", nome="Morango", ativa=False)]),
            _grupo(id="grupo-2", nome="Toppings",
                   opcoes=[_opcao(), _opcao(id="op-kiwi", nome="Kiwi", ativa=False)]),
        ],
    )

    grupos = {g["id"]: g for g in _corre(catalogo_do_pos(_={}))["grupos_personalizacao"]}

    assert grupos["grupo-1"]["opcoes"] == []
    assert grupos["grupo-1"]["min_select"] == 1
    assert grupos["grupo-1"]["max_select"] == 1
    assert [o["id"] for o in grupos["grupo-2"]["opcoes"]] == ["op-nutella"]


def test_catalogo_vazio_devolve_as_tres_listas(monkeypatch):
    """Uma loja com o catálogo ainda por importar não rebenta o ecrã: as
    três chaves vêm sempre, vazias."""
    _monta(monkeypatch)

    assert _corre(catalogo_do_pos(_={})) == {
        "categorias": [], "produtos": [], "grupos_personalizacao": [],
    }


def test_limites_de_leitura_sao_os_mesmos_do_backoffice(monkeypatch):
    """2000 produtos e 200 categorias são os limites que catalogo.py já usa
    — números novos aqui davam um balcão a ver um catálogo diferente do que
    se gere no backoffice."""
    registo = _monta(monkeypatch)
    _corre(catalogo_do_pos(_={}))

    limites = [chamada[1] for chamada in registo if chamada[0] == "to_list"]
    assert limites == [200, 2000, 200]


# --- GET /pos/tipos-pagamento --------------------------------------------------


def test_tipos_pagamento_devolve_so_activos_por_ordem(monkeypatch):
    _monta(
        monkeypatch,
        tipos_pagamento=[
            _tipo(id="tipo-mb", nome="Multibanco", tipo_fiscal="CD", da_troco=False, ordem=2),
            _tipo(id="tipo-dinheiro", nome="Dinheiro", ordem=1),
            _tipo(id="tipo-cheque", nome="Cheque", tipo_fiscal="CH", ordem=3, ativo=False),
        ],
    )

    tipos = _corre(tipos_pagamento_do_pos(_={}))

    assert [t["id"] for t in tipos] == ["tipo-dinheiro", "tipo-mb"]
    assert [t["da_troco"] for t in tipos] == [True, False]
    assert [t["tipo_fiscal"] for t in tipos] == ["NU", "CD"]


def test_pronto_diz_se_o_tipo_esta_mapeado_ao_vendus(monkeypatch):
    """`fiscal.py::finalizar` recusa com 422 um tipo sem
    `vendus_payment_method_id`. Sem este sinalizador, a operadora escolhia
    "Glovo", carregava em EMITIR à frente do cliente, e só aí descobria."""
    _monta(
        monkeypatch,
        tipos_pagamento=[
            _tipo(id="tipo-dinheiro", nome="Dinheiro", ordem=1),
            _tipo(id="tipo-glovo", nome="Glovo", tipo_fiscal="TB", da_troco=False, ordem=2,
                  vendus_payment_method_id=None),
            _tipo(id="tipo-bolt", nome="Bolt", tipo_fiscal="TB", da_troco=False, ordem=3,
                  vendus_payment_method_id=""),
        ],
    )

    prontos = {t["id"]: t["pronto"] for t in _corre(tipos_pagamento_do_pos(_={}))}

    assert prontos == {"tipo-dinheiro": True, "tipo-glovo": False, "tipo-bolt": False}


def test_tipo_por_mapear_continua_na_lista(monkeypatch):
    """Mesmo raciocínio do produto sem IVA: o botão fica lá, inutilizável e
    explicado. Escondê-lo dava uma lista de pagamentos onde "falta o Glovo"
    sem ninguém saber porquê."""
    _monta(
        monkeypatch,
        tipos_pagamento=[_tipo(id="tipo-glovo", nome="Glovo", tipo_fiscal="TB",
                               vendus_payment_method_id=None)],
    )

    tipos = _corre(tipos_pagamento_do_pos(_={}))

    assert [t["id"] for t in tipos] == ["tipo-glovo"]
    assert tipos[0]["pronto"] is False


def test_vendus_payment_method_id_nunca_sai_na_resposta(monkeypatch):
    """O teste que protege o segredo: o id do método de pagamento no Vendus
    é configuração interna da ligação e o ecrã do balcão não tem nada que a
    ver. Só o booleano `pronto` sai daqui — e nenhum outro campo do
    documento, `_id` e `protegido` incluídos."""
    _monta(monkeypatch, tipos_pagamento=[_tipo(vendus_payment_method_id="316430468")])

    tipos = _corre(tipos_pagamento_do_pos(_={}))

    assert tipos == [{
        "id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU",
        "da_troco": True, "ordem": 0, "pronto": True,
    }]
    assert "316430468" not in str(tipos)


# --- Protecção das rotas -------------------------------------------------------


def test_as_duas_rotas_exigem_o_token_de_operador():
    """São rotas de LEITURA, mas do POS: dependem de `operador_atual` (o
    X-Operator-Token), nunca do JWT de gestão — que o balcão, por desenho,
    nunca tem. Sem a dependência, qualquer pessoa lia o catálogo e a lista
    de pagamentos sem se identificar."""
    por_caminho = {rota.path: rota for rota in router.routes}

    for caminho in ("/pos/catalogo", "/pos/tipos-pagamento"):
        dependencias = {d.call for d in por_caminho[caminho].dependant.dependencies}
        assert operador_atual in dependencias, caminho


def test_sem_cabecalho_de_operador_e_recusado_401():
    """O outro elo da corrente do teste acima: é `operador_atual` que
    devolve o 401 quando o X-Operator-Token não vem no pedido."""
    with pytest.raises(HTTPException) as excinfo:
        _corre(operador_atual(x_operator_token=None))
    assert excinfo.value.status_code == 401
