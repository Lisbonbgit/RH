"""Regras das regiões: o nome, a ordem e a chave dos repetidos (crm/dominio/regioes.py).

`erro_nome` e `erro_ordem` são a porta de src/Dominio/Regioes/RegrasRegioes.php
do CRM autónomo, com todos os casos do tests/Unit/Dominio/RegrasRegioesTest.php
e os mesmos nomes nos `ids`. `criacao` e `alteracao` são a porta do
`RegioesControlador::validar` (o nome aparado, o que não é texto fica vazio, só
as chaves enviadas; na criação a ordem é 0 por omissão), com os casos de
validação do tests/Integration/Api/RegioesTest.php: assim a rota (T2.9) só lê,
grava e responde. `nome_chave` faz o papel da collation utf8mb4_unicode_ci da
chave única do MariaDB (plano §1 "Regiões"; dossiê §5.8): com ela, o índice
único em `nome_chave` recusa "Setubal" depois de "Setúbal".

A ordem dos dicionários conta (é a ordem dos erros no ecrã), por isso
compara-se `list(….items())`; o tipo também (o `assertSame` do PHP: a ordem
0 é o `int` 0, nunca 0.0 nem False).
"""
import copy
import json

import pytest

from crm.dominio import regioes
from crm.dominio.regioes import (
    NOME_MAXIMO,
    ORDEM_MAXIMA,
    ORDEM_MINIMA,
    alteracao,
    criacao,
    erro_nome,
    erro_ordem,
    nome_chave,
)
from crm.dominio.texto import chave_comparacao

ORDEM_INVALIDA = "A ordem tem de ser um número inteiro."
NOME_VAZIO = "Indique o nome."
NOME_COMPRIDO = "O nome tem no máximo 100 caracteres."


def pares(resultado):
    """`(campos, erros)` como listas de pares: a ordem conta."""
    campos, erros = resultado
    return list(campos.items()), list(erros.items())


def mesmo_valor(a, b):
    """O `assertSame` do PHP: o mesmo valor e o mesmo tipo (True não é 1, 0 não é 0.0)."""
    return type(a) is type(b) and a == b


# --- Constantes ---


def test_os_limites_sao_os_da_coluna_do_autonomo():
    # NOME_MAXIMO é o tamanho da coluna nome; a ordem era um INT do MariaDB.
    assert NOME_MAXIMO == 100
    assert ORDEM_MINIMA == -(2**31)
    assert ORDEM_MAXIMA == 2**31 - 1
    assert all(type(limite) is int for limite in (NOME_MAXIMO, ORDEM_MINIMA, ORDEM_MAXIMA))


def test_as_mensagens_sao_as_do_contrato():
    assert regioes.MENSAGEM_NOME == NOME_VAZIO
    assert regioes.MENSAGEM_ORDEM == ORDEM_INVALIDA


# --- RegrasRegioesTest.php: o nome ---


@pytest.mark.parametrize(
    "nome, erro",
    [
        ("", NOME_VAZIO),
        ("Lisboa", None),
        ("Setúbal", None),
        ("é" * 100, None),
        ("a" * 101, NOME_COMPRIDO),
    ],
    ids=["vazio", "normal", "com acentos", "100 caracteres (com acentos, contam como um)", "101 caracteres"],
)
def test_valida_o_nome(nome, erro):
    assert erro_nome(nome) == erro


@pytest.mark.parametrize(
    "nome, erro",
    [
        ("😀" * 100, None),
        ("😀" * 101, NOME_COMPRIDO),
        ("é" * 50, None),
        ("é" * 50 + "a", NOME_COMPRIDO),
        ("\ud800" * 100, None),
        ("a" * 1000, NOME_COMPRIDO),
    ],
    ids=[
        "100 emojis cabem (o mb_strlen conta caracteres, não bytes)",
        "101 emojis não cabem",
        "acento combinante conta como um carácter à parte, como no mb_strlen",
        "101 com acentos combinantes",
        "surrogates sozinhos contam um cada um, sem rebentar",
        "muito comprido",
    ],
)
def test_o_tamanho_do_nome_conta_caracteres_como_o_mb_strlen(nome, erro):
    assert erro_nome(nome) == erro


def test_o_nome_chega_ja_aparado_e_erro_nome_nao_apara():
    # Como no PHP ("o nome chega já sem espaços nas pontas"): quem apara é
    # a criacao/alteracao. Só espaços, aqui, não é vazio.
    assert erro_nome("   ") is None
    assert erro_nome(" " * 101) == NOME_COMPRIDO


@pytest.mark.parametrize("nome", [None, 42, True, ["Lisboa"], {"nome": "Lisboa"}], ids=["nulo", "número", "booleano", "lista", "objeto"])
def test_um_nome_que_nao_e_texto_e_um_erro_de_programacao(nome):
    # O `string $nome` do PHP em modo estrito dava TypeError; a criacao e a
    # alteracao convertem antes o que não é texto em "".
    with pytest.raises(TypeError):
        erro_nome(nome)


# --- RegrasRegioesTest.php: a ordem ---


@pytest.mark.parametrize(
    "ordem",
    [0, 3, -1, 2147483647, -2147483648],
    ids=["zero", "positiva", "negativa", "a maior de um INT", "a menor de um INT"],
)
def test_aceita_ordens_inteiras_que_cabem_na_coluna(ordem):
    assert erro_ordem(ordem) is None


@pytest.mark.parametrize(
    "ordem",
    ["1", 1.5, 1.0, None, True, [1], 2147483648, -2147483649],
    ids=[
        "texto com um número",
        "decimal",
        "decimal redondo",
        "nulo",
        "verdadeiro",
        "lista",
        "acima de um INT",
        "abaixo de um INT",
    ],
)
def test_recusa_o_que_nao_for_um_inteiro_da_coluna(ordem):
    assert erro_ordem(ordem) == ORDEM_INVALIDA


@pytest.mark.parametrize(
    "ordem",
    [False, 0.0, -0.0, 2**63, -(2**63) - 1, 10**400, {"ordem": 1}, "", " 1", "١"],
    ids=[
        "falso (em Python é o int 0)",
        "zero decimal",
        "menos zero",
        "fora dos 64 bits (o PHP lia um float)",
        "abaixo dos 64 bits",
        "enorme",
        "objeto",
        "texto vazio",
        "texto com espaço",
        "algarismo árabe",
    ],
)
def test_armadilhas_do_python_na_ordem(ordem):
    assert erro_ordem(ordem) == ORDEM_INVALIDA


@pytest.mark.parametrize(
    "texto_json",
    ["NaN", "Infinity", "-Infinity", "1e400", "1E2", "2.0", "true", "false", "null", "2147483648", "9223372036854775808"],
)
def test_a_ordem_lida_pelo_json_loads_so_conta_se_for_um_inteiro_da_coluna(texto_json):
    # O json do Python aceita NaN e Infinity (o do PHP não) e lê 1E2 e 2.0
    # como float: nenhum é um inteiro do JSON.
    assert erro_ordem(json.loads(texto_json)) == ORDEM_INVALIDA


@pytest.mark.parametrize("texto_json, ordem", [("0", 0), ("-0", 0), ("7", 7), ("-2147483648", -2147483648)])
def test_os_inteiros_do_json_contam(texto_json, ordem):
    lida = json.loads(texto_json)
    assert mesmo_valor(lida, ordem)
    assert erro_ordem(lida) is None


# --- nome_chave: os repetidos sem maiúsculas nem acentos ---


@pytest.mark.parametrize(
    "a, b",
    [
        ("Lisboa", "Lisboa"),
        ("Lisboa", "LISBOA"),
        ("Setúbal", "Setubal"),
        ("Setúbal", "setubal"),
        ("Évora", "EVORA"),
        ("Santarém", "santarem"),
        ("Bragança", "braganca"),
        ("Ｌｉｓｂｏａ", "lisboa"),
        ("Setúbal", "Setúbal"),
    ],
    ids=[
        "igual",
        "maiúsculas",
        "sem o acento",
        "sem o acento e em minúsculas",
        "acento na maiúscula",
        "acento agudo no meio",
        "cedilha",
        "letras de largura total",
        "acento combinante (NFD) e acento composto (NFC)",
    ],
)
def test_nomes_que_so_diferem_em_maiusculas_ou_acentos_tem_a_mesma_chave(a, b):
    assert nome_chave(a) == nome_chave(b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Lisboa", "Lisboa Norte"),
        ("Porto", "Porto 2"),
        ("Vila Real", "Vila  Real"),
        ("Vila Real", "VilaReal"),
        ("Sé", "Se nova"),
    ],
    ids=["mais uma palavra", "algarismo a mais", "dois espaços no meio", "sem o espaço do meio", "prefixo"],
)
def test_nomes_diferentes_tem_chaves_diferentes(a, b):
    assert nome_chave(a) != nome_chave(b)


def test_a_chave_e_a_chave_de_comparacao_do_texto():
    # A mesma regra que ordena os nomes (T1.3, T2.9): uma só, para que o
    # índice único e a ordem no ecrã nunca discordem.
    for nome in ["Setúbal", "  Évora ", "Ｌｉｓｂｏａ", "Straße", "Açores e Madeira"]:
        assert nome_chave(nome) == chave_comparacao(nome)
    assert nome_chave("Setúbal") == "setubal"
    assert type(nome_chave("Setúbal")) is str


# --- RegioesControlador::validar → criacao (POST) ---


def test_cria_com_o_nome_aparado_e_a_ordem():
    # RegioesTest::oAdminCriaUmaRegiao: "  Lisboa  " → "Lisboa".
    assert pares(criacao({"nome": "  Lisboa  ", "ordem": 3})) == ([("nome", "Lisboa"), ("ordem", 3)], [])


def test_sem_ordem_a_nova_regiao_fica_com_zero():
    # RegioesTest::semOrdemANovaRegiaoFicaComZero.
    campos, erros = criacao({"nome": "Porto"})

    assert erros == {}
    assert list(campos.items()) == [("nome", "Porto"), ("ordem", 0)]
    assert mesmo_valor(campos["ordem"], 0)


@pytest.mark.parametrize(
    "corpo, erros",
    [
        ({}, [("nome", NOME_VAZIO)]),
        ({"nome": "", "ordem": 1}, [("nome", NOME_VAZIO)]),
        ({"nome": "   "}, [("nome", NOME_VAZIO)]),
        ({"nome": " 　"}, [("nome", NOME_VAZIO)]),
        ({"nome": 42}, [("nome", NOME_VAZIO)]),
        ({"nome": "a" * 101}, [("nome", NOME_COMPRIDO)]),
        ({"nome": "Porto", "ordem": "2"}, [("ordem", ORDEM_INVALIDA)]),
        ({"nome": "Porto", "ordem": 1.5}, [("ordem", ORDEM_INVALIDA)]),
        ({"nome": "Porto", "ordem": None}, [("ordem", ORDEM_INVALIDA)]),
        ({"nome": "Porto", "ordem": 2147483648}, [("ordem", ORDEM_INVALIDA)]),
        ({"nome": " ", "ordem": False}, [("nome", NOME_VAZIO), ("ordem", ORDEM_INVALIDA)]),
    ],
    ids=[
        "corpo vazio",
        "nome vazio",
        "nome só com espaços",
        "nome só com espaços Unicode",
        "nome que não é texto",
        "nome com 101 caracteres",
        "ordem como texto",
        "ordem decimal",
        "ordem nula",
        "ordem acima de um INT",
        "os dois",
    ],
)
def test_criar_com_campos_invalidos_da_os_erros(corpo, erros):
    # RegioesTest::criarComCamposInvalidosDa422 (novasInvalidas).
    assert list(criacao(corpo)[1].items()) == erros


def test_na_criacao_um_nome_que_nao_e_texto_fica_vazio_nos_campos():
    assert pares(criacao({"nome": 42})) == ([("nome", ""), ("ordem", 0)], [("nome", NOME_VAZIO)])


# --- RegioesControlador::validar → alteracao (PATCH) ---


def test_sem_alteracoes_nao_ha_campos_nem_erros():
    assert pares(alteracao({})) == ([], [])


def test_o_patch_muda_o_nome_aparado():
    # RegioesTest::oPatchMudaONome.
    assert pares(alteracao({"nome": " Grande Lisboa "})) == ([("nome", "Grande Lisboa")], [])


def test_o_patch_muda_so_a_ordem():
    # RegioesTest::oPatchMudaAOrdemEAListaSegueANova.
    campos, erros = alteracao({"ordem": 0})

    assert pares((campos, erros)) == ([("ordem", 0)], [])
    assert mesmo_valor(campos["ordem"], 0)


def test_o_patch_muda_o_nome_e_a_ordem_juntos_e_so_esses():
    # RegioesTest::oPatchMudaONomeEAOrdemJuntosESoEsses: o id do corpo ignora-se.
    assert pares(alteracao({"nome": "Lisboa e Vale do Tejo", "ordem": 7, "id": 99})) == (
        [("nome", "Lisboa e Vale do Tejo"), ("ordem", 7)],
        [],
    )


@pytest.mark.parametrize(
    "corpo, erros",
    [
        ({"nome": ""}, [("nome", NOME_VAZIO)]),
        ({"nome": None}, [("nome", NOME_VAZIO)]),
        ({"ordem": "primeira"}, [("ordem", ORDEM_INVALIDA)]),
        ({"nome": "Grande Lisboa", "ordem": None}, [("ordem", ORDEM_INVALIDA)]),
    ],
    ids=["nome vazio", "nome nulo", "ordem como texto", "um válido e um inválido (nada se grava)"],
)
def test_um_patch_com_valores_invalidos_da_os_erros(corpo, erros):
    # RegioesTest::umPatchComValoresInvalidosDa422 (alteracoesInvalidas).
    assert list(alteracao(corpo)[1].items()) == erros


@pytest.mark.parametrize("ordem", ["primeira", None, 1.5, [1]], ids=["texto", "nulo", "decimal", "lista"])
def test_com_erro_a_ordem_fica_nos_campos_tal_como_veio(ordem):
    # Como no PHP (`$campos['ordem'] = $corpo['ordem']`); com erros, os
    # campos não se gravam.
    campos, erros = alteracao({"ordem": ordem})

    assert list(erros.items()) == [("ordem", ORDEM_INVALIDA)]
    assert list(campos) == ["ordem"]
    assert campos["ordem"] is ordem or campos["ordem"] == ordem
    assert type(campos["ordem"]) is type(ordem)


def test_na_alteracao_o_nome_nulo_conta_como_enviado():
    # A chave conta, mesmo com null (o array_key_exists do PHP): limpar o
    # nome não é "não mexer no nome".
    assert pares(alteracao({"nome": None})) == ([("nome", "")], [("nome", NOME_VAZIO)])


# --- Armadilhas do Python na criacao e na alteracao ---


@pytest.mark.parametrize("validar", [criacao, alteracao], ids=["criacao", "alteracao"])
@pytest.mark.parametrize(
    "nome, aparado",
    [
        ("﻿Lisboa", "Lisboa"),
        ("Lisboa\n", "Lisboa"),
        (" Porto ", "Porto"),
        ("\t Vila  Real \r\n", "Vila  Real"),
        ("Setúbal", "Setúbal"),
    ],
    ids=["U+FEFF", "mudança de linha no fim", "separadores de linha e parágrafo", "espaços do meio ficam", "acento fica"],
)
def test_o_nome_perde_os_espacos_unicode_das_pontas(validar, nome, aparado):
    campos, erros = validar({"nome": nome, "ordem": 1})

    assert erros == {}
    assert campos["nome"] == aparado


@pytest.mark.parametrize("validar", [criacao, alteracao], ids=["criacao", "alteracao"])
@pytest.mark.parametrize("nome", [True, False, 0, 1.5, [], ["Lisboa"], {}, {"nome": "Lisboa"}], ids=["verdadeiro", "falso", "zero", "decimal", "lista vazia", "lista", "objeto vazio", "objeto"])
def test_um_nome_que_nao_e_texto_fica_vazio_e_da_indique_o_nome(validar, nome):
    campos, erros = validar({"nome": nome, "ordem": 1})

    assert campos["nome"] == ""
    assert list(erros.items()) == [("nome", NOME_VAZIO)]


@pytest.mark.parametrize("validar", [criacao, alteracao], ids=["criacao", "alteracao"])
def test_um_nome_aparado_com_100_caracteres_cabe(validar):
    nome = "  " + "ã" * 100 + "　"

    campos, erros = validar({"nome": nome})

    assert erros == {}
    assert campos["nome"] == "ã" * 100


@pytest.mark.parametrize("validar", [criacao, alteracao], ids=["criacao", "alteracao"])
@pytest.mark.parametrize("ordem", [True, False, 1.0, -0.0, 2**63, 10**400], ids=["verdadeiro", "falso", "decimal redondo", "menos zero", "64 bits", "enorme"])
def test_a_ordem_tem_de_ser_um_inteiro_do_json(validar, ordem):
    assert list(validar({"nome": "Porto", "ordem": ordem})[1].items()) == [("ordem", ORDEM_INVALIDA)]


@pytest.mark.parametrize("validar", [criacao, alteracao], ids=["criacao", "alteracao"])
def test_os_erros_vem_sempre_pela_ordem_nome_e_ordem(validar):
    # Mesmo com o corpo ao contrário: é a ordem dos campos no ecrã.
    campos, erros = validar({"ordem": False, "nome": " "})

    assert list(erros) == ["nome", "ordem"]
    assert list(campos) == ["nome", "ordem"]


@pytest.mark.parametrize("validar", [criacao, alteracao], ids=["criacao", "alteracao"])
def test_chaves_parecidas_e_campos_que_o_servidor_decide_ignoram_se(validar):
    corpo = {"Nome": "", " nome": "", "ORDEM": "x", "ordem ": None, "id": "r1", "nome_chave": "x", "nome": "Porto", "ordem": 2}

    assert pares(validar(corpo)) == ([("nome", "Porto"), ("ordem", 2)], [])


def test_na_alteracao_chaves_parecidas_nao_contam_como_enviadas():
    assert pares(alteracao({"Nome": "", "ORDEM": None})) == ([], [])


@pytest.mark.parametrize("validar", [criacao, alteracao], ids=["criacao", "alteracao"])
def test_o_corpo_nao_muda_e_cada_chamada_devolve_estruturas_novas(validar):
    corpo = {"nome": "  Porto ", "ordem": [1], "id": "r1"}
    antes = copy.deepcopy(corpo)

    primeiro = validar(corpo)
    segundo = validar(corpo)

    assert corpo == antes
    assert list(corpo) == list(antes)
    assert primeiro == segundo
    assert primeiro[0] is not segundo[0]
    assert primeiro[1] is not segundo[1]


def test_a_criacao_nao_acrescenta_os_padroes_ao_corpo():
    corpo = {"nome": "Porto"}

    criacao(corpo)

    assert corpo == {"nome": "Porto"}


def test_a_criacao_aceita_a_ordem_enviada_por_cima_da_omissao():
    # O `$pedido->json() + ['nome' => null, 'ordem' => 0]` do PHP: o que vem
    # no corpo ganha, mesmo um null.
    assert pares(criacao({"nome": "Porto", "ordem": -5})) == ([("nome", "Porto"), ("ordem", -5)], [])
    assert pares(criacao({"ordem": None, "nome": "Porto"}))[1] == [("ordem", ORDEM_INVALIDA)]
