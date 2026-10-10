"""Textos do CRM: aparar as pontas e comparar sem acentos nem maiúsculas
(crm/dominio/texto.py).

`aparar` é a porta de src/Dominio/Texto.php, com todos os casos do
tests/Unit/Dominio/TextoTest.php: os textos que vêm da API perdem os espaços
das pontas, também os Unicode — o mesmo que o String.prototype.trim() do
browser. Armadilhas do Python (plano §9): o str.strip() não tira o U+FEFF e o
`$` das expressões regulares aceita um "\\n" final.

`chave_comparacao` substitui a collation utf8mb4_unicode_ci do MariaDB do CRM
autónomo: ordenar os membros por nome (T1.6) e as regiões (T2.9) e detetar
regiões repetidas (`nome_chave`, F2) sem acentos nem maiúsculas.
"""
import sys
import unicodedata

import pytest

from crm.dominio.texto import aparar, chave_comparacao


@pytest.mark.parametrize(
    "texto, aparado",
    [
        ("Loja", "Loja"),
        (" \t\nLoja \r\n", "Loja"),
        (" Loja ", "Loja"),
        ("　Loja", "Loja"),
        ("Loja ", "Loja"),
        ("﻿Loja", "Loja"),
        ("Loja ", "Loja"),
        ("\t  　﻿", ""),
        ("", ""),
        ("  Café do  Zé ", "Café do  Zé"),
        (" Óbidos é ", "Óbidos é"),
    ],
    ids=[
        "sem espaços",
        "espaços, tabulações e mudanças de linha",
        "espaço sem quebra (U+00A0)",
        "espaço ideográfico (U+3000)",
        "espaço em m (U+2003)",
        "espaço sem largura do BOM (U+FEFF)",
        "separador de linha (U+2028)",
        "só espaços",
        "vazio",
        "os espaços do meio ficam",
        "acentos nas pontas ficam",
    ],
)
def test_aparar_tira_os_espacos_das_pontas(texto, aparado):
    assert aparar(texto) == aparado


def test_o_strip_do_python_nao_tira_o_bom_e_o_aparar_tira():
    # A razão de existir o aparar (plano §9).
    assert "﻿Loja﻿".strip() != "Loja"
    assert aparar("﻿Loja﻿") == "Loja"


def test_aparar_tira_a_mudanca_de_linha_final():
    # O "\n" final é ele próprio um espaço e sai (o `$` do Python também
    # aceitaria antes dele; a expressão usa `\Z` para não depender disso).
    assert aparar("Loja\n") == "Loja"
    assert aparar("Loja \n") == "Loja"


def test_aparar_tira_todos_os_separadores_unicode_como_o_php():
    # O PHP apara [\s\p{Z}\x{FEFF}]: todos os caracteres das categorias Zs,
    # Zl e Zp (há 19 no Unicode do Python 3.11) têm de sair das pontas.
    separadores = [
        chr(i) for i in range(sys.maxunicode + 1) if unicodedata.category(chr(i)) in ("Zs", "Zl", "Zp")
    ]
    assert len(separadores) >= 17
    for s in separadores:
        assert aparar(f"{s}{s}Loja{s}") == "Loja", f"U+{ord(s):04X}"


def test_aparar_nao_toca_nos_caracteres_invisiveis_que_nao_sao_espacos():
    # O espaço de largura zero (U+200B) e o joiner (U+200D) não são espaços
    # nem para o PHP nem para o trim() do browser.
    assert aparar("​Loja‍") == "​Loja‍"


@pytest.mark.parametrize(
    "a, b",
    [
        ("  Setúbal ", "SETUBAL"),
        ("Évora", "evora"),
        ("São Brás de Alportel", "sao bras de alportel"),
        ("Açores", "ACORES"),
        ("﻿Loja ", "loja"),
        ("Straße", "STRASSE"),
        ("ＬＯＪＡ", "loja"),
    ],
    ids=[
        "acento, maiúsculas e espaços nas pontas",
        "acento agudo na maiúscula",
        "til e acento agudo",
        "cedilha",
        "espaços unicode nas pontas",
        "s agudo alemão",
        "letras de largura total",
    ],
)
def test_chave_de_comparacao_ignora_acentos_maiusculas_e_pontas(a, b):
    assert chave_comparacao(a) == chave_comparacao(b)


@pytest.mark.parametrize(
    "a, b",
    [("Setúbal", "Setúbal Norte"), ("Loja 1", "Loja 2"), ("Sé", "Se nova"), ("ana", "anna")],
    ids=["mais palavras", "algarismos diferentes", "prefixo", "letra a mais"],
)
def test_nomes_diferentes_continuam_diferentes(a, b):
    assert chave_comparacao(a) != chave_comparacao(b)


def test_os_espacos_do_meio_contam():
    # Como no aparar: só as pontas saem.
    assert chave_comparacao("Café Central") != chave_comparacao("CaféCentral")


def test_a_chave_e_texto_sem_acentos_em_minusculas():
    assert chave_comparacao("  Setúbal ") == "setubal"


def test_ordenar_por_chave_poe_os_acentos_no_sitio_certo():
    # Sem chave, "Álvaro" ficava depois de "Zé" (o "Á" vem depois do "Z" em
    # Unicode) e "beatriz" depois de "Zé" (minúsculas depois das maiúsculas).
    nomes = ["Zé", "Ana", "Álvaro", "beatriz", "Óscar"]
    assert sorted(nomes) != ["Álvaro", "Ana", "beatriz", "Óscar", "Zé"]
    assert sorted(nomes, key=chave_comparacao) == ["Álvaro", "Ana", "beatriz", "Óscar", "Zé"]
