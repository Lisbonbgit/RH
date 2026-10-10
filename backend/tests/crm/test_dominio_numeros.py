"""Números do JSON e o arredondamento do PHP (crm/dominio/numeros.py).

O CRM autónomo valida os números com `is_int` / `is_float` + `is_finite` e
arredonda com o `round()` do PHP (src/Dominio/Geo/PrecisaoGps.php,
Lojas/ValidadorLoja.php, Definicoes.php, Regioes/RegrasRegioes.php,
Geo/Duplicados.php). Em Python há três armadilhas (plano §9 e §10; dossiê
§2.1), e é para elas que este módulo existe:

- o `round()` do Python arredonda para o par: `round(50.5) == 50` aceitaria
  um GPS a 51 m; o do PHP vai para longe do zero (50,5 → 51);
- `True` é um `int` em Python, e o PHP nunca conta um bool como número;
- o `json` do Python aceita `NaN`, `Infinity` e `1e400` (→ inf), e lê
  inteiros de qualquer tamanho, que o PHP lia como `float` (ou INF).

Os valores da tabela "conferidos com o PHP" saíram do `round()` do PHP
8.4.26, o do CRM autónomo (`php -r 'var_export(round(0.285, 2));'` → 0.29).
"""
import json
import math

import pytest

from crm.dominio.numeros import arredondar, e_inteiro_json, e_numero_json


# --- arredondar: ao inteiro (o metro do GPS, a distância dos duplicados) ---


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (50.5, 51),
        (49.5, 50),
        (-0.5, -1),
        (0.5, 1),
        (1.5, 2),
        (2.5, 3),
        (-1.5, -2),
        (-2.5, -3),
        (50.4, 50),
        (50.49, 50),
        (49.99, 50),
        (-0.4, 0),
        (0.0, 0),
    ],
    ids=[
        "50,5 sobe para 51",
        "49,5 sobe para 50",
        "-0,5 desce para -1",
        "0,5 sobe para 1",
        "1,5 sobe para 2",
        "2,5 sobe para 3 (o Python dava 2)",
        "-1,5 desce para -2",
        "-2,5 desce para -3 (o Python dava -2)",
        "50,4 fica em 50",
        "50,49 fica em 50",
        "49,99 sobe para 50",
        "-0,4 fica em zero",
        "zero",
    ],
)
def test_arredondar_ao_inteiro_e_meio_para_longe_do_zero(valor, esperado):
    assert arredondar(valor) == esperado


def test_o_round_do_python_arredonda_para_o_par_e_o_arredondar_nao():
    # A razão de existir o arredondar (plano §9): com o round() do Python,
    # um GPS de 50,5 m contava como 50 e era aceite.
    assert round(50.5) == 50
    assert round(2.5) == 2
    assert arredondar(50.5) == 51
    assert arredondar(2.5) == 3


# --- arredondar: às 6 casas (as coordenadas que se guardam) ---


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (38.1234566, 38.123457),
        (38.1234564, 38.123456),
        (36.7999996, 36.8),
        (-9.13640049, -9.1364),
        (-9.1364005, -9.136401),
        (38.7075005, 38.707501),
        (0.1234565, 0.123457),
        (-38.1234565, -38.123457),
        (38.7075, 38.7075),
        (42.2, 42.2),
        (-6.1, -6.1),
        (5e-7, 0.000001),
        (4e-7, 0.0),
    ],
    ids=[
        "a sétima casa 6 sobe",
        "a sétima casa 4 fica",
        "sobe até ao limite sul de Portugal",
        "-9,13640049 fica em -9,1364",
        "meio negativo desce (longe do zero)",
        "meio positivo sobe (Praça do Comércio)",
        "meio perto do zero sobe",
        "meio negativo com a parte inteira",
        "já com 4 casas fica igual",
        "limite norte fica igual",
        "limite leste fica igual",
        "meio da sexta casa sobe",
        "abaixo do meio da sexta casa vai para zero",
    ],
)
def test_arredondar_as_6_casas_das_coordenadas(valor, esperado):
    assert arredondar(valor, 6) == esperado


def test_o_round_do_python_as_6_casas_engana_se_onde_o_php_nao():
    # 0.1234565 é, em binário, um pouco menos do que o meio: o round() do
    # Python desce, e o do PHP (como o arredondar) trata-o como o número que
    # se escreveu e sobe.
    assert round(0.1234565, 6) == 0.123456
    assert arredondar(0.1234565, 6) == 0.123457


@pytest.mark.parametrize(
    "valor, casas, php",
    [
        (50.5, 0, 51.0),
        (-0.5, 0, -1.0),
        (0.49999999999999994, 0, 0.0),
        (38.1234566, 6, 38.123457),
        (-9.1364005, 6, -9.136401),
        (0.285, 2, 0.29),
        (1.005, 2, 1.01),
        (1.0000005, 6, 1.000001),
        (123456789.1234565, 6, 123456789.123457),
        (1e15 + 0.5, 0, 1000000000000001.0),
        (4503599627370495.5, 0, 4503599627370496.0),
        (2.0**53, 6, 9007199254740992.0),
        (1e300, 6, 1e300),
        (1.7976931348623157e308, 6, 1.7976931348623157e308),
        (1e-300, 6, 0.0),
    ],
    ids=[
        "50,5",
        "-0,5",
        "o maior float abaixo de 0,5",
        "sétima casa 6",
        "meio negativo",
        "0,285 às 2 casas",
        "1,005 às 2 casas",
        "1,0000005 às 6 casas",
        "nove algarismos inteiros",
        "meio acima de 10^15",
        "meio no limite da precisão",
        "2^53 já sem casas",
        "muito grande",
        "o maior float",
        "muito pequeno",
    ],
)
def test_valores_conferidos_com_o_round_do_php(valor, casas, php):
    assert arredondar(valor, casas) == php


def test_devolve_sempre_um_float_como_o_round_do_php():
    # O round() do PHP devolve float também para inteiros (round(5, 6) → 5.0);
    # quem precisar de um int (precisao_m, distancia_m) converte, como o
    # `(int) round(…)` do autónomo.
    assert type(arredondar(50.5)) is float
    assert type(arredondar(5)) is float
    assert arredondar(5, 6) == 5.0
    assert arredondar(-3) == -3.0


@pytest.mark.parametrize(
    "valor",
    [True, False, None, "1", "50.5", math.inf, -math.inf, math.nan, [1], {"n": 1}, 10**400],
    ids=[
        "verdadeiro",
        "falso",
        "nulo",
        "texto de um inteiro",
        "texto de um decimal",
        "infinito",
        "menos infinito",
        "não é um número",
        "lista",
        "objeto",
        "inteiro maior do que qualquer float",
    ],
)
def test_arredondar_recusa_o_que_nao_e_um_numero_json(valor):
    # Quem chama verifica primeiro com e_numero_json; isto é a rede, para um
    # bool nunca virar 1.0 nem um inf passar calado.
    with pytest.raises(ValueError):
        arredondar(valor)


@pytest.mark.parametrize("casas", [-1, 1.0, True, "6", None], ids=["negativas", "decimal", "verdadeiro", "texto", "nulo"])
def test_arredondar_recusa_casas_que_nao_sejam_um_inteiro_de_zero_para_cima(casas):
    with pytest.raises(ValueError):
        arredondar(1.5, casas)


# --- e_numero_json: is_int || (is_float && is_finite) do PHP ---


@pytest.mark.parametrize(
    "valor",
    [0, 1, -1, 50, 1.5, -9.1364, 0.0, -0.0, 2**63, 10**308, 1.7976931348623157e308],
    ids=[
        "zero",
        "um",
        "menos um",
        "inteiro",
        "decimal",
        "decimal negativo",
        "zero decimal",
        "zero negativo",
        "inteiro fora dos 64 bits (o PHP lia float)",
        "inteiro do tamanho do maior float",
        "o maior float",
    ],
)
def test_e_numero_json_aceita_inteiros_e_decimais_finitos(valor):
    assert e_numero_json(valor) is True


@pytest.mark.parametrize(
    "valor",
    [True, False, None, "1", "1.5", "", math.inf, -math.inf, math.nan, [1], {"n": 1}, 10**400],
    ids=[
        "verdadeiro",
        "falso",
        "nulo",
        "texto de um inteiro",
        "texto de um decimal",
        "texto vazio",
        "infinito",
        "menos infinito",
        "não é um número",
        "lista",
        "objeto",
        "inteiro maior do que qualquer float (o PHP lia INF)",
    ],
)
def test_e_numero_json_recusa_bool_texto_infinitos_e_nan(valor):
    assert e_numero_json(valor) is False


# --- e_inteiro_json: is_int do PHP ---


@pytest.mark.parametrize(
    "valor",
    [0, 1, -1, 2147483647, -2147483648, 2**63 - 1, -(2**63)],
    ids=[
        "zero",
        "um",
        "menos um",
        "maior inteiro de 32 bits",
        "menor inteiro de 32 bits",
        "maior inteiro de 64 bits",
        "menor inteiro de 64 bits",
    ],
)
def test_e_inteiro_json_aceita_inteiros_de_64_bits(valor):
    assert e_inteiro_json(valor) is True


@pytest.mark.parametrize(
    "valor",
    [True, False, 1.0, 1.5, -0.0, "1", None, [1], math.inf, math.nan, 2**63, -(2**63) - 1],
    ids=[
        "verdadeiro",
        "falso",
        "um decimal",
        "decimal",
        "zero negativo",
        "texto",
        "nulo",
        "lista",
        "infinito",
        "não é um número",
        "acima dos 64 bits (o PHP lia float)",
        "abaixo dos 64 bits (o PHP lia float)",
    ],
)
def test_e_inteiro_json_recusa_bool_decimais_e_inteiros_fora_dos_64_bits(valor):
    # Fora dos 64 bits o PHP lê o número como float (is_int → false), e o
    # MongoDB também não guarda inteiros maiores do que 8 bytes.
    assert e_inteiro_json(valor) is False


# --- Tal como o corpo do pedido chega à API (json.loads do Python) ---


@pytest.mark.parametrize(
    "texto_json, numero, inteiro",
    [
        ("12", True, True),
        ("12.0", True, False),
        ("50.5", True, False),
        ("true", False, False),
        ('"12"', False, False),
        ("null", False, False),
        ("NaN", False, False),
        ("Infinity", False, False),
        ("-Infinity", False, False),
        ("1e400", False, False),
        ("9223372036854775807", True, True),
        ("9223372036854775808", True, False),
    ],
    ids=[
        "inteiro",
        "inteiro escrito com casa decimal",
        "decimal",
        "verdadeiro",
        "texto",
        "nulo",
        "NaN (o PHP recusava o JSON)",
        "Infinity (o PHP recusava o JSON)",
        "-Infinity (o PHP recusava o JSON)",
        "1e400 vira infinito",
        "maior inteiro de 64 bits",
        "um acima do maior inteiro de 64 bits",
    ],
)
def test_numeros_lidos_pelo_json_do_python(texto_json, numero, inteiro):
    valor = json.loads(texto_json)
    assert e_numero_json(valor) is numero
    assert e_inteiro_json(valor) is inteiro
