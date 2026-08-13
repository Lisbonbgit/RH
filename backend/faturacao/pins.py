"""PIN de 4 dígitos usado para entrar no POS.

Guardado com bcrypt, como as palavras-passe. Um PIN de 4 dígitos tem só 10.000
combinações, por isso o índice único (loja_id, pin_hash) não impede colisões
entre lojas — impede repetidos DENTRO da mesma loja, que é o que interessa para
saber quem fez cada venda.
"""
import re

import bcrypt

_SO_DIGITOS = re.compile(r"^\d{4}$")


def normalizar_pin(bruto) -> str:
    pin = str(bruto or "").strip()
    if not _SO_DIGITOS.match(pin):
        raise ValueError("O PIN tem de ter exactamente 4 dígitos.")
    return pin


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(normalizar_pin(pin).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def pin_valido(pin: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(str(pin).encode("utf-8"), str(hash_guardado).encode("utf-8"))
    except (ValueError, TypeError):
        return False
