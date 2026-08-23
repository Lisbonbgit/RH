"""A ÚNICA parte deste programa que fala com o Windows.

São duas funções e mais nada, e é deliberado: tudo o que decide seja o que
for — buscar trabalho, a ordem, repetir, o que dizer quando falha — está em
`nucleo.py`, que corre e se testa em qualquer máquina. **Este ficheiro não se
consegue provar num Mac**, e por isso é o mais pequeno possível.

Quem o prova é o dono, com o botão «Imprimir página de teste».

## O QUE É "EM CRU", E PORQUE É QUE É O TUDO DISTO

Uma impressora de talões não recebe uma imagem da página: recebe **bytes de
comando** (ESC/POS) que ela própria interpreta — «reinicia», «escreve isto»,
«corta o papel», «abre a gaveta». Se o driver do Windows tratar esses bytes
como um documento normal, ele DESENHA-OS: sai uma folha cheia de letras e
sinais soltos em vez do talão, e a gaveta não abre.

`StartDocPrinter` com o tipo de dados **"RAW"** é o que diz ao spooler «não
lhe toques, passa isto à impressora tal e qual». É a linha que interessa
neste ficheiro inteiro.

**E não chega sempre.** Se a impressora estiver instalada no Windows com um
driver gráfico (o "Generic / Text Only" ou o driver da Epson em modo página),
o driver pode continuar a desenhar. Isso resolve-se nas definições da
impressora, no Windows, e não aqui — ver INSTALAR-IMPRESSAO.md. A página de
teste é o que distingue os dois casos num clique.
"""

# `win32print` só existe no Windows. O import falha aqui, no Mac, e tem de
# falhar de uma maneira que deixe o resto do programa importar-se à mesma —
# senão nem os testes do `nucleo.py` corriam.
try:
    import win32print
except ImportError:  # pragma: no cover — no Windows nunca acontece
    win32print = None


class SemWindows(Exception):
    """Este programa foi aberto fora do Windows. Não há impressão nenhuma."""


def _exigir_win32print():
    if win32print is None:
        raise SemWindows(
            "Este programa só imprime no Windows (falta o win32print). "
            "É normal ao correr os testes noutra máquina.")


def listar_impressoras():
    """Os nomes das impressoras instaladas neste Windows.

    É esta lista que o funcionário vê nas Definições para escolher qual é a
    da caixa e qual é a da cozinha. **Escolhe-se de uma lista e nunca se
    escreve à mão**: um nome com uma letra trocada dava um programa que
    parece configurado e nunca imprime nada.

    `PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS` é o par que apanha as
    duas maneiras de uma impressora existir neste PC: instalada aqui (a USB
    do balcão) e ligada a partir daqui (uma de rede que alguém partilhou).
    Como o dono tem as duas instaladas no mesmo PC, na prática é a primeira
    que conta — mas pedir só essa deixava de fora uma loja onde alguém as
    tivesse montado de outra maneira, e a lista vazia não explica porquê.
    """
    _exigir_win32print()
    sinalizadores = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    # Cada item é (flags, descrição, NOME, comentário) — o nome é o índice 2,
    # e é ele que `imprimir_em_cru` recebe.
    return sorted({info[2] for info in win32print.EnumPrinters(sinalizadores)})


def imprimir_em_cru(nome_impressora: str, dados: bytes) -> None:
    """Manda estes bytes para esta impressora, sem o Windows lhes tocar.

    É a função inteira. Tudo o que este programa faz de irreversível acontece
    nestas oito linhas.

    O `try/finally` não é cerimónia: um `OpenPrinter` sem `ClosePrinter`
    deixa um handle preso, e ao fim de umas centenas de talões o PC do balcão
    deixa de conseguir abrir a impressora — no meio de um dia de trabalho,
    sem nada no ecrã a dizer porquê. O mesmo para o documento e a página.

    **Isto não prova que o papel saiu.** Devolver sem erro quer dizer que os
    bytes foram entregues ao spooler do Windows: a impressora pode estar sem
    papel, desligada, ou com a tampa aberta. É por isso que o servidor trata
    um trabalho confirmado como "entregue" e não como "lido pelo cliente", e
    é por isso que a fila prefere repetir a desistir.
    """
    _exigir_win32print()
    handle = win32print.OpenPrinter(nome_impressora)
    try:
        # O terceiro campo é o TIPO DE DADOS, e "RAW" é a razão de existir
        # deste ficheiro (ver a docstring do módulo).
        win32print.StartDocPrinter(handle, 1, ("Talao", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, dados)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)
