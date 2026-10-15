"""Testes do calendário das lojas.

As variáveis de ambiente têm de existir ANTES de qualquer `import server`: o pytest
colecciona `tests/calendario` antes de `tests/crm` e `tests/faturacao`, cujos conftest
as definem (ler o docstring de tests/crm/conftest.py). Os valores são exactamente os
mesmos, e `setdefault` nunca sobrepõe um valor que já lá esteja.
"""
import os

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
