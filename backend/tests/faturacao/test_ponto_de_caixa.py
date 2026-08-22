"""O Ponto de Caixa — a conferência a meio do turno, sem fechar nada.

A operadora quer saber se a gaveta bate certo às 15h, em vez de descobrir às
23h que houve um erro de troco que já não consegue reconstituir. E serve a
rendição de turno: uma sai, outra entra, sem fechar a caixa.

Duas coisas é que estes testes existem para provar, e nenhuma delas se
prova a ler o código:

1. **Não escreve nada.** Uma conferência que carimbasse a sessão, marcasse
   `a_fechar` ou confirmasse um movimento seria um fecho disfarçado — e a
   meio da tarde, com o balcão cheio.
2. **Dá exactamente os mesmos números que o Z.** Se o `esperado` das 15h e o
   das 23h saíssem de dois cálculos diferentes, este ecrã era pior do que
   não existir: mandava a operadora procurar uma diferença que não existe,
   ou calar uma que existe.

Mesmo padrão de duplo de base de dados de test_caixa_endpoints.py:
find()/find_one() filtram de facto, e o que se lê é sempre uma cópia funda
(um duplo que devolvesse o próprio objecto guardado deixa um teste passar
por aliasing).
"""
import re
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao.caixa import PedidoFecharCaixa, fechar_caixa, ponto_de_caixa
from faturacao.db import COLECOES

ACAI = "INT"     # 13 % — os açaís
REFRI = "NOR"    # 23 % — refrigerantes, brigadeiros, embalagem, entrega


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ----------------------------------------------------


def _corresponde(item, filtro):
    if not filtro:
        return True
    for chave, valor in filtro.items():
        if isinstance(valor, dict) and "$ne" in valor:
            if item.get(chave) == valor["$ne"]:
                return False
        # `$regex`, ancorado — é por ele que o travão do fecho pergunta pelas
        # RESERVAS desta sessão (`caixa._venda_com_emissao_viva`), pelo prefixo
        # `pos-{loja}-{sessão}-` da `ext_ref`. Um duplo que o ignorasse tratava
        # o dicionário como um valor a comparar, não casava com reserva
        # nenhuma, e o travão ficava verde sem nunca travar.
        elif isinstance(valor, dict) and "$regex" in valor:
            if not re.search(valor["$regex"], str(item.get(chave) or "")):
                return False
        elif item.get(chave) != valor:
            return False
    return True


class CursorFalso:
    def __init__(self, itens):
        self._itens = itens

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, n=None):
        return self._itens


class ResultadoUpdateFalso:
    def __init__(self, matched_count):
        self.matched_count = matched_count
        self.modified_count = matched_count


class ColeccaoFalsa:
    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", filtro))
        return CursorFalso(
            [deepcopy(d) for d in self._documentos if _corresponde(d, filtro)]
        )

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return deepcopy(encontrados[0]) if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._documentos.append(deepcopy(doc))

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
            for campo, valor in (atualizacao.get("$push") or {}).items():
                alvos[0].setdefault(campo, []).append(deepcopy(valor))
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def update_many(self, filtro, atualizacao):
        self.registo.append(("update_many", filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        for alvo in alvos:
            alvo.update(atualizacao.get("$set", {}))
            for campo in atualizacao.get("$unset", {}):
                alvo.pop(campo, None)
        return ResultadoUpdateFalso(matched_count=len(alvos))


class DbFalsa:
    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoFalsa([]))


def _db(registo, caixas=None, sessoes=None, movimentos=None, vendas=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, sessoes),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa(registo, movimentos),
        COLECOES["vendas"]: ColeccaoFalsa(registo, vendas),
    })


# --- Dados ---------------------------------------------------------------------


def _operador(**over):
    o = {"operador_id": "op-1", "nome": "Rafaela", "perfil": "operador_caixa", "loja_id": "loja-1"}
    o.update(over)
    return o


def _caixa(**over):
    c = {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão", "ativa": True}
    c.update(over)
    return c


def _sessao(**over):
    s = {
        "id": "sessao-1", "caixa_id": "caixa-1", "loja_id": "loja-1",
        "aberta_por": {"id": "op-1", "nome": "Rafaela"},
        "aberta_em": "2026-08-15T09:00:00+00:00",
        "fundo": 50.0, "estado": "aberta", "fechada_por": None, "fechada_em": None,
        "contado": None, "esperado": None, "diferenca": None,
    }
    s.update(over)
    return s


def _pagamento(**over):
    p = {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 8.99}
    p.update(over)
    return p


def _linha(nome, preco, tax_id, quantidade=1, **extra):
    linha = {
        "id": "linha-%s" % nome, "produto_nome": nome, "produto_preco": preco,
        "produto_tax_id": tax_id, "quantidade": quantidade,
    }
    linha.update(extra)
    return linha


def _venda(id_, linhas, pagamentos, **over):
    v = {
        "id": id_, "loja_id": "loja-1", "caixa_id": "caixa-1", "sessao_id": "sessao-1",
        "estado": "emitida", "linhas": linhas, "pagamentos": pagamentos,
        "desconto_global_pct": None, "desconto_global_eur": None,
    }
    v.update(over)
    return v


def _turno():
    """Um turno com as duas taxas misturadas, descontos por linha e desconto
    global, e três tipos de pagamento. Valores que EXPÕEM o cêntimo:
    0,29 · 1,15 · 10,20."""
    return [
        # 10,20 (13 %) + 1,15 (23 %) = 11,35, tudo em dinheiro.
        _venda(
            "v1",
            [_linha("Açaí XL", 10.20, ACAI), _linha("Coca-Cola", 1.15, REFRI)],
            [_pagamento(valor=11.35)],
        ),
        # 0,29 × 3 (23 %) + 10,20 (13 %) = 11,07, com 12,5 % de desconto
        # global -> 9,69. Metade em dinheiro, metade em multibanco.
        _venda(
            "v2",
            [_linha("Brigadeiro", 0.29, REFRI, quantidade=3), _linha("Açaí XL", 10.20, ACAI)],
            [
                _pagamento(valor=4.69),
                _pagamento(tipo_pagamento_id="tipo-mb", nome="Multibanco",
                           tipo_fiscal="CD", valor=5.00),
            ],
            desconto_global_pct=12.5,
        ),
        # 1,15 (23 %) só, pelo Glovo.
        _venda(
            "v3",
            [_linha("Entrega", 1.15, REFRI)],
            [_pagamento(tipo_pagamento_id="tipo-glovo", nome="Glovo",
                        tipo_fiscal="OU", valor=1.15)],
        ),
    ]


def _movimentos():
    return [
        {"id": "m1", "sessao_id": "sessao-1", "tipo": "entrada", "valor": 20.0},
        {"id": "m2", "sessao_id": "sessao-1", "tipo": "saida", "valor": 5.0},
    ]


# --- Não fecha nada ------------------------------------------------------------


def test_o_ponto_de_caixa_nao_escreve_uma_unica_vez(monkeypatch):
    """A garantia central deste ecrã: é conferência, não é fecho. Nenhum
    insert, nenhum update, nenhum delete — nem a marca `a_fechar` (que
    travaria as emissões enquanto a operadora confere), nem um carimbo na
    sessão."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             movimentos=_movimentos(), vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))

    escritas = [op for op in registo if op[0] not in ("find", "find_one")]
    assert escritas == []


def test_o_ponto_de_caixa_deixa_a_sessao_aberta_e_intacta(monkeypatch):
    registo = []
    sessao = _sessao()
    antes = deepcopy(sessao)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao],
             movimentos=_movimentos(), vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))

    assert sessao == antes


# --- Os mesmos números do Z ----------------------------------------------------


def test_o_ponto_de_caixa_e_o_z_dao_os_mesmos_numeros(monkeypatch):
    """A razão de ser da função partilhada. O Ponto de Caixa é o Z sem o
    fecho: o mesmo esperado, os mesmos movimentos, o mesmo desdobramento por
    tipo de pagamento e o mesmo mapa de imposto.

    Duas somas independentes que "têm de concordar" acabam sempre por
    discordar — neste módulo já aconteceu três vezes — e aqui a discordância
    mandava a operadora procurar uma diferença que não existe."""
    registo = []
    sessao = _sessao()
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao],
             movimentos=_movimentos(), vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))
    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=ponto["esperado"]),
        operador=_operador(),
    ))

    for campo in ("fundo", "vendas_dinheiro", "entradas", "saidas", "esperado",
                  "pagamentos", "mapa_imposto", "base_tributavel", "iva_total",
                  "total_faturado", "quantos_documentos"):
        assert ponto[campo] == z[campo], campo
    # E o Z confirma que o esperado que o Ponto de Caixa mostrou era mesmo o
    # que estava na gaveta.
    assert z["diferenca"] == 0.0


# --- O montante que devia estar na gaveta --------------------------------------


def test_o_esperado_soma_fundo_vendas_em_dinheiro_e_movimentos(monkeypatch):
    """50,00 de fundo + 11,35 + 4,69 em dinheiro + 20,00 de entrada
    - 5,00 de saída = 81,04. O multibanco e o Glovo não entram na gaveta."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)],
             movimentos=_movimentos(), vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))

    assert ponto["fundo"] == 50.0
    assert ponto["vendas_dinheiro"] == 16.04
    assert ponto["entradas"] == 20.0
    assert ponto["saidas"] == 5.0
    assert ponto["esperado"] == 81.04


def test_movimento_que_ficou_por_confirmar_nao_conta_para_o_esperado(monkeypatch):
    """Um movimento inserido mas nunca confirmado é dinheiro que ninguém
    tirou da gaveta — quem o pediu levou 409 ou nem chegou a receber
    resposta. O Z já o excluía; a conferência tem de o excluir pela MESMA
    regra, senão os dois ecrãs discordam."""
    registo = []
    movimentos = [
        {"id": "m1", "sessao_id": "sessao-1", "tipo": "entrada", "valor": 20.0},
        {"id": "m2", "sessao_id": "sessao-1", "tipo": "saida", "valor": 5.0,
         "por_confirmar": True},
    ]
    sessao = _sessao(fundo=50.0, movimentos_confirmados=["m1"])
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=movimentos, vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))

    assert ponto["saidas"] == 0.0
    assert ponto["esperado"] == 70.0


# --- Por tipo de pagamento -----------------------------------------------------


def test_o_desdobramento_por_tipo_de_pagamento(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             movimentos=[], vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))

    por_nome = {linha["nome"]: linha for linha in ponto["pagamentos"]}
    assert por_nome["Dinheiro"]["total"] == 16.04
    assert por_nome["Dinheiro"]["quantos"] == 2
    assert por_nome["Multibanco"]["total"] == 5.00
    assert por_nome["Glovo"]["total"] == 1.15
    # A ordem é por total decrescente — o que mais entrou primeiro.
    assert [linha["nome"] for linha in ponto["pagamentos"]] == [
        "Dinheiro", "Multibanco", "Glovo"
    ]


def test_o_dinheiro_do_desdobramento_e_o_mesmo_das_vendas_em_dinheiro(monkeypatch):
    """A linha "Dinheiro" da tabela e o "Vendas em dinheiro" que está por
    cima dela aparecem na MESMA janela. Se discordassem, ninguém ao balcão
    sabia qual das duas acreditar."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             movimentos=[], vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))

    em_dinheiro = sum(
        linha["total"] for linha in ponto["pagamentos"] if linha["tipo_fiscal"] == "NU"
    )
    assert round(em_dinheiro, 2) == ponto["vendas_dinheiro"]


# --- Mapa de imposto -----------------------------------------------------------


def test_o_mapa_de_imposto_fecha_com_o_total_faturado_do_turno(monkeypatch):
    """A prova ao cêntimo, agora pela rota real e com o desconto global no
    meio: a soma das bases mais a soma dos IVAs por taxa tem de dar
    exactamente o total dos documentos da sessão — e esse total tem de ser
    o que os clientes pagaram."""
    registo = []
    vendas = _turno()
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], movimentos=[], vendas=vendas)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))
    mapa = ponto["mapa_imposto"]

    bases_mais_ivas = round(
        sum(linha["base"] for linha in mapa) + sum(linha["iva"] for linha in mapa), 2
    )
    pago_pelos_clientes = round(
        sum(p["valor"] for v in vendas for p in v["pagamentos"]), 2
    )
    assert bases_mais_ivas == ponto["total_faturado"]
    assert ponto["total_faturado"] == pago_pelos_clientes


def test_o_mapa_de_imposto_separa_as_duas_taxas_e_conta_documentos(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             movimentos=[], vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))
    por_taxa = {linha["taxa"]: linha for linha in ponto["mapa_imposto"]}

    assert sorted(por_taxa) == [13, 23]
    # Os açaís estão em v1 e v2; os artigos a 23 % em v1, v2 e v3.
    assert por_taxa[13]["documentos"] == 2
    assert por_taxa[23]["documentos"] == 3
    assert ponto["quantos_documentos"] == 3
    for linha in ponto["mapa_imposto"]:
        assert round(linha["base"] + linha["iva"], 2) == linha["total"]


def test_uma_conta_ainda_aberta_nao_entra_no_mapa_nem_nos_pagamentos(monkeypatch):
    """A conta que está a ser feita neste instante não é documento nenhum e
    não entrou na gaveta — a conferência a meio do turno é precisamente o
    momento em que há sempre uma."""
    registo = []
    vendas = _turno() + [
        _venda("v4", [_linha("Açaí XL", 10.20, ACAI)], [], estado="aberta")
    ]
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], movimentos=[], vendas=vendas)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))

    assert ponto["quantos_documentos"] == 3
    assert ponto["total_faturado"] == round(
        sum(p["valor"] for v in _turno() for p in v["pagamentos"]), 2
    )


# --- Recusas -------------------------------------------------------------------


def test_sem_sessao_aberta_o_ponto_de_caixa_e_recusado(monkeypatch):
    """Não há turno nenhum para conferir — e responder com zeros era pior:
    lia-se como "a gaveta está a zero"."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(estado="fechada")], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as erro:
        _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))
    assert erro.value.status_code == 409


def test_caixa_de_outra_loja_nao_se_confere(monkeypatch):
    """O âmbito nunca é só o id: uma caixa de outra loja não se lê, mesmo
    por acidente."""
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")], sessoes=[_sessao()], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as erro:
        _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))
    assert erro.value.status_code == 404


def test_a_sessao_que_ficou_a_meio_de_um_fecho_ainda_se_confere(monkeypatch):
    """Uma sessão em `a_fechar` (um fecho que morreu a meio) continua por
    fechar, e é exactamente aí que alguém precisa de ver os números antes de
    tentar outra vez."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(estado="a_fechar")],
             movimentos=_movimentos(), vendas=_turno())
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    ponto = _corre(ponto_de_caixa(caixa_id="caixa-1", operador=_operador()))
    assert ponto["esperado"] == 81.04
