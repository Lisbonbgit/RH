#!/usr/bin/env python3
"""
Gera o hash bcrypt da password do admin principal.

Uso:
    python generate_admin_hash.py "A-Sua-Password-Forte"

Copie o resultado para a variável ADMIN_PASSWORD_HASH no ficheiro .env
"""
import sys
import bcrypt


def main():
    if len(sys.argv) != 2:
        print('Uso: python generate_admin_hash.py "A-Sua-Password"')
        sys.exit(1)

    password = sys.argv[1]
    if len(password) < 8:
        print("Aviso: use pelo menos 8 caracteres.")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    print("\nADMIN_PASSWORD_HASH para o .env:\n")
    print(hashed)
    print()


if __name__ == "__main__":
    main()
