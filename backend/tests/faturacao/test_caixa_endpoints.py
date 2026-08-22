"""Sessão de caixa do POS: abrir e registar movimentos (Task 3 do Plano 2A).

Mesmo padrão de duplo de base de dados que test_pos_auth.py: find()/find_one()
filtram de facto pelos campos do filtro, para que "caixa já aberta" e "sem
sessão aberta" provem comportamento real, e não apenas confiem que o Mongo
filtraria por nós. Nenhum teste liga a uma base de dados nem à rede.
"""
import re
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import caixa as caixa_mod
from faturacao.caixa import (
    PedidoAbrirCaixa,
    PedidoFecharCaixa,
    PedidoMovimento,
    _porque_o_movimento_nao_entrou,
    _sessao_publica,
    abrir_caixa,
    estado_caixa,
    fechar_caixa,
    registar_movimento,
)
from faturacao.db import COLECOES
from faturacao.fiscal import ext_ref_determinista


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ----------------------------------------------------


def _corresponde(item, filtro):
    """Réplica minimalista do casamento de filtro do Mongo: igualdade exacta
    em cada campo pedido, mais o `$ne`.

    O `$ne` é por onde o travão do fecho pergunta pelas contas que ainda NÃO
    estão `emitida` (`caixa._venda_com_emissao_viva`). Um duplo que o
    ignorasse tratava `{"$ne": "emitida"}` como um valor a comparar, não
    casava com venda nenhuma, e os testes do fecho deste ficheiro ficavam
    verdes a medir uma sessão sem contas."""
    if not filtro:
        return True
    for chave, valor in filtro.items():
        # `$or` e `$nin` — ver o mesmo ramo em test_venda.py. É por eles que
        # `por_resolver.contas_por_resolver` pergunta pelas RESERVAS de várias
        # sessões de uma vez e pelas vendas em estado NÃO TERMINAL. Um duplo
        # que os ignorasse tratava "$or" como um campo do documento (nenhuma
        # reserva casava) e `$nin` como um valor a comparar (casava com tudo,
        # `emitida` incluída) — metade do predicado ficava verde sem correr.
        if chave == "$or":
            if not any(_corresponde(item, sub) for sub in valor):
                return False
        elif isinstance(valor, dict) and "$nin" in valor:
            if item.get(chave) in valor["$nin"]:
                return False
        elif isinstance(valor, dict) and "$in" in valor:
            if item.get(chave) not in valor["$in"]:
                return False
        elif isinstance(valor, dict) and "$ne" in valor:
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


def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find_one` real descodifica BSON de fresco a cada chamada: o resultado
    NUNCA está ligado ao que está no Mongo. Um duplo que devolvesse o próprio
    objecto guardado deixa um teste passar por ALIASING — o código de produção
    muta o que "leu", o Mongo falso muda sozinho, e a asserção fica verde sem
    que nenhuma escrita tenha acontecido. Já apanhou um caso real neste
    módulo: apagar o `venda.update(atualizacao)` de `cancelar_venda`
    (faturacao/venda.py) não punha um único teste vermelho, apesar de a rota
    passar a responder `estado: "aberta"` depois de cancelar.

    Cópia FUNDA, não `dict(d)`: aqui as vendas trazem `pagamentos` (que o
    fecho soma em `caixa_math.soma_vendas_dinheiro`) e as sessões trazem
    `aberta_por` — uma cópia rasa partilhava essas listas e dicionários com o
    documento guardado, e o aliasing voltava uma camada abaixo, onde é ainda
    mais difícil de ver.
    """
    return deepcopy(documento)


class CursorFalso:
    def __init__(self, itens):
        self._itens = itens

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, n=None):
        return self._itens


class ResultadoUpdateFalso:
    """Réplica minimalista do UpdateResult do pymongo/motor — só os dois
    campos de que caixa.py precisa (I2) para saber se a escrita CONDICIONAL
    (`{"id": ..., "estado": "aberta"}`) encontrou mesmo alguma coisa, em vez
    de aplicar $set às cegas a "o que quer que tenha calhado casar"."""

    def __init__(self, matched_count):
        self.matched_count = matched_count
        self.modified_count = matched_count


class ResultadoDeleteFalso:
    """O DeleteResult do pymongo/motor, reduzido ao que é preciso aqui: o
    `deleted_count` que `fiscal.py::_libertar_reserva_se_intacta` lê."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: find()/find_one() filtram de facto."""

    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", filtro))
        return CursorFalso(
            [_como_o_motor(d) for d in self._documentos if _corresponde(d, filtro)]
        )

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return _como_o_motor(encontrados[0]) if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._documentos.append(deepcopy(doc))
        return None

    async def update_many(self, filtro, atualizacao):
        """`$set`/`$unset` em TODAS as que casam — hoje só o `$unset` da
        etiqueta do posto, que o fecho de caixa faz às contas que deixa
        abertas (`caixa._largar_o_posto_das_contas_abertas`). Sem isto o duplo
        levantava `AttributeError`, o `except` de lá engolia-o e o teste ficava
        verde a medir o contrário do que diz."""
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        for alvo in alvos:
            alvo.update(atualizacao.get("$set", {}))
            for campo in atualizacao.get("$unset", {}):
                alvo.pop(campo, None)
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
            # `$push` — a confirmação de um movimento empurra o `id` dele para
            # `movimentos_confirmados` da sessão NA MESMA escrita em que exige
            # `estado: "aberta"`. Tem de ser $push e não um $set de uma lista
            # relida: duas confirmações ao mesmo tempo perdiam uma delas, e uma
            # confirmação perdida é dinheiro fora do Z (ver
            # `caixa.py::registar_movimento`).
            for campo, valor in (atualizacao.get("$push") or {}).items():
                alvos[0].setdefault(campo, []).append(deepcopy(valor))
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def delete_one(self, filtro):
        """Só o primeiro que casa, como o Mongo — e devolve `deleted_count`,
        que é por onde `fiscal.py` decide se ganhou a corrida da libertação
        da reserva. Existe aqui porque a secção da janela do fecho confirma,
        contra o núcleo fiscal a sério, que uma sessão `a_fechar` faz a
        emissão libertar a reserva e abortar."""
        self.registo.append(("delete_one", filtro))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            self._documentos.remove(alvos[0])
        return ResultadoDeleteFalso(deleted_count=1 if alvos else 0)


class DbFalsa:
    """Duplo de db com várias colecções — caixas, sessões e movimentos têm
    estados independentes na mesma chamada a obter_db()."""

    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoFalsa([]))


def _db(registo, caixas=None, sessoes=None, movimentos=None, vendas=None, tipos_pagamento=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, sessoes),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa(registo, movimentos),
        COLECOES["vendas"]: ColeccaoFalsa(registo, vendas),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa(registo, tipos_pagamento),
    })


def _pagamento(**over):
    p = {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 8.99}
    p.update(over)
    return p


def _venda_emitida(**over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "sessao_id": "sessao-1", "estado": "emitida",
        "pagamentos": [_pagamento()],
    }
    v.update(over)
    return v


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
        "aberta_por": {"id": "op-1", "nome": "Rafaela"}, "aberta_em": "2026-08-15T09:00:00+00:00",
        "fundo": 50.0, "estado": "aberta", "fechada_por": None, "fechada_em": None,
        "contado": None, "esperado": None, "diferenca": None,
    }
    s.update(over)
    return s


# --- Estado da caixa (o que o ecrã de entrada na app precisa) ------------------


def test_estado_caixa_sem_nenhuma_caixa_configurada_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(estado_caixa(caixa_id=None, operador=_operador()))
    assert excinfo.value.status_code == 404


def test_estado_caixa_ignora_caixas_inactivas_de_outras_lojas(monkeypatch):
    registo = []
    db = _db(registo, caixas=[
        _caixa(id="caixa-inactiva", ativa=False),
        _caixa(id="caixa-outra-loja", loja_id="loja-2"),
    ])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(estado_caixa(caixa_id=None, operador=_operador()))
    assert excinfo.value.status_code == 404


def test_estado_caixa_com_uma_so_caixa_activa_resolve_sozinho_sem_sessao(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(estado_caixa(caixa_id=None, operador=_operador()))
    assert resultado["caixa"]["id"] == "caixa-1"
    assert resultado["sessao_aberta"] is None
    assert resultado["ultimo_fecho"] is None


def test_estado_caixa_com_uma_so_caixa_activa_traz_a_sessao_aberta(monkeypatch):
    registo = []
    sessao = _sessao()
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(estado_caixa(caixa_id=None, operador=_operador()))
    assert resultado["caixa"]["id"] == "caixa-1"
    assert resultado["sessao_aberta"]["id"] == "sessao-1"
    assert resultado["ultimo_fecho"] is None


def test_estado_caixa_sem_sessao_aberta_traz_o_resumo_do_ultimo_fecho(monkeypatch):
    """É o que preenche "Em 12/08 às 18:56 · Por Rafaela · Montante: € 87,58"
    no ecrã "Caixa Fechada" (Task 2)."""
    registo = []
    fechada = _sessao(
        estado="fechada",
        fechada_por={"id": "op-1", "nome": "Rafaela Prates"},
        fechada_em="2026-08-12T18:56:00+00:00",
        contado=87.58,
    )
    db = _db(registo, caixas=[_caixa()], sessoes=[fechada])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(estado_caixa(caixa_id=None, operador=_operador()))
    assert resultado["sessao_aberta"] is None
    assert resultado["ultimo_fecho"]["fechada_por"] == {"id": "op-1", "nome": "Rafaela Prates"}
    assert resultado["ultimo_fecho"]["contado"] == 87.58


def test_estado_caixa_com_mais_do_que_uma_ativa_devolve_a_lista_sem_escolher(monkeypatch):
    """Nunca escolhe pela funcionária — o mesmo raciocínio do PIN em
    conflito (409 em /pos/entrar): mais do que uma correspondência é
    ambiguidade explícita, nunca a primeira ao acaso."""
    registo = []
    db = _db(registo, caixas=[
        _caixa(id="caixa-1", nome="Balcão"),
        _caixa(id="caixa-2", nome="Drive-Thru"),
    ])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(estado_caixa(caixa_id=None, operador=_operador()))
    assert resultado["caixa"] is None
    assert {c["id"] for c in resultado["caixas"]} == {"caixa-1", "caixa-2"}


def test_estado_caixa_com_caixa_id_explicito_resolve_essa(monkeypatch):
    registo = []
    db = _db(registo, caixas=[
        _caixa(id="caixa-1", nome="Balcão"),
        _caixa(id="caixa-2", nome="Drive-Thru"),
    ], sessoes=[_sessao(caixa_id="caixa-2")])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(estado_caixa(caixa_id="caixa-2", operador=_operador()))
    assert resultado["caixa"]["id"] == "caixa-2"
    assert resultado["sessao_aberta"]["caixa_id"] == "caixa-2"


def test_estado_caixa_com_caixa_id_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa(id="caixa-2", loja_id="loja-2")])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(estado_caixa(caixa_id="caixa-2", operador=_operador()))
    assert excinfo.value.status_code == 404


# --- Abrir caixa -----------------------------------------------------------------


def test_abrir_caixa_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.0), operador=_operador())
    )
    assert resultado["estado"] == "aberta"
    assert resultado["fundo"] == 50.0
    assert resultado["caixa_id"] == "caixa-1"
    assert resultado["loja_id"] == "loja-1"
    assert resultado["aberta_por"] == {"id": "op-1", "nome": "Rafaela"}


def test_abrir_caixa_ja_aberta_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.0), operador=_operador()))
    assert excinfo.value.status_code == 409
    # Não deve ter tentado gravar uma segunda sessão.
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_abrir_caixa_inexistente_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_caixa(PedidoAbrirCaixa(caixa_id="nao-existe", fundo=50.0), operador=_operador()))
    assert excinfo.value.status_code == 404


def test_abrir_caixa_de_outra_loja_e_recusado_404(monkeypatch):
    """Uma caixa de outra loja não pode ser aberta por um operador desta loja
    — mesmo que o id exista, o âmbito é sempre o da loja do operador."""
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.0), operador=_operador()))
    assert excinfo.value.status_code == 404


def test_abrir_caixa_com_fundo_negativo_e_recusado():
    with pytest.raises(ValidationError):
        PedidoAbrirCaixa(caixa_id="caixa-1", fundo=-10.0)


def test_abrir_caixa_com_fundo_com_3_casas_e_recusado():
    with pytest.raises(ValidationError):
        PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.995)


def test_abrir_caixa_com_fundo_zero_e_aceite(monkeypatch):
    """Zero é um fundo legítimo (loja que ainda não recebeu o troco do dia) —
    o que não pode é ser negativo."""
    registo = []
    db = _db(registo, caixas=[_caixa()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=0.0), operador=_operador())
    )
    assert resultado["fundo"] == 0.0


# --- Movimentos --------------------------------------------------------------------


def test_movimento_de_entrada_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
    ))
    assert resultado["sessao_id"] == "sessao-1"
    assert resultado["tipo"] == "entrada"
    assert resultado["valor"] == 20.0
    assert resultado["por"] == {"id": "op-1", "nome": "Rafaela"}


def test_movimento_de_saida_sem_motivo_e_recusado():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=10.0)


def test_movimento_de_saida_com_motivo_vazio_e_recusado():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=10.0, motivo="   ")


def test_movimento_de_saida_com_motivo_passa(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=10.0, motivo="Troco ao banco"),
        operador=_operador(),
    ))
    assert resultado["motivo"] == "Troco ao banco"


def test_movimento_de_entrada_nao_exige_motivo(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
    ))
    assert resultado["motivo"] is None


def test_movimento_com_valor_negativo_e_recusado_422():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=-5.0)


def test_movimento_com_valor_zero_e_recusado_422():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=0)


def test_movimento_com_valor_de_3_casas_e_recusado():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.995)


def test_movimento_sem_sessao_aberta_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(registar_movimento(
            PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
        ))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_movimento_em_caixa_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")], sessoes=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(registar_movimento(
            PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
        ))
    assert excinfo.value.status_code == 404


def test_movimento_ignora_sessao_id_vindo_do_corpo_mesmo_que_apareca(monkeypatch):
    """A regra central da tarefa: a sessão é resolvida no servidor a partir
    da caixa + operador, nunca de um sessao_id que venha no pedido — senão
    qualquer um lançava movimentos na sessão de outra loja. Simula um corpo
    desactualizado/malicioso que ainda traz sessao_id e confirma que é
    ignorado por completo: o modelo nem sequer declara esse campo, por isso
    o movimento tem sempre de ficar preso à sessão aberta da PRÓPRIA caixa
    pedida, nunca à sessão "sugerida" no pedido.

    Mutação verificada manualmente (ver relatório da tarefa): se
    PedidoMovimento ganhasse um campo `sessao_id` e o endpoint passasse a
    confiar nele em vez de resolver sempre pela caixa, este teste fica
    vermelho."""
    registo = []
    sessao_amiga = _sessao(id="sessao-amiga", caixa_id="caixa-1", loja_id="loja-1")
    sessao_estranha = _sessao(id="sessao-estranha", caixa_id="caixa-2", loja_id="loja-2")
    db = _db(
        registo,
        caixas=[_caixa(id="caixa-1", loja_id="loja-1"), _caixa(id="caixa-2", loja_id="loja-2")],
        sessoes=[sessao_amiga, sessao_estranha],
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    dados = PedidoMovimento.model_validate({
        "caixa_id": "caixa-1", "tipo": "entrada", "valor": 10.0,
        "sessao_id": "sessao-estranha",
    })
    resultado = _corre(registar_movimento(dados, operador=_operador()))
    assert resultado["sessao_id"] == "sessao-amiga"


# --- Fecho de caixa e relatório Z (Task 4 do Plano 2A) --------------------------
#
# O esperado calcula-se das NOSSAS vendas, não do Vendus (regra 1) — os
# testes desta secção não passam nenhuma venda, por isso vendas_dinheiro
# continua honestamente 0.0 (soma_vendas_dinheiro de uma lista vazia). A
# ligação real às vendas está na secção seguinte (Task 4 do Plano 2B).


def test_fecho_com_diferenca_zero_quando_conta_bate_certo(monkeypatch):
    registo = []
    sessao = _sessao(fundo=50.0)
    movimentos = [
        {"id": "m1", "sessao_id": "sessao-1", "tipo": "entrada", "valor": 20.0},
        {"id": "m2", "sessao_id": "sessao-1", "tipo": "saida", "valor": 5.0},
    ]
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=movimentos)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    # esperado = 50 (fundo) + 0 (vendas) + 20 (entrada) - 5 (saída) = 65
    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=65.0), operador=_operador())
    )
    assert resultado["esperado"] == 65.0
    assert resultado["contado"] == 65.0
    assert resultado["diferenca"] == 0.0
    assert resultado["estado"] == "fechada"


def test_fecho_com_diferenca_positiva_quando_ha_sobra(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=55.0), operador=_operador())
    )
    assert resultado["esperado"] == 50.0
    assert resultado["diferenca"] == 5.0


def test_fecho_com_diferenca_negativa_quando_falta_dinheiro(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=42.5), operador=_operador())
    )
    assert resultado["esperado"] == 50.0
    assert resultado["diferenca"] == -7.5


def test_fecho_marca_a_sessao_como_fechada(monkeypatch):
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))
    assert sessao["estado"] == "fechada"
    assert sessao["fechada_por"] == {"id": "op-1", "nome": "Rafaela"}
    assert sessao["fechada_em"] is not None
    assert sessao["contado"] == 50.0
    assert sessao["esperado"] == 50.0
    assert sessao["diferenca"] == 0.0


def test_fechar_sessao_ja_fechada_e_recusado_409(monkeypatch):
    registo = []
    sessao_fechada = _sessao(estado="fechada")
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao_fechada], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(
            fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
        )
    assert excinfo.value.status_code == 409


def test_dois_fechos_concorrentes_o_segundo_e_recusado_409(monkeypatch):
    """I2, reproduzido: `update_one({"id": ...})` sem condição de estado
    deixava DOIS fechos em paralelo passarem os dois — a última contagem
    escrita "ganhava" sem nenhum aviso (uma respondeu 50€, a outra 30€,
    ficava só 30€ com diferenca=-20, e saíam dois Z diferentes que o
    backoffice contradiz o papel que a funcionária levou).

    Sem sleep points no duplo de base de dados deste ficheiro (ao contrário
    do de test_fiscal.py), simula-se a corrida real com um espião que fecha
    a sessão "por fora" — outro pedido de fecho, que já chegou primeiro —
    exactamente no instante em que ESTE pedido tentaria confirmar
    {"id": ..., "estado": "aberta"}. O primeiro fecho (que já tinha corrido
    a computação toda) não pode escrever por cima do segundo."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    colecao_sessoes = db[COLECOES["sessoes_caixa"]]
    update_original = colecao_sessoes.update_one

    async def fecha_por_fora_antes_de_escrever(filtro, atualizacao):
        # Simula: OUTRO pedido de fecho (a operadora do turno seguinte,
        # ou um duplo-toque) já fechou esta sessão mesmo antes de este
        # pedido conseguir escrever a sua própria contagem.
        sessao["estado"] = "fechada"
        sessao["contado"] = 30.0
        return await update_original(filtro, atualizacao)

    colecao_sessoes.update_one = fecha_por_fora_antes_de_escrever

    with pytest.raises(HTTPException) as excinfo:
        _corre(
            fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
        )
    assert excinfo.value.status_code == 409
    # A contagem do "outro" fecho (30€) não pode ter sido pisada pela deste
    # pedido (50€) — é exactamente essa pisadela que o índice condicional
    # evita.
    assert sessao["contado"] == 30.0


def test_movimento_com_sessao_fechada_entre_a_leitura_e_a_confirmacao_e_recusado_409(monkeypatch):
    """I2, "o mesmo raciocínio para um movimento a cruzar-se com o fecho":
    entre `_sessao_aberta` (a leitura inicial) e o registo do movimento,
    outro pedido fechou a sessão — sem uma confirmação atómica logo antes
    de gravar, o movimento entrava na gaveta depois de o Z já ter sido
    calculado, e nenhum fecho (nem o de hoje, já fechado, nem o de amanhã)
    o explica."""
    registo = []
    sessao = _sessao()
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    colecao_sessoes = db[COLECOES["sessoes_caixa"]]
    update_original = colecao_sessoes.update_one

    async def fecha_entre_a_leitura_e_a_confirmacao(filtro, atualizacao):
        sessao["estado"] = "fechada"
        return await update_original(filtro, atualizacao)

    colecao_sessoes.update_one = fecha_entre_a_leitura_e_a_confirmacao

    with pytest.raises(HTTPException) as excinfo:
        _corre(registar_movimento(
            PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
        ))
    assert excinfo.value.status_code == 409
    # A linha do movimento passou a entrar na colecção ANTES da confirmação
    # (é essa ordem que impede que ela apareça DEPOIS de um Z já assinado —
    # ver `caixa.py::registar_movimento`), por isso o que se exige aqui já não
    # é "não houve insert": é que este movimento não tenha chegado a ser
    # dinheiro — nem linha na colecção, nem `id` na lista da sessão, que é a
    # única coisa que o fecho conta.
    assert db[COLECOES["movimentos_caixa"]]._documentos == []
    assert sessao.get("movimentos_confirmados", []) == []


def test_fechar_caixa_sem_sessao_aberta_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(
            fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
        )
    assert excinfo.value.status_code == 409


def test_fechar_caixa_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")], sessoes=[], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(
            fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
        )
    assert excinfo.value.status_code == 404


def test_fechar_caixa_com_contado_negativo_e_recusado():
    with pytest.raises(ValidationError):
        PedidoFecharCaixa(caixa_id="caixa-1", contado=-5.0)


def test_fechar_caixa_com_contado_de_3_casas_e_recusado():
    with pytest.raises(ValidationError):
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.995)


def test_relatorio_z_inclui_todos_os_campos_pedidos(monkeypatch):
    """O Z tem de mostrar abertura (fundo), vendas em dinheiro, entradas,
    saídas, esperado, contado e diferença — o suficiente para a funcionária
    e o dono perceberem o dia inteiro sem adivinhar nada."""
    registo = []
    sessao = _sessao(fundo=100.0)
    movimentos = [
        {"id": "m1", "sessao_id": "sessao-1", "tipo": "entrada", "valor": 30.0},
        {"id": "m2", "sessao_id": "sessao-1", "tipo": "entrada", "valor": 10.0},
        {"id": "m3", "sessao_id": "sessao-1", "tipo": "saida", "valor": 15.0},
    ]
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=movimentos)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=130.0), operador=_operador())
    )

    assert resultado["fundo"] == 100.0
    assert resultado["vendas_dinheiro"] == 0.0
    assert resultado["entradas"] == 40.0
    assert resultado["saidas"] == 15.0
    assert resultado["esperado"] == 125.0
    assert resultado["contado"] == 130.0
    assert resultado["diferenca"] == 5.0
    assert resultado["aberta_por"] == {"id": "op-1", "nome": "Rafaela"}
    assert resultado["aberta_em"] is not None
    assert resultado["fechada_por"] == {"id": "op-1", "nome": "Rafaela"}
    assert resultado["fechada_em"] is not None


def test_relatorio_z_com_sessao_sem_movimentos(monkeypatch):
    """Listas vazias não podem rebentar o fecho — é o caso mais comum (uma
    caixa tranquila, sem entradas nem saídas no turno)."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
    )
    assert resultado["entradas"] == 0.0
    assert resultado["saidas"] == 0.0
    assert resultado["diferenca"] == 0.0


def test_fecho_nunca_bloqueia_mesmo_com_diferenca_grande(monkeypatch):
    """Mutação própria da Task 4 (pedida no brief, além das do plano): a
    funcionária tem de poder ir para casa mesmo que a conta não bata por
    muito. Este teste é o canário — se o fecho passar a recusar (levantar
    HTTPException) quando a diferença é grande, em vez de só a registar,
    fica vermelho. Confirmado manualmente com uma guarda de bloqueio
    acrescentada a fechar_caixa e revertida (ver relatório da tarefa)."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    # Devia haver 50€ na gaveta; a funcionária conta 3€. Uma diferença deste
    # tamanho não pode impedir o fecho — só ficar registada para o gestor ver.
    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=3.0), operador=_operador())
    )
    assert resultado["estado"] == "fechada"
    assert resultado["diferenca"] == -47.0


# --- A venda entra na caixa (Task 4 do Plano 2B) --------------------------------
#
# Uma venda paga em dinheiro conta para o esperado; uma venda em cartão não.
# A matemática em si (pagamento misto, vendas não emitidas) já está testada
# em test_caixa_math.py::soma_vendas_dinheiro — aqui só importa que
# fechar_caixa lê as vendas CERTAS (da sessão a fechar, nenhuma outra) e as
# entrega a essa função.


def test_fecho_soma_as_vendas_em_dinheiro_da_sessao(monkeypatch):
    registo = []
    db = _db(
        registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[],
        vendas=[_venda_emitida()],  # 8.99 em dinheiro
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99), operador=_operador())
    )
    assert resultado["vendas_dinheiro"] == 8.99
    assert resultado["esperado"] == 58.99
    assert resultado["diferenca"] == 0.0


def test_fecho_com_pagamento_misto_conta_so_a_parte_em_dinheiro(monkeypatch):
    registo = []
    venda_mista = _venda_emitida(pagamentos=[
        _pagamento(valor=10.0),
        _pagamento(tipo_pagamento_id="tipo-mb", nome="Multibanco", tipo_fiscal="CD", valor=7.98),
    ])
    db = _db(
        registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[],
        vendas=[venda_mista],
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=60.0), operador=_operador())
    )
    assert resultado["vendas_dinheiro"] == 10.0  # só a parte em dinheiro, não os 17.98 todos


def test_fecho_ignora_venda_de_outra_sessao(monkeypatch):
    registo = []
    venda_de_ontem = _venda_emitida(id="venda-ontem", sessao_id="sessao-ontem")
    db = _db(
        registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[],
        vendas=[venda_de_ontem],
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
    )
    assert resultado["vendas_dinheiro"] == 0.0


def test_fecho_ignora_venda_ainda_aberta(monkeypatch):
    """Uma venda no meio de uma conta (nunca chegou a emitir) não pode
    contar como dinheiro na gaveta."""
    registo = []
    venda_aberta = _venda_emitida(estado="aberta")
    db = _db(
        registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[],
        vendas=[venda_aberta],
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
    )
    assert resultado["vendas_dinheiro"] == 0.0


# --- Verificação de leitura contra o Vendus (prometida no Plano 2A) -------------
#
# Bate certo -> não diz nada. Não bate -> avisa, mas deixa fechar. Não
# conseguiu ler tudo -> diz que não conseguiu verificar. NUNCA bloqueia.


def test_fecho_sem_vendus_configurado_diz_que_nao_conseguiu_verificar(monkeypatch):
    """Sem VENDUS_REGISTER_ID/conta configurados (o caso normal nestes
    testes — nenhum env var de Vendus está definido), a verificação não
    pode fingir que bateu certo: diz claramente que não conseguiu, e o
    fecho segue em frente na mesma."""
    monkeypatch.delenv("VENDUS_REGISTER_ID", raising=False)
    monkeypatch.delenv("VENDUS_ACCOUNTS", raising=False)
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
    )
    assert resultado["estado"] == "fechada"  # nunca bloqueia
    assert resultado["verificacao_vendus"] is not None
    assert "nao_verificado" in resultado["verificacao_vendus"]


def test_fecho_com_verificacao_vendus_a_rebentar_no_meio_nao_bloqueia_o_fecho(monkeypatch):
    """Defesa extra (além da que já existe dentro da própria função de
    verificação): mesmo que a chamada a verificar_vendas_dinheiro_no_vendus
    levantasse uma excepção inesperada, o fecho em si nunca pode falhar por
    causa disto — regra 3 do dono."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)], movimentos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    async def rebenta(*args, **kwargs):
        raise RuntimeError("falha inesperada simulada")

    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", rebenta)

    resultado = _corre(
        fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador())
    )
    assert resultado["estado"] == "fechada"
    assert "nao_verificado" in resultado["verificacao_vendus"]


# --- O fecho recusa-se a fechar A MEIO DE UMA EMISSÃO --------------------------
#
# O fecho lia as vendas `emitida`, calculava o Z e fechava, sem perguntar mais
# nada. Dois PCs na mesma caixa (o "PC Balcão" e o "PC Drive-Thru", a
# configuração que `venda.venda_aberta` documenta como estado estável)
# chegavam a isto: às 23:58 a Rafaela carrega em FINALIZAR e o Vendus demora;
# a Ana, no outro PC, conta a gaveta e fecha. Medido:
# `FECHAR CAIXA -> 200; Z: vendas_dinheiro=0.00 esperado=50.00 contado=58.99
# diferenca=+8.99`, e logo a seguir a FS REAL de 8,99 € a sair para uma sessão
# já fechada. O Z assinado não tinha essa venda, os 8,99 € ficavam na gaveta
# como sobra por justificar, e a venda `emitida` não entrava em Z nenhum — nem
# neste nem no seguinte (que filtra pelo `sessao_id` da sessão nova).


def _venda_aberta(**over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
        "sessao_id": "sessao-1", "estado": "aberta", "linhas": [],
        "criada_em": "2026-08-18T23:50:00+00:00",
    }
    v.update(over)
    return v


def _reserva_fiscal(sessao_id="sessao-1", loja_id="loja-1", **over):
    """Uma reserva como `fiscal._reservar` a insere — e a `ext_ref` construída
    pela MESMA função da produção (`ext_ref_determinista`), nunca escrita à
    mão aqui.

    Passou a ter de ser assim: o travão do fecho pergunta pelas reservas DESTA
    sessão através do prefixo da `ext_ref`
    (`caixa._venda_com_emissao_viva`), e uma `ext_ref` escrita à mão com a
    sessão errada é um documento que a produção nunca poderia ter gravado — o
    teste ficava a medir uma base impossível."""
    venda_id = over.pop("venda_id", "venda-1")
    r = {
        "id": "ref-1",
        "ext_ref": ext_ref_determinista(loja_id, sessao_id, venda_id),
        "venda_id": venda_id, "criado_em": "2026-08-18T23:58:00+00:00",
    }
    r.update(over)
    return r


def _db_com_reservas(registo, vendas, refs, **over):
    argumentos = {"caixas": [_caixa()], "sessoes": [_sessao(fundo=50.0)],
                  "movimentos": [], "vendas": vendas}
    argumentos.update(over)
    db = _db(registo, **argumentos)
    db._coleccoes[COLECOES["refs_fiscais"]] = ColeccaoFalsa(registo, refs)
    return db


def test_fechar_caixa_com_emissao_em_curso_numa_venda_da_sessao_e_recusado(monkeypatch):
    """Fechar a caixa a meio de uma emissão é fechar as contas antes de o
    dinheiro estar contado. A sessão fica aberta e nenhum Z sai."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db_com_reservas(registo, [_venda_aberta()], [_reserva_fiscal()], sessoes=[sessao])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99),
                            operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "emissão de fatura em curso" in excinfo.value.detail
    # A mensagem tem de dizer o que fazer: esperar, e — se ficar presa — quem
    # a resolve e onde.
    assert "Espere" in excinfo.value.detail
    assert "reservas fiscais presas" in excinfo.value.detail
    assert sessao["estado"] == "aberta", "a caixa fechou a meio de uma emissão"
    assert sessao["fechada_em"] is None
    assert not any(
        chamada[0] == "update_one" for chamada in registo
    ), "escreveu no meio de uma recusa"


def test_fechar_caixa_ignora_a_reserva_de_uma_venda_ja_emitida(monkeypatch):
    """A reserva de uma venda `emitida` fica lá PARA SEMPRE de propósito (é
    ela que sustenta a idempotência) — se contasse, a caixa não fechava
    nenhuma noite."""
    registo = []
    db = _db_com_reservas(
        registo,
        [_venda_aberta(estado="emitida", pagamentos=[_pagamento()])],
        [_reserva_fiscal()],
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99), operador=_operador()))
    assert resultado["estado"] == "fechada"
    assert resultado["vendas_dinheiro"] == 8.99


def test_fechar_caixa_ignora_a_reserva_de_uma_venda_de_outra_sessao(monkeypatch):
    """A pergunta é pelas contas DESTA sessão: uma emissão a decorrer na
    caixa do lado não pode impedir esta de fechar."""
    registo = []
    db = _db_com_reservas(
        registo,
        [_venda_aberta(id="venda-9", sessao_id="sessao-outra")],
        [_reserva_fiscal(venda_id="venda-9", sessao_id="sessao-outra")],
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))
    assert resultado["estado"] == "fechada"


def test_fechar_caixa_com_conta_aberta_sem_reserva_nenhuma_fecha_na_mesma(monkeypatch):
    """Uma conta esquecida em aberto (sem emissão nenhuma) não trava o fecho —
    isso seria prender a funcionária na loja por causa de um ecrã aberto."""
    registo = []
    db = _db_com_reservas(registo, [_venda_aberta()], [])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))
    assert resultado["estado"] == "fechada"


# --- A JANELA do fecho: marcar primeiro, perguntar depois -----------------------
#
# A secção anterior prova que o fecho recusa quando encontra uma emissão viva.
# Esta prova a outra metade — que ele não pode ser ULTRAPASSADO por uma emissão
# que comece depois dessa pergunta. O fecho perguntava pela emissão e lia as
# vendas logo no princípio, mas só escrevia `fechada` no FIM, e no meio corria a
# verificação contra o Vendus, que é rede (um GET por dia da janela, 30 s de
# tempo limite, até 3 tentativas). Um FINALIZAR que caísse nessa janela relia a
# sessão, via-a AINDA ABERTA — porque estava mesmo — e emitia. Medido, com as
# rotas reais: `vendas_dinheiro=0.00 esperado=50.00 contado=58.99
# diferenca=+8.99`, 1 emissão real ao Vendus, e a venda `emitida` numa sessão
# `fechada`.
#
# A correcção não é mais uma verificação (essa deixa sempre a mesma janela, só
# mais estreita): é ORDEM. O fecho marca a sessão `a_fechar` ANTES de perguntar,
# e a partir daí é o próprio núcleo fiscal que recusa emitir. Ou o fecho vê a
# reserva, ou a emissão vê a marca — nunca nenhum dos dois.


def _sessoes_de(db):
    return db._coleccoes[COLECOES["sessoes_caixa"]]


def test_fecho_marca_a_sessao_a_fechar_antes_de_ler_as_vendas(monkeypatch):
    """A ordem, medida no instante exacto: quando o fecho lê as vendas para
    somar o Z, a sessão JÁ tem de estar marcada `a_fechar`. Ler primeiro e
    marcar depois é literalmente o defeito — entre as duas coisas cabia uma
    emissão inteira."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    estados_ao_ler = []
    colecao_vendas = db[COLECOES["vendas"]]
    find_original = colecao_vendas.find

    def espia_a_leitura_das_vendas(filtro=None, projecao=None):
        # Só a leitura QUE ALIMENTA O Z (as `emitida`) — as outras duas
        # leituras de vendas desta rota são as perguntas pela emissão viva,
        # que percorrem as contas ainda `aberta`, uma de cada lado da marca.
        if (filtro or {}).get("estado") == "emitida":
            estados_ao_ler.append(sessao["estado"])
        return find_original(filtro, projecao)

    colecao_vendas.find = espia_a_leitura_das_vendas

    _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0),
                        operador=_operador()))
    assert estados_ao_ler == ["a_fechar"], (
        "as vendas do Z foram lidas com a sessão ainda aberta — é a janela"
    )
    assert sessao["estado"] == "fechada"


def test_verificacao_contra_o_vendus_so_corre_depois_do_z_estar_escrito(monkeypatch):
    """A verificação contra o Vendus é I/O de REDE (30 s de tempo limite, até
    3 tentativas com esperas) e é uma segunda opinião de leitura: nada no Z
    depende dela. Estava no MEIO do fecho, e era ela que dava à janela os seus
    30 a 90 segundos de largura — tempo mais do que suficiente para um
    FINALIZAR inteiro caber lá dentro. Correndo depois da escrita, a marca
    `a_fechar` dura o que duram três escritas locais."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    estados_na_verificacao = []

    async def espia_a_verificacao(_db, _sessao, _valor):
        estados_na_verificacao.append(sessao["estado"])
        return {"nao_verificado": "desligado no teste"}

    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", espia_a_verificacao)

    resultado = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0),
                                    operador=_operador()))
    assert estados_na_verificacao == ["fechada"], (
        "a rede corre com a sessão em suspenso — é a janela outra vez"
    )
    assert resultado["verificacao_vendus"] == {"nao_verificado": "desligado no teste"}


def test_reserva_que_nasce_entre_a_pergunta_e_a_marca_e_apanhada_e_o_fecho_desfaz_se(monkeypatch):
    """A corrida mesmo: a reserva fiscal nasce DEPOIS de o fecho já ter
    perguntado pela emissão viva (não havia nenhuma) e antes de ele marcar a
    sessão. É a segunda pergunta — a que vem do outro lado da marca — que a
    apanha. O fecho tem de se desfazer por inteiro: a sessão volta a `aberta`,
    sem `fecho_iniciado_em`, e nenhum Z sai."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db_com_reservas(registo, [_venda_aberta()], [], sessoes=[sessao])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    colecao_sessoes = _sessoes_de(db)
    update_original = colecao_sessoes.update_one

    async def reserva_nasce_mesmo_antes_da_marca(filtro, atualizacao):
        if atualizacao.get("$set", {}).get("estado") == "a_fechar":
            # A Rafaela carregou em FINALIZAR no outro PC neste instante: a
            # reserva atómica já existe, o Vendus ainda não respondeu.
            db._coleccoes[COLECOES["refs_fiscais"]]._documentos.append(_reserva_fiscal())
        return await update_original(filtro, atualizacao)

    colecao_sessoes.update_one = reserva_nasce_mesmo_antes_da_marca

    with pytest.raises(HTTPException) as excinfo:
        _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99),
                            operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "emissão de fatura em curso" in excinfo.value.detail
    assert sessao["estado"] == "aberta", "a caixa ficou presa a meio de um fecho"
    assert sessao["fecho_iniciado_em"] is None
    assert sessao["fechada_em"] is None
    assert sessao["contado"] is None, "escreveu um Z para uma sessão que não fechou"


def test_a_marca_a_fechar_faz_o_nucleo_fiscal_recusar_emitir(monkeypatch):
    """O outro lado do par, confirmado contra o núcleo fiscal A SÉRIO (não
    contra a nossa ideia dele): com a sessão em `a_fechar`, a releitura que a
    emissão faz depois de ganhar a reserva recusa, LIBERTA a reserva e aborta
    sem falar com o Vendus. É disto que depende a correcção — se um dia o
    `fiscal.py` passar a aceitar outro estado que não `aberta`, é aqui que se
    vê, e não numa noite de sexta-feira."""
    from faturacao import fiscal as fiscal_mod

    registo = []
    sessao = _sessao(estado="a_fechar")
    db = _db_com_reservas(registo, [_venda_aberta()], [_reserva_fiscal()], sessoes=[sessao])

    with pytest.raises(fiscal_mod.SessaoJaNaoAberta):
        _corre(fiscal_mod._garante_venda_ainda_aberta(
            db, "pos-loja-1-sessao-1-venda-1", "venda-1", "ref-1"
        ))

    assert db._coleccoes[COLECOES["refs_fiscais"]]._documentos == [], (
        "a reserva ficou órfã a trancar a conta"
    )


def test_dois_fechos_ao_mesmo_tempo_so_um_passa_da_marca(monkeypatch):
    """A marca é o ponto de decisão único: escrita condicionada ao estado que
    foi lido, e é o `matched_count` que decide — como em todo o resto do
    módulo. O segundo pedido nem chega a somar nada."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    colecao_sessoes = _sessoes_de(db)
    update_original = colecao_sessoes.update_one

    async def o_outro_pc_marca_primeiro(filtro, atualizacao):
        # O fecho do outro PC ganhou a marca um instante antes deste.
        sessao["estado"] = "a_fechar"
        return await update_original(filtro, atualizacao)

    colecao_sessoes.update_one = o_outro_pc_marca_primeiro

    with pytest.raises(HTTPException) as excinfo:
        _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0),
                            operador=_operador()))
    assert excinfo.value.status_code == 409
    assert "a fechar esta sessão" in excinfo.value.detail
    assert sessao["contado"] is None


def test_fecho_com_a_sessao_fechada_por_outro_antes_da_escrita_final_nao_pisa_o_z(monkeypatch):
    """I2, agora contra a escrita final: quem tem a marca é o único que pode
    escrever o Z, mas se alguém tiver conseguido fechar a sessão à mesma
    (retoma concorrente de um fecho interrompido), a escrita condicionada a
    `a_fechar` não a pisa. Uma respondeu 50 €, a outra 30 €: não podem sair
    dois Z diferentes da mesma sessão."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    colecao_sessoes = _sessoes_de(db)
    update_original = colecao_sessoes.update_one

    async def fecha_por_fora_mesmo_antes_da_escrita_final(filtro, atualizacao):
        if atualizacao.get("$set", {}).get("estado") == "fechada":
            sessao["estado"] = "fechada"
            sessao["contado"] = 30.0
        return await update_original(filtro, atualizacao)

    colecao_sessoes.update_one = fecha_por_fora_mesmo_antes_da_escrita_final

    with pytest.raises(HTTPException) as excinfo:
        _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0),
                            operador=_operador()))
    assert excinfo.value.status_code == 409
    assert sessao["contado"] == 30.0


# --- Um fecho que morre a meio TEM de ter saída ---------------------------------
#
# O estado intermédio só é aceitável se uma falha lá dentro (o processo morto
# entre a marca e a escrita final) não deixar a caixa num beco. A sessão fica em
# `a_fechar`; o que se segue é o que a funcionária vê e o que a tira de lá.


def test_estado_caixa_mostra_a_sessao_que_ficou_a_meio_de_um_fecho(monkeypatch):
    """Se ela desaparecesse daqui, o ecrã mostrava "Caixa Fechada" com o
    resumo do fecho ANTERIOR e só oferecia o botão de ABRIR — que é recusado,
    e bem. A funcionária ficava sem forma nenhuma de chegar ao único botão que
    resolve isto, que é o FECHAR."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(estado="a_fechar")])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resposta = _corre(estado_caixa(operador=_operador()))
    assert resposta["sessao_aberta"] is not None
    assert resposta["sessao_aberta"]["estado"] == "a_fechar"
    assert resposta["ultimo_fecho"] is None


def test_fechar_outra_vez_retoma_o_fecho_interrompido_e_emite_o_z(monkeypatch):
    """A saída do beco: carregar outra vez em FECHAR CAIXA. As somas são todas
    recalculadas do zero — nada é reaproveitado da tentativa que morreu."""
    registo = []
    sessao = _sessao(fundo=50.0, estado="a_fechar",
                     fecho_iniciado_em="2026-08-18T23:58:00+00:00")
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[],
             vendas=[_venda_emitida()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99),
                                    operador=_operador()))
    assert resultado["estado"] == "fechada"
    assert resultado["vendas_dinheiro"] == 8.99
    assert resultado["esperado"] == 58.99
    assert resultado["diferenca"] == 0.0
    assert sessao["estado"] == "fechada"


def test_abrir_caixa_com_uma_sessao_a_meio_de_um_fecho_e_recusado(monkeypatch):
    """O índice único parcial de db.py só cobre `estado: "aberta"` — uma
    sessão em `a_fechar` não colide com nada e deixava abrir uma sessão nova
    POR CIMA dela. Ficavam duas sessões vivas na mesma caixa: a nova a receber
    as vendas e a velha para sempre sem Z, com as vendas dela fora de qualquer
    fecho. A mensagem tem de dizer o que fazer."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(estado="a_fechar")])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.0),
                           operador=_operador()))
    assert excinfo.value.status_code == 409
    assert "FECHAR CAIXA" in excinfo.value.detail
    assert not any(chamada[0] == "insert_one" for chamada in registo), (
        "abriu uma segunda sessão por cima de uma que ainda espera um Z"
    )


def test_movimento_com_a_sessao_a_meio_de_um_fecho_diz_o_que_fazer(monkeypatch):
    """Recusado — o Z está a ser calculado, dinheiro a entrar agora na gaveta
    não pertence a fecho nenhum. Mas a mensagem não pode ser "esta caixa não
    tem nenhuma sessão aberta": é verdade à letra e é uma pista errada, que
    manda a funcionária ABRIR a caixa (recusado) em vez de FECHAR."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(estado="a_fechar")])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(registar_movimento(
            PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 409
    assert "FECHAR CAIXA" in excinfo.value.detail
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_movimento_que_chega_a_meio_do_fecho_e_recusado_e_nao_fica_fora_do_z(monkeypatch):
    """A mesma janela, com dinheiro em vez de faturas: os movimentos do Z
    eram lidos no princípio do fecho e a sessão só fechava no fim, com rede
    pelo meio. Uma sangria ou um reforço registados nesse intervalo passavam
    a confirmação (a sessão estava mesmo `aberta`) e ficavam fora do Z que a
    funcionária assinou — dinheiro na gaveta sem fecho nenhum que o
    explique, exactamente como a FS. A marca fecha as duas coisas de uma
    vez: a partir dela, o movimento é RECUSADO."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    tentativa = {}
    colecao_sessoes = _sessoes_de(db)
    update_original = colecao_sessoes.update_one

    async def a_rafaela_tira_troco_no_outro_pc(filtro, atualizacao):
        resultado = await update_original(filtro, atualizacao)
        if atualizacao.get("$set", {}).get("estado") == "a_fechar" and not tentativa:
            try:
                await registar_movimento(
                    PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=20.0,
                                    motivo="troco para o outro PC"),
                    operador=_operador(),
                )
                tentativa["resultado"] = "aceite"
            except HTTPException as e:
                tentativa["resultado"] = e.status_code
                tentativa["detalhe"] = e.detail
        return resultado

    colecao_sessoes.update_one = a_rafaela_tira_troco_no_outro_pc

    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0),
                            operador=_operador()))
    assert tentativa["resultado"] == 409
    assert "FECHAR CAIXA" in tentativa["detalhe"]
    assert z["saidas"] == 0.0
    assert z["esperado"] == 50.0, "um movimento aceite ficou fora do Z"


def test_fecho_que_rebenta_a_meio_deixa_a_caixa_fechavel_e_nao_num_beco(monkeypatch):
    """A outra metade da marca `a_fechar`, e a que a torna aceitável: se o
    fecho abortar DEPOIS de a pôr — um soluço do Mongo a ler as vendas, um
    restart, um deploy — a sessão fica marcada e a loja NÃO pode ficar sem
    saída. Fica: `_sessao_por_fechar` aceita `a_fechar`, e o gesto óbvio
    (carregar outra vez em FECHAR CAIXA) conclui o turno, com as somas todas
    recalculadas do zero.

    O que a marca NUNCA pode ser é uma sessão que não fecha nem abre — nesse
    caso a loja passava a noite sem POS."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[],
             vendas=[_venda_emitida()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    async def verificacao(_db, _sessao, _valor):
        return {"nao_verificado": "duplo"}
    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", verificacao)

    vendas = db._coleccoes[COLECOES["vendas"]]
    find_original = vendas.find
    # A TERCEIRA leitura das vendas é a das somas do Z — já do outro lado da
    # marca (as duas primeiras são as perguntas pela emissão viva, uma de cada
    # lado dela). É aí que o fecho tem de morrer para este cenário ser o que
    # diz ser.
    leituras = {"n": 0}

    def find_que_rebenta_nas_somas(filtro=None, projecao=None):
        leituras["n"] += 1
        if leituras["n"] == 3:
            raise RuntimeError("o Mongo engasgou-se a ler as vendas da sessão")
        return find_original(filtro, projecao)

    vendas.find = find_que_rebenta_nas_somas

    with pytest.raises(RuntimeError):
        _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99),
                            operador=_operador()))
    assert sessao["estado"] == "a_fechar"
    assert sessao["contado"] is None, "escreveu um Z de um fecho que abortou"

    # E a segunda tentativa fecha, com tudo recalculado.
    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99),
                            operador=_operador()))
    assert z["estado"] == "fechada"
    assert z["vendas_dinheiro"] == 8.99
    assert z["diferenca"] == 0.0
    assert sessao["estado"] == "fechada"


# --- O movimento e o Z: a confirmação e o dinheiro na MESMA escrita ------------
#
# `registar_movimento` confirmava que a sessão estava aberta com uma escrita
# condicional (o `matched_count` a decidir — a defesa I2) e só DEPOIS gravava
# o movimento: noutra colecção, e sem condição nenhuma. A confirmação é uma
# fotografia, e entre ela e o `insert_one` cabia um fecho inteiro — o fecho lê
# `fat_movimentos_caixa` DEPOIS da marca `a_fechar` e escreve o Z a seguir. A
# marca congela as VENDAS (o núcleo fiscal recusa emitir) e não congelava os
# movimentos.
#
# Medido, sobre as rotas reais: a Rafaela tira 20,00 € para pagar o fornecedor
# do gelo e regista a saída; a Ana conta a gaveta e fecha — «Z assinado:
# fundo=50.00 saidas=0.00 esperado=50.00 contado=30.00 diferenca=-20.00» — e
# só depois «o movimento gravou-se AGORA: 201», numa sessão já `fechada`. A
# funcionária assina um Z que acusa uma falta de 20,00 € numa gaveta que está
# certa, e os 20 € não entram em Z nenhum: nem neste (assinado) nem no
# seguinte (que filtra pelo sessao_id da sessão nova).
#
# A correcção: o movimento entra primeiro (marcado `por_confirmar`) e o que o
# torna dinheiro é a MESMA escrita que confirma a sessão — o `$push` do `id`
# para `movimentos_confirmados`, condicionado a `{"estado": "aberta"}`. Uma
# escrita só, no MESMO documento em que o fecho põe a marca: ou o `id` entra
# antes da marca (e o Z conta-o), ou a marca chega primeiro (e o movimento é
# recusado). Não há terceira ordem.


def test_movimento_confirmado_antes_da_marca_entra_no_z(monkeypatch):
    """O caminho normal, com o Z a prová-lo: uma saída de 20,00 € registada
    antes de o fecho começar tem de aparecer no Z como saída — é a leitura
    pela lista da sessão que o garante, e não a colecção lida às cegas."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=20.0,
                        motivo="pagar o fornecedor do gelo"),
        operador=_operador(),
    ))
    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=30.0),
                            operador=_operador()))

    assert z["saidas"] == 20.0
    assert z["esperado"] == 30.0
    assert z["diferenca"] == 0.0, "a gaveta está certa e o Z tem de o dizer"


def test_movimento_que_so_se_grava_depois_do_z_e_recusado_e_nao_deixa_rasto(monkeypatch):
    """O cenário medido, do princípio ao fim: o fecho INTEIRO corre entre o
    início do movimento e a escrita que o confirmaria. O movimento leva 409,
    o Z fica com a gaveta certa, e não fica lixo na colecção."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    fecho = {}
    colecao_movimentos = db[COLECOES["movimentos_caixa"]]
    insert_original = colecao_movimentos.insert_one

    async def a_ana_fecha_a_caixa_no_outro_pc(doc):
        if not fecho:
            # A Ana conta a gaveta (30,00 €) e fecha, ANTES de este movimento
            # chegar a ser confirmado.
            fecho["z"] = await fechar_caixa(
                PedidoFecharCaixa(caixa_id="caixa-1", contado=30.0),
                operador=_operador(nome="Ana"),
            )
        return await insert_original(doc)

    colecao_movimentos.insert_one = a_ana_fecha_a_caixa_no_outro_pc

    with pytest.raises(HTTPException) as excinfo:
        _corre(registar_movimento(
            PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=20.0,
                            motivo="pagar o fornecedor do gelo"),
            operador=_operador(),
        ))

    assert excinfo.value.status_code == 409
    assert "NÃO entrou em nenhum Z" in excinfo.value.detail
    # A sessão ACABOU MESMO (Z assinado, `fechada`), e é o único caso em que a
    # recusa pode mandar a operadora repetir noutra sessão — ver
    # `_porque_o_movimento_nao_entrou`. Sem esta asserção, as três saídas
    # podiam colapsar numa só sem nenhum teste dar por isso.
    assert sessao["estado"] == "fechada" and fecho["z"]["esperado"] == 50.0
    assert "já na sessão nova" in excinfo.value.detail
    assert colecao_movimentos._documentos == []
    assert sessao.get("movimentos_confirmados", []) == []


def test_movimento_que_ficou_a_meio_nunca_entra_num_z(monkeypatch):
    """Um processo que morre entre o `insert_one` e a confirmação deixa a
    linha `por_confirmar` na colecção. Esse dinheiro NUNCA saiu da gaveta —
    ninguém recebeu 201 — e o fecho não o pode contar: contá-lo era acusar
    uma falta que não existe, exactamente o estrago que isto veio corrigir,
    só que pelo outro lado."""
    registo = []
    a_meio = {"id": "m-a-meio", "sessao_id": "sessao-1", "tipo": "saida",
              "valor": 20.0, "motivo": "processo morto a meio",
              "por": {"id": "op-1", "nome": "Rafaela"},
              "em": "2026-08-15T09:30:00+00:00", "por_confirmar": True}
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(fundo=50.0)],
             movimentos=[a_meio], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0),
                            operador=_operador()))

    assert z["saidas"] == 0.0
    assert z["esperado"] == 50.0
    assert z["diferenca"] == 0.0


def test_movimentos_anteriores_a_esta_correccao_continuam_a_entrar_no_z(monkeypatch):
    """A migração, que aqui não existe de propósito: uma sessão aberta ANTES
    do deploy não tem `movimentos_confirmados` nenhum, e os movimentos dela
    não têm `por_confirmar`. Esses contam sempre — uma sessão que atravesse o
    deploy não pode ver o dinheiro dela desaparecer do Z."""
    registo = []
    antigo = {"id": "m-antigo", "sessao_id": "sessao-1", "tipo": "saida",
              "valor": 20.0, "motivo": "sangria de ontem",
              "por": {"id": "op-1", "nome": "Rafaela"},
              "em": "2026-08-15T09:30:00+00:00"}
    sessao = _sessao(fundo=50.0)
    assert "movimentos_confirmados" not in sessao
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao],
             movimentos=[antigo], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=30.0),
                            operador=_operador()))

    assert z["saidas"] == 20.0
    assert z["esperado"] == 30.0


def test_a_lista_de_confirmados_nao_vai_no_estado_da_caixa(monkeypatch):
    """`movimentos_confirmados` é escrituração interna do fecho e cresce com
    cada movimento: não tem nada que fazer na resposta que o ecrã da caixa lê.

    Só isso — a outra metade ("a rota de leitura não apagou o campo do
    documento guardado") mede-se na função, não aqui: por esta rota, um
    `pop` destrutivo em `_sessao_publica` é INVISÍVEL, porque o duplo devolve
    cópia funda como o Motor e o que ele apagaria era só a cópia. É
    `test_sessao_publica_nao_mexe_no_dicionario_que_recebe` que a defende."""
    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0),
        operador=_operador(),
    ))
    estado = _corre(estado_caixa(caixa_id="caixa-1", operador=_operador()))

    assert "movimentos_confirmados" not in estado["sessao_aberta"]
    # E a lista continua a ser escrita na sessão — a rota não tem de a
    # devolver, mas o fecho conta com ela.
    assert len(sessao["movimentos_confirmados"]) == 1


def test_sessao_publica_nao_mexe_no_dicionario_que_recebe():
    """`_sessao_publica` é uma PROJECÇÃO: devolve uma cópia sem o campo, e
    deixa intacto o dicionário que lhe deram.

    A asserção que aqui estava passava pela rota e era impossível de pôr
    vermelha: trocava-se o dicionário por compreensão por um
    `sessao.pop(...); return sessao` — a rota de leitura a apagar mesmo o
    campo — e ela continuava verde, porque o `find_one` do duplo devolve cópia
    funda (como o Motor) e o `pop` só mordia essa cópia. Um teste que não
    consegue ficar vermelho não defende nada; este mede a função directamente
    e apanha o `pop`.

    E o que se defende não é hipotético só por o Motor copiar: os dois
    chamadores de hoje passam-lhe leituras descartáveis, mas a próxima
    chamada que lhe passe uma sessão que ainda vai ser usada (o fecho relê a
    sessão marcada e é dessa lista que sai o Z) perdia
    `movimentos_confirmados` do dicionário em mãos — dinheiro fora do Z, a
    partir de uma função de leitura."""
    sessao = {"id": "sessao-1", "estado": "aberta",
              "movimentos_confirmados": ["m-1", "m-2"]}

    publica = _sessao_publica(sessao)

    assert "movimentos_confirmados" not in publica
    # `.get`, e não `[...]`: com o campo apagado o que se quer ler é a
    # mensagem, não um KeyError.
    assert sessao.get("movimentos_confirmados") == ["m-1", "m-2"], (
        "`_sessao_publica` apagou o campo do dicionário que recebeu"
    )
    assert publica["id"] == "sessao-1" and publica["estado"] == "aberta"
    assert _sessao_publica(None) is None


def test_movimento_confirmado_mesmo_antes_da_marca_ainda_entra_no_z(monkeypatch):
    """A janela mais estreita de todas, e a razão de a sessão se RELER depois
    da marca: o movimento confirma-se entre a leitura de entrada do fecho e a
    marca `a_fechar`. A sessão está aberta quando ele passa, logo o Z tem de o
    contar — e tem de o contar mesmo no pior caso, com a marca
    `por_confirmar` da linha ainda por limpar (é uma escrita à parte, e o
    fecho pode cair no intervalo). Lida do documento de entrada, a lista de
    confirmados vinha vazia e os 20,00 € ficavam fora do Z assinado."""

    class MovimentosQueNaoChegamALimparAMarca(ColeccaoFalsa):
        async def update_one(self, filtro, atualizacao):
            if "por_confirmar" in (atualizacao.get("$set") or {}):
                raise RuntimeError("o fecho entrou antes de a marca sair")
            return await super().update_one(filtro, atualizacao)

    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    db._coleccoes[COLECOES["movimentos_caixa"]] = MovimentosQueNaoChegamALimparAMarca(
        registo, [])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    colecao_sessoes = _sessoes_de(db)
    update_original = colecao_sessoes.update_one

    async def a_rafaela_regista_a_saida_antes_da_marca(filtro, atualizacao):
        if atualizacao.get("$set", {}).get("estado") == "a_fechar":
            colecao_sessoes.update_one = update_original  # só uma vez
            await registar_movimento(
                PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=20.0,
                                motivo="pagar o fornecedor do gelo"),
                operador=_operador(),
            )
        return await update_original(filtro, atualizacao)

    colecao_sessoes.update_one = a_rafaela_regista_a_saida_antes_da_marca

    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=30.0),
                            operador=_operador(nome="Ana")))

    assert z["saidas"] == 20.0
    assert z["esperado"] == 30.0
    assert z["diferenca"] == 0.0


def test_movimento_confirmado_conta_no_z_mesmo_com_a_marca_por_limpar(monkeypatch):
    """Quem manda é a LISTA da sessão, nunca a marca `por_confirmar` da linha.
    A marca sai numa escrita à parte, a seguir à confirmação, e é uma
    conveniência: se ela não sair (um soluço do Mongo, ou o fecho a ler no
    intervalo entre as duas escritas), o movimento está confirmado à mesma e
    o Z TEM de o contar. É essa janela que obriga a lista a ser lida do
    documento marcado `a_fechar`, e não do que o fecho leu à entrada."""

    class MovimentosQueNaoLimpamAMarca(ColeccaoFalsa):
        async def update_one(self, filtro, atualizacao):
            if "por_confirmar" in (atualizacao.get("$set") or {}):
                raise RuntimeError("Mongo com soluços a limpar a marca")
            return await super().update_one(filtro, atualizacao)

    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    db._coleccoes[COLECOES["movimentos_caixa"]] = MovimentosQueNaoLimpamAMarca(registo, [])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    movimento = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=20.0,
                        motivo="pagar o fornecedor do gelo"),
        operador=_operador(),
    ))
    # A operadora recebeu 201: o dinheiro saiu mesmo da gaveta.
    assert movimento["valor"] == 20.0
    guardado = db._coleccoes[COLECOES["movimentos_caixa"]]._documentos[0]
    assert guardado["por_confirmar"] is True, "a marca ficou mesmo por limpar"

    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=30.0),
                            operador=_operador(nome="Ana")))

    assert z["saidas"] == 20.0
    assert z["esperado"] == 30.0
    assert z["diferenca"] == 0.0


def test_dois_movimentos_confirmados_contam_os_dois_no_z(monkeypatch):
    """A lista da sessão CRESCE — é um `$push`, nunca um `$set` de uma lista
    montada por quem escreve.

    O teste de cima tem UM movimento, e com um só um `$set` de `[o meu id]`
    dá exactamente o mesmo que um `$push`: a garantia inteira do módulo (quem
    manda é a lista da sessão) fica sem rede. Aqui são DOIS, e a limpeza da
    marca falha no PRIMEIRO — o mesmo "Mongo com soluços" que o teste de cima
    modela. Com `$push`, os dois `id`s estão na lista e o Z conta os 25,00 €.
    Com um `$set`, o segundo movimento apaga o primeiro da lista; e como esse
    ficou com a marca `por_confirmar` por limpar, o fecho descarta-o: o Z
    conta 5,00 € de saídas e acusa uma falta de 20,00 € numa gaveta que está
    certa — a funcionária assina um Z que a acusa de dinheiro que ela não
    tirou."""

    class MarcaQueFalhaNoPrimeiro(ColeccaoFalsa):
        def __init__(self, registo, documentos=None):
            super().__init__(registo, documentos)
            self.limpezas = 0

        async def update_one(self, filtro, atualizacao):
            if "por_confirmar" in (atualizacao.get("$set") or {}):
                self.limpezas += 1
                if self.limpezas == 1:
                    raise RuntimeError("Mongo com soluços a limpar a marca")
            return await super().update_one(filtro, atualizacao)

    registo = []
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[], vendas=[])
    db._coleccoes[COLECOES["movimentos_caixa"]] = MarcaQueFalhaNoPrimeiro(registo, [])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    primeiro = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=20.0,
                        motivo="pagar o fornecedor do gelo"),
        operador=_operador(),
    ))
    segundo = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=5.0,
                        motivo="pilhas para a balança"),
        operador=_operador(),
    ))
    # As duas saídas foram aceites (201) — o dinheiro saiu mesmo da gaveta.
    linhas = db._coleccoes[COLECOES["movimentos_caixa"]]._documentos
    assert [li["valor"] for li in linhas] == [20.0, 5.0]
    assert linhas[0]["por_confirmar"] is True, (
        "o cenário só vale se a marca do PRIMEIRO tiver mesmo ficado por limpar"
    )

    # A gaveta: 50,00 € de fundo, menos 20,00 €, menos 5,00 € = 25,00 €, e é
    # isso que lá está mesmo.
    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=25.0),
                            operador=_operador(nome="Ana")))

    assert z["saidas"] == 25.0, "o Z tem de contar as DUAS saídas, não só a última"
    assert z["esperado"] == 25.0
    assert z["diferenca"] == 0.0, "a gaveta está certa e o Z tem de o dizer"
    # E o mecanismo que o garante, dito à letra: a lista tem os DOIS `id`s.
    assert sessao["movimentos_confirmados"] == [primeiro["id"], segundo["id"]], (
        "a confirmação empurra para a lista, nunca a substitui pela sua"
    )


# --- A recusa de um movimento diz o que se sabe NO INSTANTE em que é enviada ---
#
# A confirmação exige `{"estado": "aberta"}` e falhava sempre com a mesma
# frase: "esta sessão foi fechada por outro pedido — registe o movimento outra
# vez, já na sessão nova". Mas o fecho marca `a_fechar` ANTES de perguntar pela
# emissão viva e DESFAZ a marca quando encontra uma. Um movimento que caia
# nessa janela ouvia três afirmações falsas ao mesmo tempo — não houve Z, a
# sessão é a mesma, e a "sessão nova" pode nunca vir a existir — e a única
# acção que a mensagem sugeria era a errada.
#
# É a mesma invariante que `venda.py::_porque_nao_foi_cancelada` e
# `fiscal.py::SessaoEmFechoAgora` já fixam para as mensagens da venda e da
# emissão: dizer à operadora que o turno acabou só pode acontecer se o turno
# tiver MESMO acabado.


class MovimentosComPausa(ColeccaoFalsa):
    """Pára o movimento no `insert_one` — depois de ele já ter lido a sessão
    ABERTA e antes de a confirmação correr. `ao_apagar` corre no `delete_one`
    da limpeza, que é o último passo antes de a mensagem ser composta: é por
    aí que se controla o que a operadora encontra quando a lê."""

    def __init__(self, registo, documentos=None):
        super().__init__(registo, documentos)
        self.chegou = asyncio.Event()
        self.segue = asyncio.Event()
        self.armado = False
        self.ao_apagar = None

    async def insert_one(self, doc):
        if self.armado:
            self.armado = False
            self.chegou.set()
            await self.segue.wait()
        return await super().insert_one(doc)

    async def delete_one(self, filtro):
        accao, self.ao_apagar = self.ao_apagar, None
        if accao is not None:
            await accao()
        return await super().delete_one(filtro)


class SessoesComPausa(ColeccaoFalsa):
    """Pára o fecho logo a seguir a escrever a marca `a_fechar` — a janela em
    que a caixa não está aberta e ainda não fechou nada."""

    def __init__(self, registo, documentos=None):
        super().__init__(registo, documentos)
        self.marcou = asyncio.Event()
        self.segue = asyncio.Event()
        self.armado = False

    async def update_one(self, filtro, atualizacao):
        resultado = await super().update_one(filtro, atualizacao)
        if (self.armado and resultado.matched_count == 1
                and (atualizacao.get("$set") or {}).get("estado") == "a_fechar"):
            self.armado = False
            self.marcou.set()
            await self.segue.wait()
        return resultado


def _db_do_fecho_recusado(registo):
    """Uma caixa com uma conta ABERTA e uma reserva fiscal viva nela: é o que
    faz o fecho ser recusado do outro lado da marca — e desfazer-se."""
    sessao = _sessao(fundo=50.0)
    db = _db(registo, caixas=[_caixa()], sessoes=[sessao], movimentos=[],
             vendas=[{"id": "venda-1", "sessao_id": "sessao-1", "loja_id": "loja-1",
                      "estado": "aberta", "linhas": [], "pagamentos": []}])
    db._coleccoes[COLECOES["sessoes_caixa"]] = SessoesComPausa(registo, [sessao])
    db._coleccoes[COLECOES["movimentos_caixa"]] = MovimentosComPausa(registo, [])
    db._coleccoes[COLECOES["refs_fiscais"]] = ColeccaoFalsa(registo, [])
    return db, sessao


async def _a_rafaela_apanhada_pelo_fecho_da_ana(db, desfazer_antes_da_mensagem):
    """A ordem forçada, sobre as rotas reais:
    1. a Rafaela tira 20,00 € e regista a saída — lê a sessão ABERTA e pára;
    2. a Ana carrega em FECHAR CAIXA e a marca `a_fechar` fica escrita;
    3. uma emissão ganha a reserva DENTRO da janela da marca (é o que vai
       fazer o fecho ser recusado e desfeito);
    4. o movimento segue e a confirmação já não casa -> 409.

    `desfazer_antes_da_mensagem` decide o que a Rafaela encontra quando lê a
    recusa: com `False`, a marca ainda lá está (a caixa está mesmo a fechar
    naquele instante); com `True`, o fecho já foi recusado e desfeito e a
    caixa está outra vez ABERTA."""
    sessoes = db._coleccoes[COLECOES["sessoes_caixa"]]
    movimentos = db._coleccoes[COLECOES["movimentos_caixa"]]

    movimentos.armado = True
    mov = asyncio.ensure_future(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=20.0,
                        motivo="pagar o fornecedor do gelo"),
        operador=_operador(),
    ))
    await movimentos.chegou.wait()

    sessoes.armado = True
    fecho = asyncio.ensure_future(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0),
        operador=_operador(nome="Ana"),
    ))
    await sessoes.marcou.wait()

    await db[COLECOES["refs_fiscais"]].insert_one(
        {"id": "ref-1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1"})

    async def deixar_o_fecho_acabar():
        sessoes.segue.set()
        await asyncio.gather(fecho, return_exceptions=True)

    if desfazer_antes_da_mensagem:
        movimentos.ao_apagar = deixar_o_fecho_acabar
    movimentos.segue.set()
    recusa = (await asyncio.gather(mov, return_exceptions=True))[0]
    if not desfazer_antes_da_mensagem:
        await deixar_o_fecho_acabar()
    resultado_do_fecho = (await asyncio.gather(fecho, return_exceptions=True))[0]
    return recusa, resultado_do_fecho


def _nao_houve_z(sessao, db):
    return (sessao["estado"] == "aberta" and sessao["fechada_em"] is None
            and sessao["contado"] is None
            and db._coleccoes[COLECOES["movimentos_caixa"]]._documentos == [])


def test_movimento_recusado_a_meio_de_um_fecho_nao_diz_que_o_turno_acabou(monkeypatch):
    """A janela medida: a marca `a_fechar` está posta e o fecho ainda vai ser
    recusado por uma emissão viva. A caixa acaba a noite ABERTA, na mesma
    sessão, sem Z nenhum — e a recusa não pode mandar a Rafaela repor o
    dinheiro numa "sessão nova" que não existe. O que ela precisa de ouvir é
    que espere alguns segundos."""
    registo = []
    db, sessao = _db_do_fecho_recusado(registo)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    recusa, fecho = _corre(_a_rafaela_apanhada_pelo_fecho_da_ana(
        db, desfazer_antes_da_mensagem=False))

    assert isinstance(recusa, HTTPException) and recusa.status_code == 409
    assert "está a FECHAR o turno neste momento" in recusa.detail
    assert "NÃO entrou em nenhum Z" in recusa.detail
    assert "sessão nova" not in recusa.detail, (
        "nenhum Z foi assinado e não há sessão nenhuma para onde a mandar"
    )
    # E o mundo é mesmo como a mensagem o descreve: o fecho foi recusado, a
    # sessão voltou a `aberta` e não ficou lixo na colecção.
    assert isinstance(fecho, HTTPException) and fecho.status_code == 409
    assert _nao_houve_z(sessao, db)


def test_movimento_recusado_por_um_fecho_ja_desfeito_manda_repetir_aqui_mesmo(monkeypatch):
    """A mesma corrida, um instante mais tarde: quando a Rafaela lê a recusa,
    o fecho já foi recusado e desfeito e a caixa está outra vez ABERTA — na
    MESMA sessão. A acção certa é registar o movimento outra vez aqui, e é
    isso que a mensagem tem de dizer."""
    registo = []
    db, sessao = _db_do_fecho_recusado(registo)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    recusa, fecho = _corre(_a_rafaela_apanhada_pelo_fecho_da_ana(
        db, desfazer_antes_da_mensagem=True))

    assert isinstance(recusa, HTTPException) and recusa.status_code == 409
    assert "MESMA sessão" in recusa.detail
    assert "registe-o outra vez, aqui mesmo" in recusa.detail
    assert "sessão nova" not in recusa.detail
    assert isinstance(fecho, HTTPException) and fecho.status_code == 409
    assert _nao_houve_z(sessao, db)


def test_a_recusa_de_um_movimento_nao_inventa_diagnostico_em_estado_inesperado():
    """A quarta saída, e a razão de ela existir: a sessão desapareceu, ou está
    num estado que este módulo não escreve. Aí não se escolhe a mais provável —
    escolhe-se a que não afirma nada sobre a caixa e manda olhar para o ecrã.
    Dizer "foi fechada, registe na sessão nova" sem o saber é o defeito que
    esta ronda veio fechar, e um estado inesperado não é prova de fecho
    nenhum."""
    registo = []
    vazia = _db(registo, caixas=[_caixa()], sessoes=[], movimentos=[], vendas=[])
    estranha = _db(registo, caixas=[_caixa()], movimentos=[], vendas=[],
                   sessoes=[_sessao(estado="estado-que-nao-existe")])

    for db in (vazia, estranha):
        mensagem = _corre(_porque_o_movimento_nao_entrou(db, "sessao-1"))
        assert "veja o ecrã da caixa" in mensagem
        assert "NÃO entrou em nenhum Z" in mensagem, (
            "isto sabe-se sempre: a confirmação não casou, logo nenhum Z o conta"
        )
        assert "foi fechada" not in mensagem and "sessão nova" not in mensagem
