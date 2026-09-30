"""Travão à força bruta no login, só stdlib, em memória.

Conta só as FALHAS (as lojas partilham o IP do router: dez colaboradores a
entrar ao mesmo tempo não são um ataque). Vive em cada worker (há 2), por isso
o teto real é o dobro — chega para tornar o ataque impraticável; o que tem de
ser exato (as tentativas do código de recuperação) vive na base.
"""
import time
from collections import deque
from typing import Optional

from fastapi import Request

MENSAGEM = "Demasiadas tentativas falhadas. Aguarde uns minutos e tente de novo."
_falhas: dict = {}


def ip_do_cliente(request: Request) -> str:
    """IP real atrás de Caddy → nginx.

    O Caddy põe o IP do cliente no X-Forwarded-For e o nginx do frontend junta
    o do Caddy no fim: "cliente, caddy". O real é o PENÚLTIMO. O que o cliente
    escrever vai para a esquerda e nunca lá chega — ler o primeiro deixava o
    atacante escolher o IP (ver o `trust proxy` do Menooo)."""
    partes = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(partes) >= 2:
        return partes[-2]
    if partes:
        return partes[0]
    return request.client.host if request.client else "?"


def _fila(chave, janela_s: int, agora: float) -> deque:
    fila = _falhas.setdefault(chave, deque())
    while fila and agora - fila[0] >= janela_s:
        fila.popleft()
    return fila


def bloqueado(chave, limite: int, janela_s: int, agora: Optional[float] = None) -> bool:
    agora = time.monotonic() if agora is None else agora
    return len(_fila(chave, janela_s, agora)) >= limite


def falhou(chave, janela_s: int, agora: Optional[float] = None) -> None:
    agora = time.monotonic() if agora is None else agora
    _fila(chave, janela_s, agora).append(agora)
    if len(_falhas) > 50_000:
        # ponytail: poda grosseira quando engorda; filas vazias já não travam nada.
        for k in [k for k, q in _falhas.items() if not q or agora - q[-1] >= janela_s]:
            _falhas.pop(k, None)


def perdoa(chave) -> None:
    """Devolve a vaga reservada por um pedido que afinal acertou."""
    fila = _falhas.get(chave)
    if fila:
        fila.pop()
