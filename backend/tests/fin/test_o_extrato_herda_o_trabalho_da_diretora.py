"""**Quando o extrato chega, absorve — e herda o que já foi classificado.**

O fluxo real, dito pelo dono: durante o mês entram os avisos do banco e as
linhas que a diretora financeira escreve à mão; no fim (ou início) do mês entra
o extrato, para confirmar que os saldos estão certos.

O extrato traz os MESMOS movimentos, com a descrição do banco e com saldo. Se
ele entrasse por cima, ficava tudo a dobrar. Se apagasse o que lá estava,
deitava fora horas de classificação: a categoria, a descrição que ela deu
("MAKRO" onde o banco escreve "COMPRA 4512 MAKRO CASH"), a anotação e a fatura
que ela ligou.

Por isso ele ABSORVE: fica a linha do extrato, que tem saldo, com o trabalho
dela por cima. E o que ela escreve que o banco nunca vai mostrar — o "Dinheiro
Restante Mês Anterior" do Excel — não é tocado.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _casa(doc, filtro):
    for campo, esperado in filtro.items():
        valor = doc.get(campo)
        if isinstance(esperado, dict):
            if "$gte" in esperado and not (valor is not None and valor >= esperado["$gte"]):
                return False
            if "$lte" in esperado and not (valor is not None and valor <= esperado["$lte"]):
                return False
        elif valor != esperado:
            return False
    return True


class MovimentosFalsos:
    def __init__(self, guardados=None):
        self.guardados = [dict(d) for d in (guardados or [])]
        self.inseridos = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if _casa(doc, filtro):
                return dict(doc)
        return None

    def find(self, filtro, proj=None):
        docs = [dict(d) for d in self.guardados if _casa(d, filtro)]

        class Cursor:
            async def to_list(self, n):
                return docs
        return Cursor()

    async def insert_one(self, doc):
        self.inseridos.append(doc)
        self.guardados.append(dict(doc))

    async def delete_one(self, filtro):
        self.guardados = [d for d in self.guardados if not _casa(d, filtro)]

    async def delete_many(self, filtro):
        antes = len(self.guardados)
        self.guardados = [d for d in self.guardados if not _casa(d, filtro)]

        class Res:
            deleted_count = antes - len(self.guardados)
        return Res()


class BaseFalsa:
    def __init__(self, movimentos):
        self.fin_movements = movimentos


CONTA = {"id": "c1", "company_id": "e1", "account_number": "0000045740375997", "currency": "EUR"}

# O extrato descreve o movimento à maneira do banco.
EXTRATO = [{"date_lancamento": "2026-09-04",
            "description": "COMPRA 4512 MAKRO CASH CARRY LISBOA",
            "amount": -65.8, "balance": 3127.11}]

# A linha dela: o mesmo dinheiro, com o nome dela e já classificada.
DELA = {
    "id": "sua", "account_id": "c1", "company_id": "e1",
    "date_lancamento": "2026-09-04", "amount": -65.8, "balance": None,
    "description": None, "title": "MAKRO", "category": "supermercado",
    "note": "compra da semana", "invoice_id": "fatura-1", "link_auto": False,
    "attachment_path": "/uploads/x.pdf", "manual": True, "provisorio": False,
    "dedup_key": None,
}


def _base(monkeypatch, guardados):
    movs = MovimentosFalsos(guardados)
    monkeypatch.setattr(server, "db", BaseFalsa(movs))
    return movs


def test_o_extrato_absorve_a_linha_dela_e_herda_tudo(monkeypatch):
    movs = _base(monkeypatch, [DELA])

    ins, salt, absorvidas = _corre(server._fin_guardar_movimentos_do_banco(
        CONTA, EXTRATO, "bank_email", provisorio=False))

    assert (ins, absorvidas) == (1, 1)
    assert len(movs.guardados) == 1, "ficaram duas linhas para o mesmo dinheiro"
    nova = movs.guardados[0]
    assert nova["balance"] == 3127.11, "a linha que ficou tem de ser a do extrato, com saldo"
    assert nova["title"] == "MAKRO", "perdeu a descrição que ela escreveu"
    assert nova["category"] == "supermercado", "perdeu a classificação dela"
    assert nova["note"] == "compra da semana", "perdeu a anotação dela"
    assert nova["invoice_id"] == "fatura-1", "desligou a fatura que ela tinha ligado"
    assert nova["attachment_path"] == "/uploads/x.pdf", "perdeu o documento anexado"


def test_um_aviso_do_banco_tambem_e_absorvido(monkeypatch):
    aviso = dict(DELA, id="aviso", manual=False, provisorio=True,
                 title=None, category="supermercado", note=None,
                 invoice_id=None, attachment_path=None)
    movs = _base(monkeypatch, [aviso])

    ins, _s, absorvidas = _corre(server._fin_guardar_movimentos_do_banco(
        CONTA, EXTRATO, "bank_email", provisorio=False))

    assert (ins, absorvidas) == (1, 1)
    assert len(movs.guardados) == 1
    assert movs.guardados[0]["category"] == "supermercado"


def test_o_que_ela_escreve_e_o_banco_nunca_mostra_fica_intocado(monkeypatch):
    # "Dinheiro Restante Mês Anterior": não tem gémeo no extrato.
    dela = dict(DELA, id="restante", amount=1104.97, title="Dinheiro Restante Mês Anterior")
    movs = _base(monkeypatch, [dela])

    ins, _s, absorvidas = _corre(server._fin_guardar_movimentos_do_banco(
        CONTA, EXTRATO, "bank_email", provisorio=False))

    assert (ins, absorvidas) == (1, 0), "absorveu uma linha que não era a mesma"
    assert len(movs.guardados) == 2
    assert any(d["id"] == "restante" for d in movs.guardados), "apagou o que só existe no mapa dela"


def test_uma_linha_antiga_so_e_absorvida_uma_vez(monkeypatch):
    # Duas compras de 65,80 no mesmo dia no extrato, uma linha dela.
    # A primeira absorve; a segunda tem de entrar como movimento novo.
    movs = _base(monkeypatch, [DELA])
    dois = [
        dict(EXTRATO[0], description="COMPRA 4512 MAKRO", balance=3127.11),
        dict(EXTRATO[0], description="COMPRA 9910 MAKRO", balance=3061.31),
    ]

    ins, _s, absorvidas = _corre(server._fin_guardar_movimentos_do_banco(
        CONTA, dois, "bank_email", provisorio=False))

    assert (ins, absorvidas) == (2, 1), "a mesma linha dela foi absorvida duas vezes"
    assert len(movs.guardados) == 2


def test_um_aviso_nao_absorve_nada_porque_nao_traz_saldo(monkeypatch):
    # O caminho inverso: chega o aviso DEPOIS de a linha dela existir. O aviso
    # não é a verdade — não pode comer a linha dela.
    movs = _base(monkeypatch, [DELA])
    aviso = [{"date_lancamento": "2026-09-04", "description": "COMPRA MAKRO",
              "amount": -65.8, "balance": None}]

    _i, _s, absorvidas = _corre(server._fin_guardar_movimentos_do_banco(
        CONTA, aviso, "bank_email", provisorio=True))

    assert absorvidas == 0
    assert any(d["id"] == "sua" for d in movs.guardados), "o aviso comeu a linha dela"
