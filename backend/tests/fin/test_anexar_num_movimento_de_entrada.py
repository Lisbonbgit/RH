"""**Uma ENTRADA também tem direito a documento.**

No Extrato, o botão de anexar e o de ligar fatura só aparecem em movimentos com
`amount < 0`. A Conciliação mostra o mês inteiro, e metade do que interessa à
diretora financeira são entradas: Glovo, Uber, fecho de TPA. Se alguém levar a
regra do ecrã para o servidor, essas linhas ficam sem forma de guardar o
comprovativo.

Este teste existe para essa regra nunca lá chegar.
"""
import asyncio
import io
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, guardados):
        self.guardados = [dict(d) for d in guardados]

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def update_one(self, filtro, update):
        for doc in self.guardados:
            if doc.get("id") == filtro.get("id"):
                doc.update(update.get("$set", {}))


class BaseFalsa:
    def __init__(self, movimentos):
        self.fin_movements = movimentos


class FicheiroFalso:
    """O mínimo do UploadFile que o endpoint usa: só o `.file`."""

    def __init__(self, dados=b"%PDF-1.4 teste"):
        self.file = io.BytesIO(dados)
        self.filename = "comprovativo.pdf"


def test_anexar_a_uma_entrada_do_glovo_funciona(monkeypatch, tmp_path):
    movimentos = ColeccaoFalsa([
        {"id": "m1", "company_id": "e1", "amount": 3633.00, "description": "Glovo"},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))
    monkeypatch.setattr(server, "UPLOAD_DIR", tmp_path)

    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)

    _corre(server.fin_attach_movement("m1", FicheiroFalso(), {"user_id": "u1"}))

    assert movimentos.guardados[0]["attachment_path"], (
        "o anexo foi recusado numa entrada — a regra do ecrã chegou ao servidor"
    )
    assert (tmp_path / "fin_movements" / "m1.pdf").exists()
