"""O ponto de entrada do `.exe` do programa de impressão da loja.

Existe na raiz e não dentro de `agente_impressao/` por uma razão prática: o
PyInstaller põe a pasta DO SCRIPT no sys.path, e o pacote só se importa se
essa pasta for a raiz do repositório. Três linhas aqui poupam um truque de
caminhos no ficheiro de compilação.

    python arrancar.py          — correr durante o desenvolvimento
    pyinstaller agente.spec     — compilar o .exe (ver INSTALAR-IMPRESSAO.md)
"""
from agente_impressao.agente import main

if __name__ == "__main__":
    main()
