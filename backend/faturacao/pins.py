"""PIN de 4 dígitos usado para entrar no POS.

Guardado com bcrypt, como as palavras-passe. Um PIN de 4 dígitos tem só 10.000
combinações, por isso NÃO há (nem pode haver) um índice único sobre pin_hash:
o bcrypt usa sal aleatório, logo duas pessoas com o mesmo PIN "1234" na mesma
loja têm pin_hash diferentes, e um índice de Mongo nunca detecta essa
duplicação (ver test_hash_muda_de_cada_vez em test_pins.py).

A unicidade do PIN dentro da mesma loja tem de ser garantida pelo SERVIDOR:
ao criar ou mudar um PIN, verifica-se com bcrypt.checkpw contra o pin_hash de
cada utilizador ACTIVO da mesma loja, e recusa-se se já existir alguém com
esse PIN. (Essa verificação é de outra tarefa — este módulo é só a lógica
pura de hash/verificação.)
"""
import re
from typing import Optional

import bcrypt

_SO_DIGITOS = re.compile(r"^\d{4}$")

# Formato de um hash bcrypt válido: $2a$, $2b$ ou $2y$ (variante do algoritmo),
# custo de 2 dígitos, e 53 caracteres do alfabeto base64 do bcrypt (sal + hash).
# Comprimento total fixo: 60 caracteres. Validar isto ANTES de chamar o bcrypt
# evita entregar-lhe um hash truncado — o bcrypt 4.1.3 (motor em Rust) levanta
# pyo3_runtime.PanicException nesse caso, que herda de BaseException e por
# isso NÃO é apanhado por um except (ValueError, TypeError).
_HASH_BCRYPT_VALIDO = re.compile(r"^\$2[aby]\$\d{2}\$[A-Za-z0-9./]{53}$")


def normalizar_pin(bruto) -> str:
    if bruto is None:
        bruto = ""
    pin = str(bruto).strip()
    if not _SO_DIGITOS.match(pin):
        raise ValueError("O PIN tem de ter exactamente 4 dígitos.")
    return pin


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(normalizar_pin(pin).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def pin_valido(pin, hash_guardado: Optional[str]) -> bool:
    """Verifica um PIN contra o hash guardado. Nunca levanta excepção — PIN
    ou hash inválidos devolvem simplesmente False (ao contrário de
    normalizar_pin, que levanta ValueError; aqui isso seria um 500 a meio de
    uma venda em vez de "PIN inválido")."""
    try:
        pin_normalizado = normalizar_pin(pin)
    except ValueError:
        return False

    if not isinstance(hash_guardado, str) or not _HASH_BCRYPT_VALIDO.match(hash_guardado):
        return False

    try:
        return bcrypt.checkpw(pin_normalizado.encode("utf-8"), hash_guardado.encode("utf-8"))
    except (ValueError, TypeError):
        # Segunda linha de defesa — não deve disparar se a validação de
        # formato acima estiver correcta, mas mantém-se por segurança.
        return False
