"""Textos: aparar as pontas e comparar sem acentos nem maiúsculas.

`aparar` é a porta de src/Dominio/Texto.php do CRM autónomo: os textos que
vêm da API (nomes, moradas…) guardam-se sem espaços nas pontas, contando os
espaços Unicode (U+00A0, U+3000, U+2028…) e o U+FEFF — o mesmo que o
String.prototype.trim() do browser. Assim um nome feito só desses espaços
fica vazio, e não uma etiqueta invisível no mapa.

`chave_comparacao` faz o papel da collation utf8mb4_unicode_ci do MariaDB do
CRM autónomo, sem depender de collation no Mongo (plano §1, "Regiões"):
ordenar por nome em Python e detetar nomes repetidos (`nome_chave`, F2).
"""
import re
import unicodedata

# O \s do Python, em texto, já apanha todos os separadores Unicode (Zs, Zl,
# Zp — o \p{Z} do PHP), mas NÃO o U+FEFF nem o U+180E (separador de vogais
# mongol: deixou de ser espaço no Unicode 6.3, mas o \s do PCRE2 do PHP ainda
# o tira — conferido no PHP 8.4.26 em todos os pontos de código, revisão da
# F2); daí a classe [\s\u180e\ufeff]. \Z e não `$`, que também aceita antes de
# um "\n" final. (Apanha ainda U+001C–U+001F, separadores de controlo que o
# PHP não tira: a única diferença assumida, e nas pontas tanto faz.)
_PONTAS = re.compile(r"^[\s\u180e\ufeff]+|[\s\u180e\ufeff]+\Z")


def aparar(texto: str) -> str:
    """O texto sem espaços nas pontas (também os Unicode); os do meio ficam."""
    return _PONTAS.sub("", texto)


def chave_comparacao(texto: str) -> str:
    """Chave para ordenar e comparar textos sem acentos nem maiúsculas.

    Aparado, decomposto por compatibilidade (NFKD: "é" → "e" + acento, letras
    de largura total → normais), sem as marcas combinantes (os acentos) e em
    `casefold` ("ß" → "ss"). Os espaços do meio contam.
    """
    decomposto = unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", aparar(texto)).casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))
