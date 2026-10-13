"""As definições que o admin pode mudar: na F2, só as da fábrica (crm/dominio/definicoes.py).

Porta de src/Dominio/Definicoes.php do CRM autónomo, com todos os casos do
tests/Unit/Dominio/DefinicoesTest.php e os mesmos nomes nos `ids` (dossiê
§5.9). Os padrões vivem no código; a coleção `crm_definicoes` só guarda, em
texto, o que o admin alterou (upsert por `chave`, T2.13). `combinar` junta os
padrões com o que está guardado e devolve as coordenadas como números;
`alteracao` valida um PATCH e devolve `(valores para gravar, erros)`, ambos
pela ordem dos `PADROES` e depois as chaves desconhecidas.

A ordem dos dicionários conta (a dos erros no ecrã), por isso compara-se
`list(….items())`; o tipo também (o `assertSame` do PHP: as coordenadas
guardam-se em texto com 6 casas e saem do `combinar` como `float`). Os
valores esperados das armadilhas foram conferidos no PHP 8.4.26 (`round` +
`sprintf('%.6F')` e o `(float)` de um texto).
"""
import copy
import json

import pytest

from crm.dominio import definicoes
from crm.dominio.definicoes import PADROES, alteracao, combinar
from crm.dominio.geo import contem_latitude, contem_longitude

FORA = "Fora de Portugal"
LAT = "A latitude tem de ser um número."
LNG = "A longitude tem de ser um número."
DESCONHECIDA = "Esta definição não existe."
TEXTO = "Tem de ser texto."

PADROES_NA_API = [("fabrica_morada", ""), ("fabrica_lat", 38.7223), ("fabrica_lng", -9.1393)]


def pares(resultado):
    """`(valores, erros)` como listas de pares: a ordem conta."""
    valores, erros = resultado
    return list(valores.items()), list(erros.items())


def mesmos_pares(dicionario, esperado):
    """A mesma ordem, os mesmos valores e os mesmos tipos (38.7223 é float, "" é str)."""
    obtido = list(dicionario.items())
    return [c for c, _v in obtido] == [c for c, _v in esperado] and all(
        type(a) is type(b) and a == b for (_c, a), (_c2, b) in zip(obtido, esperado)
    )


# --- DefinicoesTest.php: os padrões ---


def test_os_padroes_tem_as_chaves_da_fabrica():
    assert list(PADROES) == ["fabrica_morada", "fabrica_lat", "fabrica_lng"]
    assert PADROES["fabrica_morada"] == ""
    assert PADROES["fabrica_lat"] == "38.722300"
    assert PADROES["fabrica_lng"] == "-9.139300"
    assert all(type(valor) is str for valor in PADROES.values())


def test_o_ponto_padrao_da_fabrica_fica_em_portugal():
    assert contem_latitude(float(PADROES["fabrica_lat"]))
    assert contem_longitude(float(PADROES["fabrica_lng"]))


def test_os_padroes_nao_se_mudam_por_engano():
    # Um dicionário partilhado por todos os pedidos: quem o mudasse mudava os
    # padrões de toda a gente até o servidor reiniciar.
    with pytest.raises(TypeError):
        PADROES["fabrica_lat"] = "0"
    with pytest.raises(TypeError):
        PADROES["hora_saida"] = "08:00"
    assert list(PADROES.items()) == [("fabrica_morada", ""), ("fabrica_lat", "38.722300"), ("fabrica_lng", "-9.139300")]


def test_as_mensagens_sao_as_do_contrato():
    assert definicoes.MENSAGEM_DESCONHECIDA == DESCONHECIDA
    assert definicoes.MORADA_MAXIMO == 255


# --- DefinicoesTest.php: combinar ---


def test_sem_nada_guardado_valem_os_padroes_com_as_coordenadas_como_numeros():
    assert mesmos_pares(combinar({}), PADROES_NA_API)


def test_o_que_esta_guardado_substitui_o_padrao():
    obtido = combinar({"fabrica_lng": "-8.611000", "fabrica_morada": "Rua das Flores 1, Porto"})

    assert mesmos_pares(obtido, [("fabrica_morada", "Rua das Flores 1, Porto"), ("fabrica_lat", 38.7223), ("fabrica_lng", -8.611)])


def test_chaves_guardadas_que_esta_versao_nao_conhece_ignoram_se():
    # Ex.: gravadas por uma versão mais nova, antes de se voltar a esta.
    assert mesmos_pares(combinar({"hora_saida": "08:00"}), PADROES_NA_API)


# --- Armadilhas do Python no combinar ---


@pytest.mark.parametrize(
    "guardado, numero",
    [
        ("38.722300", 38.7223),
        ("-8.611000", -8.611),
        ("39", 39.0),
        (" 38.7", 38.7),
        ("\t\n\r\x0b\x0c38.7", 38.7),
        ("38.7 ", 38.7),
        ("38.7abc", 38.7),
        ("38,7", 38.0),
        ("1.2.3", 1.2),
        ("1e3", 1000.0),
        ("1E-2", 0.01),
        ("1e", 1.0),
        ("1e+", 1.0),
        (".5", 0.5),
        ("5.", 5.0),
        ("-.5", -0.5),
        ("+5", 5.0),
        (" +38.7", 38.7),
        ("abc", 0.0),
        ("", 0.0),
        ("  ", 0.0),
        ("inf", 0.0),
        ("INF", 0.0),
        ("nan", 0.0),
        ("infinity", 0.0),
        ("1_000", 1.0),
        ("0x1A", 0.0),
        ("0b11", 0.0),
        ("+-5", 0.0),
        ("--1", 0.0),
        (".e1", 0.0),
        ("+.e1", 0.0),
        (" 38.7", 0.0),
        ("１２", 0.0),
        ("١٢", 0.0),
        ("\x0038.7", 0.0),
        ("38.7\x00x", 38.7),
    ],
    ids=[
        "seis casas",
        "negativo com seis casas",
        "inteiro em texto",
        "espaço antes",
        "espaços de controlo antes",
        "espaço depois",
        "letras depois",
        "vírgula decimal (só a parte inteira)",
        "dois pontos",
        "expoente",
        "expoente negativo",
        "expoente sem algarismos",
        "expoente só com sinal",
        "sem parte inteira",
        "sem parte decimal",
        "negativo sem parte inteira",
        "sinal mais",
        "espaço e sinal mais",
        "texto",
        "vazio",
        "só espaços",
        "inf (o float() do Python aceitava)",
        "INF",
        "nan (o float() do Python aceitava)",
        "infinity",
        "sublinhado (o float() do Python lia 1000)",
        "hexadecimal",
        "binário",
        "dois sinais",
        "dois menos",
        "ponto e expoente",
        "sinal, ponto e expoente",
        "espaço sem quebra antes (o float() do Python aceitava)",
        "algarismos de largura total (o float() do Python lia 12)",
        "algarismos árabes (o float() do Python lia 12)",
        "NUL antes",
        "NUL depois",
    ],
)
def test_as_coordenadas_guardadas_leem_se_como_o_float_do_php(guardado, numero):
    # O `(float)` do PHP lê o número do início do texto e o resto ignora-se;
    # sem número no início é 0,0 — nunca rebenta. O float() do Python
    # rebentava com ValueError (um 500 no mapa) ou lia o que o PHP não lia.
    # Valores do PHP 8.4.26.
    obtido = combinar({"fabrica_lat": guardado, "fabrica_lng": guardado})

    assert type(obtido["fabrica_lat"]) is float and obtido["fabrica_lat"] == numero
    assert type(obtido["fabrica_lng"]) is float and obtido["fabrica_lng"] == numero


def test_o_menos_zero_guardado_continua_menos_zero_como_no_php():
    assert str(combinar({"fabrica_lat": "-0"})["fabrica_lat"]) == "-0.0"


@pytest.mark.parametrize("guardado, numero", [("1e400", float("inf")), ("-1e400", float("-inf")), ("1e-400", 0.0)])
def test_um_expoente_enorme_da_infinito_como_no_php(guardado, numero):
    assert combinar({"fabrica_lat": guardado})["fabrica_lat"] == numero


@pytest.mark.parametrize("guardado, numero", [(38.7, 38.7), (39, 39.0), (-9, -9.0)], ids=["decimal", "inteiro", "inteiro negativo"])
def test_um_numero_guardado_a_mao_le_se_como_numero(guardado, numero):
    # A alteracao grava sempre texto; um número só lá chega escrito à mão na
    # base. O `(float)` do PHP lia-o como o número.
    obtido = combinar({"fabrica_lat": guardado})["fabrica_lat"]

    assert type(obtido) is float and obtido == numero


@pytest.mark.parametrize("guardado", [None, True, False, ["38.7"], {"v": "38.7"}], ids=["nulo", "verdadeiro", "falso", "lista", "objeto"])
def test_uma_coordenada_guardada_que_nao_e_texto_nem_numero_e_um_erro_de_programacao(guardado):
    # Nunca a escreve o CRM: um bool não pode virar 1,0 sem ninguém dar conta.
    with pytest.raises(TypeError):
        combinar({"fabrica_lat": guardado})


def test_a_morada_guardada_sai_tal_e_qual():
    assert combinar({"fabrica_morada": "  Rua A "})["fabrica_morada"] == "  Rua A "


def test_combinar_nao_muda_o_que_recebe_e_devolve_sempre_um_dicionario_novo():
    guardadas = {"fabrica_lat": "41.149600", "hora_saida": "08:00"}
    antes = copy.deepcopy(guardadas)

    primeiro = combinar(guardadas)
    segundo = combinar(guardadas)

    assert guardadas == antes
    assert primeiro == segundo
    assert primeiro is not segundo
    primeiro["fabrica_lat"] = 0.0
    assert combinar({})["fabrica_lat"] == 38.7223


def test_combinar_devolve_sempre_as_tres_chaves_pela_ordem_dos_padroes():
    obtido = combinar({"fabrica_lng": "-8.0", "hora_saida": "1", "fabrica_lat": "40.0", "fabrica_morada": "Rua B"})

    assert list(obtido) == ["fabrica_morada", "fabrica_lat", "fabrica_lng"]


# --- DefinicoesTest.php: alteracao ---


def test_uma_alteracao_valida_devolve_os_valores_como_se_guardam():
    resultado = alteracao({"fabrica_lng": -8.611, "fabrica_morada": "  Rua das Flores 1, Porto ", "fabrica_lat": 41.1496})

    assert pares(resultado) == (
        [("fabrica_morada", "Rua das Flores 1, Porto"), ("fabrica_lat", "41.149600"), ("fabrica_lng", "-8.611000")],
        [],
    )


def test_sem_alteracoes_nao_ha_nada_a_gravar():
    assert pares(alteracao({})) == ([], [])


def test_so_a_morada_pode_vir_sozinha():
    assert pares(alteracao({"fabrica_morada": "Rua A"})) == ([("fabrica_morada", "Rua A")], [])


@pytest.mark.parametrize("morada", ["", "   ", None], ids=["texto vazio", "só espaços", "null"])
def test_uma_morada_vazia_fica_vazia(morada):
    assert pares(alteracao({"fabrica_morada": morada})) == ([("fabrica_morada", "")], [])


@pytest.mark.parametrize(
    "morada, erro",
    [(12, TEXTO), (["Rua A"], TEXTO), ("á" * 256, "A morada tem no máximo 255 caracteres.")],
    ids=["número", "lista", "256 caracteres"],
)
def test_uma_morada_invalida_da_erro(morada, erro):
    assert list(alteracao({"fabrica_morada": morada})[1].items()) == [("fabrica_morada", erro)]


def test_a_morada_aceita_255_caracteres():
    morada = "á" * 255

    assert pares(alteracao({"fabrica_morada": morada})) == ([("fabrica_morada", morada)], [])


@pytest.mark.parametrize(
    "lat, lng, lat_guardada, lng_guardada",
    [
        (38.7223, -9.1393, "38.722300", "-9.139300"),
        (38.7223456, -9.1393444, "38.722346", "-9.139344"),
        (39, -8, "39.000000", "-8.000000"),
        (36.8, -9.6, "36.800000", "-9.600000"),
        (42.2, -6.1, "42.200000", "-6.100000"),
    ],
    ids=["Lisboa", "arredondadas", "inteiros", "canto sudoeste (limites incluídos)", "canto nordeste (limites incluídos)"],
)
def test_as_coordenadas_guardam_se_com_seis_casas(lat, lng, lat_guardada, lng_guardada):
    assert pares(alteracao({"fabrica_lat": lat, "fabrica_lng": lng})) == (
        [("fabrica_lat", lat_guardada), ("fabrica_lng", lng_guardada)],
        [],
    )


@pytest.mark.parametrize(
    "lat, lng, erro_lat, erro_lng",
    [
        (32.65, -16.9, FORA, FORA),
        (36.79, -8.0, FORA, None),
        (42.21, -8.0, FORA, None),
        (39.0, -9.61, None, FORA),
        (39.0, -6.09, None, FORA),
        ("38.7", "-9.1", LAT, LNG),
        (None, None, LAT, LNG),
        (True, False, LAT, LNG),
        (float("inf"), float("-inf"), LAT, LNG),
    ],
    ids=[
        "Madeira",
        "a sul do Algarve",
        "a norte do Minho",
        "no mar, a oeste",
        "em Espanha, a leste",
        "texto",
        "null",
        "booleano",
        "infinito (1e400 no JSON)",
    ],
)
def test_coordenadas_invalidas_dao_erro(lat, lng, erro_lat, erro_lng):
    esperado = [(campo, erro) for campo, erro in [("fabrica_lat", erro_lat), ("fabrica_lng", erro_lng)] if erro is not None]

    assert list(alteracao({"fabrica_lat": lat, "fabrica_lng": lng})[1].items()) == esperado


def test_a_latitude_sem_a_longitude_da_erro():
    assert list(alteracao({"fabrica_lat": 38.7})[1].items()) == [("fabrica_lng", "Indique também a longitude.")]


def test_a_longitude_sem_a_latitude_da_erro():
    assert list(alteracao({"fabrica_lng": -9.1})[1].items()) == [("fabrica_lat", "Indique também a latitude.")]


def test_uma_chave_desconhecida_da_erro():
    assert list(alteracao({"fabrica_morada": "Rua A", "hora_saida": "08:00"})[1].items()) == [("hora_saida", DESCONHECIDA)]


def test_os_erros_vem_pela_ordem_dos_padroes_e_depois_as_chaves_desconhecidas():
    _valores, erros = alteracao(
        {"raio_km": 5, "fabrica_lng": 0.0, "fabrica_lat": "x", "fabrica_morada": 1, "atualizado_em": "x"}
    )

    assert list(erros) == ["fabrica_morada", "fabrica_lat", "fabrica_lng", "raio_km", "atualizado_em"]


# --- Armadilhas do Python na alteracao (valores conferidos no PHP 8.4.26) ---


@pytest.mark.parametrize(
    "lat, lng, valores, erros",
    [
        (38.7223445, -8.6110005, ("38.722345", "-8.611001"), []),
        (41.1496005, -9.1393495, ("41.149601", "-9.139350"), []),
        (42.1999995, -9.5999995, ("42.200000", "-9.600000"), []),
        (36.7999995, -6.0999995, ("36.800000", "-6.100000"), []),
        (42.2000005, -9.6000005, ("42.200001", "-9.600001"), [("fabrica_lat", FORA), ("fabrica_lng", FORA)]),
        (36.7999994, -6.0999994, ("36.799999", "-6.099999"), [("fabrica_lat", FORA), ("fabrica_lng", FORA)]),
    ],
    ids=[
        "meio-para-longe-do-zero (o round do Python dava 38.722344 e -8.611000)",
        "meio-para-longe-do-zero (o round do Python dava 41.149600 e -9.139349)",
        "norte e oeste: arredondam para o limite e ficam dentro",
        "sul e leste: arredondam para o limite e ficam dentro",
        "norte e oeste: o meio arredonda para fora",
        "sul e leste: não chegam ao limite",
    ],
)
def test_arredonda_as_6_casas_como_o_php_antes_de_ver_portugal(lat, lng, valores, erros):
    assert pares(alteracao({"fabrica_lat": lat, "fabrica_lng": lng})) == (
        [("fabrica_lat", valores[0]), ("fabrica_lng", valores[1])],
        erros,
    )


@pytest.mark.parametrize(
    "lat, lng, valores, erros",
    [
        (-0.0, -9.1, ("0.000000", "-9.100000"), [("fabrica_lat", FORA)]),
        (38.7, -0.0, ("38.700000", "0.000000"), [("fabrica_lng", FORA)]),
        (-0.0000004, 0.0000004, ("0.000000", "0.000000"), [("fabrica_lat", FORA), ("fabrica_lng", FORA)]),
        (-0.0000005, 0.0000005, ("-0.000001", "0.000001"), [("fabrica_lat", FORA), ("fabrica_lng", FORA)]),
        (2**63, -9.1, ("9223372036854775808.000000", "-9.100000"), [("fabrica_lat", FORA)]),
        (1, 2, ("1.000000", "2.000000"), [("fabrica_lat", FORA), ("fabrica_lng", FORA)]),
    ],
    ids=[
        "menos zero sai sem sinal (o sprintf do PHP)",
        "menos zero na longitude",
        "arredonda para menos zero e sai sem sinal",
        "o meio negativo vai para longe do zero",
        "fora dos 64 bits (o PHP lia um float)",
        "inteiros pequenos",
    ],
)
def test_fora_de_portugal_o_valor_arredondado_fica_como_no_php(lat, lng, valores, erros):
    # Os valores com erros não se gravam; ficam iguais aos do PHP.
    assert pares(alteracao({"fabrica_lat": lat, "fabrica_lng": lng})) == (
        [("fabrica_lat", valores[0]), ("fabrica_lng", valores[1])],
        erros,
    )


def test_um_numero_enorme_sai_com_todos_os_algarismos_como_no_sprintf_do_php():
    valores, erros = alteracao({"fabrica_lat": 1e308, "fabrica_lng": -1e308})

    assert valores["fabrica_lat"] == "%.6f" % 1e308
    assert valores["fabrica_lat"].startswith("100000000000000001097906362944045541740492309677311846336810682903157585404911491537163328978494688899061249669721172515611590283743140088328307009198146046031271664502933027185697489699588559043338384466165001178426897626212945177628091195786707458122783970171784415105291802893207873272974885715430223118336")
    assert valores["fabrica_lat"].endswith(".000000")
    assert valores["fabrica_lng"] == "-" + valores["fabrica_lat"]
    assert list(erros.items()) == [("fabrica_lat", FORA), ("fabrica_lng", FORA)]


@pytest.mark.parametrize(
    "texto_json",
    ["NaN", "Infinity", "-Infinity", "1e400", "-1e400", "true", "false", "null", '"38.7"', "[38.7]", '{"lat": 38.7}', str(10**400)],
)
def test_coordenadas_lidas_pelo_json_loads_que_nao_sao_numeros_finitos_dao_erro(texto_json):
    # O json do Python aceita NaN e Infinity (o do PHP não) e lê 1e400 como
    # inf; um inteiro sem fim lia-o o PHP como INF.
    valor = json.loads(texto_json)

    assert pares(alteracao({"fabrica_lat": valor, "fabrica_lng": valor})) == (
        [("fabrica_lat", ""), ("fabrica_lng", "")],
        [("fabrica_lat", LAT), ("fabrica_lng", LNG)],
    )


@pytest.mark.parametrize(
    "pedido, valores, erros",
    [
        ({"fabrica_lat": None}, [("fabrica_lat", "")], [("fabrica_lat", LAT), ("fabrica_lng", "Indique também a longitude.")]),
        ({"fabrica_lng": None}, [("fabrica_lng", "")], [("fabrica_lat", "Indique também a latitude."), ("fabrica_lng", LNG)]),
        ({"fabrica_lat": None, "fabrica_lng": None}, [("fabrica_lat", ""), ("fabrica_lng", "")], [("fabrica_lat", LAT), ("fabrica_lng", LNG)]),
        (
            {"fabrica_lng": "x", "fabrica_morada": "  "},
            [("fabrica_morada", ""), ("fabrica_lng", "")],
            [("fabrica_lat", "Indique também a latitude."), ("fabrica_lng", LNG)],
        ),
    ],
    ids=["latitude nula", "longitude nula", "as duas nulas", "a que falta vem antes, pela ordem dos padrões"],
)
def test_a_chave_conta_mesmo_com_null(pedido, valores, erros):
    # O array_key_exists do PHP: uma coordenada a null foi enviada.
    assert pares(alteracao(pedido)) == (valores, erros)


@pytest.mark.parametrize(
    "pedido, valores, erros",
    [
        (
            {"Fabrica_lng": -9.1, "fabrica_lat": 38.7},
            [("fabrica_lat", "38.700000")],
            [("fabrica_lng", "Indique também a longitude."), ("Fabrica_lng", DESCONHECIDA)],
        ),
        (
            {"fabrica_lat ": 38.7, " fabrica_lng": -9.1},
            [],
            [("fabrica_lat ", DESCONHECIDA), (" fabrica_lng", DESCONHECIDA)],
        ),
        ({"FABRICA_MORADA": "Rua A"}, [], [("FABRICA_MORADA", DESCONHECIDA)]),
    ],
    ids=["maiúscula", "espaços", "tudo em maiúsculas"],
)
def test_chaves_parecidas_sao_desconhecidas_e_nao_contam_como_o_par(pedido, valores, erros):
    assert pares(alteracao(pedido)) == (valores, erros)


def test_as_chaves_desconhecidas_vem_pela_ordem_em_que_chegaram():
    _valores, erros = alteracao({"z": 1, "a": 2, "fabrica_morada": 1, "m": None})

    assert list(erros.items()) == [("fabrica_morada", TEXTO), ("z", DESCONHECIDA), ("a", DESCONHECIDA), ("m", DESCONHECIDA)]


def test_com_uma_chave_desconhecida_os_valores_validos_vem_na_mesma_mas_nao_se_gravam():
    # Como no PHP: quem chama só usa os valores quando não há erros.
    assert pares(alteracao({"fabrica_morada": "Rua A", "hora_saida": "08:00"})) == (
        [("fabrica_morada", "Rua A")],
        [("hora_saida", DESCONHECIDA)],
    )


@pytest.mark.parametrize(
    "morada, aparada",
    [
        ("﻿Rua A　", "Rua A"),
        (" Rua  A\n", "Rua  A"),
        ("  ", ""),
        ("\n", ""),
    ],
    ids=["U+FEFF e espaço ideográfico", "espaço sem quebra e mudança de linha (os do meio ficam)", "só separadores Unicode", "só uma mudança de linha"],
)
def test_a_morada_perde_os_espacos_unicode_das_pontas(morada, aparada):
    assert pares(alteracao({"fabrica_morada": morada})) == ([("fabrica_morada", aparada)], [])


@pytest.mark.parametrize(
    "morada, erro",
    [
        ("😀" * 255, None),
        ("😀" * 256, "A morada tem no máximo 255 caracteres."),
        (" " + "a" * 255 + " ", None),
        (True, TEXTO),
        (False, TEXTO),
        (0, TEXTO),
        ({"rua": "A"}, TEXTO),
        ([], TEXTO),
    ],
    ids=["255 emojis cabem", "256 emojis não cabem", "conta depois de aparar", "verdadeiro", "falso", "zero", "objeto", "lista vazia"],
)
def test_a_morada_conta_caracteres_e_so_aceita_texto(morada, erro):
    valores, erros = alteracao({"fabrica_morada": morada})

    assert list(erros.items()) == ([] if erro is None else [("fabrica_morada", erro)])
    assert type(valores["fabrica_morada"]) is str
    if erro is not None:
        # Com erro, o valor fica "" (o `$morada ?? ''` do PHP).
        assert valores["fabrica_morada"] == ""


def test_os_valores_sao_sempre_texto():
    valores, _erros = alteracao({"fabrica_morada": None, "fabrica_lat": 39, "fabrica_lng": -8})

    assert all(type(valor) is str for valor in valores.values())


def test_os_valores_vem_pela_ordem_dos_padroes_e_so_os_enviados():
    valores, _erros = alteracao({"fabrica_lng": -8.611, "fabrica_lat": 41.1496})

    assert list(valores) == ["fabrica_lat", "fabrica_lng"]


def test_o_pedido_nao_muda_e_cada_chamada_devolve_estruturas_novas():
    pedido = {"fabrica_lng": -8.611, "fabrica_morada": [" Rua "], "x": {"y": 1}, "fabrica_lat": 41.1496}
    antes = copy.deepcopy(pedido)

    primeiro = alteracao(pedido)
    segundo = alteracao(pedido)

    assert pedido == antes
    assert list(pedido) == list(antes)
    assert primeiro == segundo
    assert primeiro[0] is not segundo[0]
    assert primeiro[1] is not segundo[1]


def test_o_que_a_alteracao_grava_o_combinar_le_de_volta():
    # Ida e volta: os textos com 6 casas voltam ao mesmo número.
    valores, erros = alteracao({"fabrica_lat": 41.1496005, "fabrica_lng": -8.6110005, "fabrica_morada": " Rua das Flores 1 "})

    assert erros == {}
    assert mesmos_pares(
        combinar(valores),
        [("fabrica_morada", "Rua das Flores 1"), ("fabrica_lat", 41.149601), ("fabrica_lng", -8.611001)],
    )
