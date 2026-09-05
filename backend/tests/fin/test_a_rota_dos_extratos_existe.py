"""**A rota é a que o cron vai bater, não a que eu acho que escrevi.**

Já matou o POS três vezes neste repositório: afirmar o endereço que o código
escreve nunca apanha um prefixo errado. Pergunta-se ao router.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _caminhos(metodo):
    return {r.path for r in server.api_router.routes
            if metodo in getattr(r, "methods", set())}


def test_o_cron_dos_extratos_esta_servido():
    assert "/api/fin/cron/extratos" in _caminhos("POST")


def test_o_botao_do_painel_esta_servido():
    assert "/api/fin/sync/extratos" in _caminhos("POST")


def test_nao_colide_com_a_ingestao_das_faturas():
    # Duas portas diferentes, de propósito: as faturas vêm de qualquer
    # remetente, os extratos só dos bancos.
    posts = _caminhos("POST")
    assert "/api/fin/cron/ingest" in posts
    assert "/api/fin/cron/extratos" in posts
