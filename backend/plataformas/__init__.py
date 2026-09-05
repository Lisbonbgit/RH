"""Módulo Plataformas — o relatório de segunda-feira da Uber Eats, da Bolt Food
e da Glovo.

Todas as segundas às 08:00 lê a caixa de email, encontra os relatórios que as
plataformas mandam de madrugada, e envia um email só com o que interessa: o
que vamos receber de cada uma, quantos pedidos foram, o que nos foi cobrado e
os problemas que os relatórios assinalam. A Glovo leva sempre o calendário da
quinzena, que não depende de email nenhum ter chegado.

Vive como pacote próprio, e não dentro do `server.py`, pela mesma razão que o
`faturacao`: o `server.py` já tem mais de oito mil linhas, e uma avaria aqui
não pode derrubar o RH, o Financeiro nem a Faturação.

**Não tem `arrancar()` e não cria índices** — a idempotência deste módulo está
no `_id` do Mongo, que é único sem ninguém declarar nada. Ver a docstring de
`rotas.py`.
"""
from fastapi import APIRouter

from .rotas import router as _rotas

router = APIRouter(prefix="/api/plataformas", tags=["plataformas"])
router.include_router(_rotas)
