"""Ajudantes dos testes do calendário (importar com `from .apoio import ...`)."""
import asyncio

# As rotas testam-se chamando as funções directamente; quem pede é um administrador.
ADMIN = {"user_id": "u-admin", "role": "admin", "email": "admin@example.com", "employee_id": None}


def corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)
