"""O programa de impressão da loja — o que leva os talões da fila ao papel.

Três ficheiros e uma regra:

- `nucleo.py` — TUDO o que decide (buscar, ordenar, repetir, o que dizer
  quando falha). Corre e testa-se em qualquer máquina.
- `windows.py` — a ÚNICA parte que fala com o Windows: duas funções. Não se
  prova em lado nenhum a não ser à frente de uma impressora.
- `agente.py` — a janela e o ciclo.

Correr durante o desenvolvimento:  python -m agente_impressao
Compilar o .exe:                   ver INSTALAR-IMPRESSAO.md
"""
