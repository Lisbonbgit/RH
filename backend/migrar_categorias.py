"""Migração única das categorias das faturas (2026-09).

`mercadoria` passa a `fornecedor` e `energia_agua` a `utilitarios`, para que a
Conciliação e o relatório de Resultados falem a mesma língua. Corre em ensaio
por omissão; só escreve com `--aplicar`.

    cd backend && ./.venv/bin/python migrar_categorias.py            # ensaio
    cd backend && ./.venv/bin/python migrar_categorias.py --aplicar  # a sério
"""
import asyncio
import os
import sys

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402

MAPA_CATEGORIAS = {
    "mercadoria": "fornecedor",
    "energia_agua": "utilitarios",
    "rendas": "rendas",
    "salarios": "salarios",
    "servicos": "servicos",
    "impostos": "impostos",
    "outros": "outros",
}


def categoria_migrada(valor):
    """Categoria nova, ou None se a fatura estava por classificar.

    Por classificar continua por classificar: mandá-la para "Outros" escondia
    trabalho por fazer atrás de um número que parece completo."""
    if not valor:
        return None
    return MAPA_CATEGORIAS.get(valor, "outros")


async def _correr(aplicar: bool):
    faturas = await server.db.fin_invoices.find(
        {"category": {"$nin": [None, ""]}}, {"_id": 0, "id": 1, "category": 1}
    ).to_list(50000)
    mudancas = {}
    for inv in faturas:
        antiga = inv.get("category")
        nova = categoria_migrada(antiga)
        if nova and nova != antiga:
            mudancas.setdefault((antiga, nova), []).append(inv["id"])
    total = sum(len(v) for v in mudancas.values())
    for (antiga, nova), ids in sorted(mudancas.items()):
        print(f"  {antiga} -> {nova}: {len(ids)} faturas")
    print(f"{'A APLICAR' if aplicar else 'ENSAIO'}: {total} faturas a mudar de categoria")
    if not aplicar:
        print("Nada foi escrito. Corre outra vez com --aplicar.")
        return
    for (antiga, nova), ids in mudancas.items():
        await server.db.fin_invoices.update_many(
            {"id": {"$in": ids}}, {"$set": {"category": nova}}
        )
    print(f"Feito: {total} faturas reescritas.")


if __name__ == "__main__":
    asyncio.run(_correr("--aplicar" in sys.argv))
