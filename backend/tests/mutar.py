"""Prova por mutação: estraga UM pedaço de um ficheiro, corre o comando de teste, exige que
fique VERMELHO, e repõe SEMPRE o ficheiro (mesmo com Ctrl-C).

Regra da casa: um teste verde não vale nada até se o ver vermelho pela razão certa. Esta
ferramenta faz a parte mecânica; a razão certa lê-se na saída do pytest, que passa por aqui.

Uso (a partir de backend/):
    python tests/mutar.py <ficheiro> <texto-original> <texto-estragado> -- <comando de teste…>

Sai com 0 se o teste ficou vermelho (mutação apanhada), 1 se ficou verde, 2 se o texto a
estragar não aparece exactamente uma vez no ficheiro.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Neste Mac o bytecode vai para aqui; um .pyc do ficheiro estragado deixado lá envenena a
# corrida seguinte (já aconteceu). Limpa-se depois de repor.
_CACHE = Path.home() / "Library" / "Caches" / "com.apple.python"


def main(argv):
    if len(argv) < 5 or argv[3] != "--":
        print(__doc__)
        return 2
    caminho, original, estragado = argv[:3]
    comando = argv[4:]
    ficheiro = Path(caminho)
    antes = ficheiro.read_bytes()
    texto = antes.decode("utf-8")
    if texto.count(original) != 1:
        print("O texto a estragar aparece %d vezes em %s (tem de ser 1)." % (texto.count(original), caminho))
        return 2
    try:
        ficheiro.write_text(texto.replace(original, estragado), encoding="utf-8")
        resultado = subprocess.run(comando, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    finally:
        ficheiro.write_bytes(antes)
        shutil.rmtree(_CACHE, ignore_errors=True)
    if resultado.returncode == 0:
        print("\nMUTAÇÃO NÃO APANHADA: o teste ficou VERDE com o código estragado.")
        return 1
    print("\nMutação apanhada (o teste ficou vermelho). %s reposto." % caminho)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
