"""Sessão de caixa do POS: abrir e registar movimentos (Task 3 do Plano 2A).

Mesmo padrão de duplo de base de dados que test_pos_auth.py: find()/find_one()
filtram de facto pelos campos do filtro, para que "caixa já aberta" e "sem
sessão aberta" provem comportamento real, e não apenas confiem que o Mongo
filtraria por nós. Nenhum teste liga a uma base de dados nem à rede.
"""
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import caixa as caixa_mod
from faturacao.caixa import (
    PedidoAbrirCaixa,
    PedidoFecharCaixa,
    PedidoMovimento,
    abrir_caixa,
    fechar_caixa,
    registar_movimento,
)
from faturacao.db import COLECOES


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ----------------------------------------------------


def _corresponde(item, filtro):
    """Réplica minimalista do casamento de filtro do Mongo: igualdade exacta
    em cada campo pedido."""
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


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


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: find()/find_one() filtram de facto."""

    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None):
        self.registo.append(("find", filtro))
        return CursorFalso([d for d in self._documentos if _corresponde(d, filtro)])

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return encontrados[0] if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._documentos.append(doc)
        return None

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return ResultadoUpdateFalso(matched_count=len(alvos))


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
    c = {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão"}
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
    assert not any(chamada[0] == "insert_one" for chamada in registo)


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
