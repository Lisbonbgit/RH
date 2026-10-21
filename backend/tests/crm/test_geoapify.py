"""Os pedidos à Geoapify e as respostas no formato do CRM
(crm/servicos/geoapify.py; plano T2.14, dossiê §8).

Porta de src/Servicos/Geoapify.php, com todos os casos de
tests/Unit/Servicos/{GeoapifyUrlTest,GeoapifyNormalizarTest}.php do CRM
autónomo (etiqueta `referencia-standalone`), com os nomes de lá nos docstrings
e nos `ids`. Funções puras, sem rede: o cliente assíncrono e a rota
`/morada/inversa` são da T2.15.

Desde a G18 do plano do mapa Google, a Geoapify fica só para a morada
sugerida do ponto do GPS (a inversa): a pesquisa de moradas é a da própria
Google, no browser, e os casos do URL da pesquisa saíram com o `url_pesquisa`
e o `LIMITE_PESQUISA` (os do texto e da chave codificados passaram para a
chave da inversa). O normalizador é o mesmo para as duas respostas e
continua a chamar-se `normalizar_autocomplete`; a resposta gravada da
pesquisa da Rua Augusta fica, porque prova a normalização com vários
resultados.

As respostas gravadas (tests/crm/fixtures/geoapify/*.json) vêm do autónomo,
escritas à mão no formato `format=json` da documentação da Geoapify, com o
`_origem` "manual — regravar": o dono regrava-as com a chave de
desenvolvimento (dossiê §14, item 3).

Armadilhas do Python (dossiê §2.1 e §8):

- as coordenadas do URL são o `number_format($v, 6)` do PHP sem zeros no fim:
  meio-para-longe-do-zero (o `round()` do Python arredonda para o par) e
  nunca "-0" (o `"%.6f"` do Python escreve `-0.000000`);
- o `http_build_query(…, PHP_QUERY_RFC3986)` é o `rawurlencode` de cada chave
  e valor: espaço → `%20` (nunca `+`), só `A-Za-z0-9-_.~` ficam; os bytes
  que não são UTF-8 de uma variável de ambiente (surrogateescape) vão um a um;
- `True` é um `int` em Python e o `json` lê `NaN`, `Infinity` e `1e400`; o
  PHP nunca conta um bool como coordenada;
- `39 == 39.0` em Python: o tipo das coordenadas normalizadas confere-se à
  parte (o `assertSame` do PHP distingue 39 de 39.0);
- o `trim()` do PHP só tira `" \\t\\n\\r\\0\\x0B"` (não os espaços Unicode nem o
  U+FEFF, ao contrário do `texto.aparar`) e o `strtolower` só mexe no ASCII;
- o `assertSame` do PHP sobre arrays confere também a ordem das chaves: aqui
  comparam-se listas de pares e `list(d)`.

Os valores "conferidos com o PHP" saíram da própria classe do autónomo, no
PHP 8.4.26.
"""
import copy
import json
import math
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from crm.dominio.geo import contem_latitude, contem_longitude, distancia_metros
from crm.servicos import geoapify
from crm.servicos.geoapify import normalizar_autocomplete, normalizar_inversa, url_inversa

BASE = "https://api.geoapify.com"
CHAVE = "chave-teste-servidor"

GRAVADAS = Path(__file__).parent / "fixtures" / "geoapify"

# Um resultado completo, como a Geoapify o devolve (só os campos que contam).
RESULTADO = {
    "country_code": "pt",
    "city": "Lisboa",
    "postcode": "1100-048",
    "street": "Rua Augusta",
    "housenumber": "24",
    "lon": -9.13712,
    "lat": 38.70921,
    "formatted": "Rua Augusta 24, 1100-048 Lisboa, Portugal",
    "address_line1": "Rua Augusta 24",
}

NORMALIZADO = {
    "rotulo": "Rua Augusta 24, 1100-048 Lisboa, Portugal",
    "morada": "Rua Augusta 24",
    "codigo_postal": "1100-048",
    "localidade": "Lisboa",
    "lat": 38.70921,
    "lng": -9.13712,
}

CHAVES_NORMALIZADO = ["rotulo", "morada", "codigo_postal", "localidade", "lat", "lng"]

CODIGO_POSTAL = re.compile(r"[0-9]{4}-[0-9]{3}")


def _parametros(url):
    """Os parâmetros do URL, por ordem, como pares (o `parse_str` do PHP + a
    ordem que o `assertSame` confere)."""
    return parse_qsl(urlsplit(url).query, keep_blank_values=True, strict_parsing=True)


def _resultado(**alteracoes):
    """O resultado completo com as alterações; um valor `None` tira o campo
    (o `array_filter(array_replace(…))` do teste do autónomo)."""
    juntos = {**RESULTADO, **alteracoes}
    return {campo: valor for campo, valor in juntos.items() if valor is not None}


def _resposta(*resultados):
    return {"results": list(resultados)}


def _gravada(ficheiro):
    return json.loads((GRAVADAS / ficheiro).read_text(encoding="utf-8"))


def _mesmo(obtido, esperado):
    """Igualdade com os tipos (39.0 não é 39, nem True é 1) e a ordem das
    chaves, como o `assertSame` do PHP."""
    assert obtido == esperado
    if isinstance(esperado, dict):
        assert list(obtido) == list(esperado)
        for chave in esperado:
            _mesmo(obtido[chave], esperado[chave])
    elif isinstance(esperado, list):
        for a, b in zip(obtido, esperado):
            _mesmo(a, b)
    else:
        assert type(obtido) is type(esperado)


# --- GeoapifyUrlTest.php -------------------------------------------------------------------






def test_a_inversa_leva_o_ponto_a_lingua_o_formato_e_a_chave():
    """`aInversaLevaOPontoALinguaOFormatoEAChave`."""
    assert url_inversa(BASE, CHAVE, 38.7075, -9.1364) == (
        BASE + "/v1/geocode/reverse?lat=38.7075&lon=-9.1364&lang=pt&format=json&apiKey=chave-teste-servidor"
    )


def test_usa_o_url_base_da_configuracao_com_ou_sem_barra_no_fim():
    """`usaOUrlBaseDaConfiguracaoComOuSemBarraNoFim`."""
    base = "http://127.0.0.1:8099/geoapify/"

    assert url_inversa(base, CHAVE, 38.7075, -9.1364).startswith("http://127.0.0.1:8099/geoapify/v1/geocode/reverse?")


@pytest.mark.parametrize(
    "base",
    ["http://127.0.0.1:8099/geoapify", "http://127.0.0.1:8099/geoapify/", "http://127.0.0.1:8099/geoapify///"],
    ids=["sem barra", "com uma barra", "com várias barras (o rtrim tira todas)"],
)
def test_o_url_base_perde_todas_as_barras_do_fim(base):
    """Conferido com o PHP: o `rtrim($urlBase, '/')` tira todas."""
    assert url_inversa(base, "k", 38.7075, -9.1364) == (
        "http://127.0.0.1:8099/geoapify/v1/geocode/reverse?lat=38.7075&lon=-9.1364&lang=pt&format=json&apiKey=k"
    )


def test_a_chave_vai_codificada_no_url():
    """`oTextoEAChaveVaoCodificadosNoUrl`, só com a chave: o texto era o da
    pesquisa, que saiu na G18 (os caracteres dele vão aqui na chave)."""
    chave = "a&b=c d 1º Esq. & Cª #2 ?x=1"

    url = url_inversa(BASE, chave, 38.7075, -9.1364)

    assert dict(_parametros(url))["apiKey"] == chave
    assert " " not in url
    assert "#" not in url


def test_a_codificacao_e_a_do_rawurlencode_do_php():
    """Conferido com o PHP: espaço → `%20` (nunca `+`), só `A-Za-z0-9-_.~`
    ficam, a barra e o `+` codificam-se, e o UTF-8 vai byte a byte em
    maiúsculas. Os mesmos caracteres que se conferiram no texto da pesquisa
    (que saiu na G18) e na chave, agora todos na chave."""
    url = url_inversa(BASE, "Praça do Comércio ~/+*'()!$,;:@[] chave/+~ é", 38.7075, -9.1364)

    assert url == (
        BASE + "/v1/geocode/reverse?lat=38.7075&lon=-9.1364&lang=pt&format=json"
        "&apiKey=Pra%C3%A7a%20do%20Com%C3%A9rcio%20~%2F%2B%2A%27%28%29%21%24%2C%3B%3A%40%5B%5D"
        "%20chave%2F%2B~%20%C3%A9"
    )


def test_uma_chave_com_bytes_que_nao_sao_utf8_vai_byte_a_byte():
    """Conferido com o PHP: o byte 0xFF de uma variável de ambiente chega ao
    Python como `\\udcff` (surrogateescape) e vai como `%FF`, sem rebentar."""
    assert url_inversa(BASE, "\udcff", 38.7075, -9.1364) == (
        BASE + "/v1/geocode/reverse?lat=38.7075&lon=-9.1364&lang=pt&format=json&apiKey=%FF"
    )


def test_sem_chave_o_url_leva_a_chave_vazia():
    """Conferido com o PHP. A rota (T2.15) nem chega a pedir sem chave: dá 503."""
    assert url_inversa(BASE, "", 38.7075, -9.1364).endswith("&format=json&apiKey=")


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (38.7223, "38.7223"),
        (38.722312345, "38.722312"),
        (38.7000000001, "38.7"),
        (39.0, "39"),
        (-9.5, "-9.5"),
        (-10.0, "-10"),
    ],
    ids=["sem zeros a mais", "arredondada a 6 casas", "quase inteira", "inteira", "negativa", "dezenas negativas"],
)
def test_as_coordenadas_vao_com_ate_6_casas_decimais_sem_zeros_no_fim(valor, esperado):
    """`asCoordenadasVaoComAte6CasasDecimaisSemZerosNoFim`."""
    inversa = dict(_parametros(url_inversa(BASE, CHAVE, valor, valor)))

    assert [inversa["lat"], inversa["lon"]] == [esperado, esperado]


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (38.1234565, "38.123457"),
        (38.1234566, "38.123457"),
        (36.7999996, "36.8"),
        (-9.13640049, "-9.1364"),
        (0.0000005, "0.000001"),
        (-0.0000005, "-0.000001"),
        (1.0000005, "1.000001"),
        (2.0000005, "2.000001"),
        (0.285, "0.285"),
        (0.0000004, "0"),
        (-0.0000001, "0"),
        (-0.0, "0"),
        (0.0, "0"),
        (100.0, "100"),
        (-180.0, "-180"),
        (39, "39"),
    ],
    ids=[
        "meio para cima às 6 casas",
        "acima do meio",
        "arredonda para o limite de Portugal",
        "negativa com zeros a tirar",
        "meio para longe do zero",
        "meio negativo para longe do zero",
        "1,0000005 (o round do Python dava 1,0)",
        "2,0000005",
        "0,285 como se escreve",
        "abaixo do meio dá zero",
        "negativa que arredonda a zero não leva sinal",
        "zero negativo",
        "zero",
        "centenas sem zeros a tirar",
        "centenas negativas",
        "um int vai como o float do PHP",
    ],
)
def test_as_coordenadas_seguem_o_number_format_do_php(valor, esperado):
    """Conferidos com o PHP: o `number_format` arredonda meio-para-longe-do-zero
    e, desde o PHP 8.0, nunca escreve "-0"."""
    inversa = dict(_parametros(url_inversa(BASE, CHAVE, valor, valor)))

    assert [inversa["lat"], inversa["lon"]] == [esperado, esperado]


def test_a_inversa_leva_a_latitude_e_a_longitude_cada_uma_no_seu_parametro():
    assert _parametros(url_inversa(BASE, CHAVE, 38.7075, -9.1364)) == [
        ("lat", "38.7075"),
        ("lon", "-9.1364"),
        ("lang", "pt"),
        ("format", "json"),
        ("apiKey", CHAVE),
    ]


# --- GeoapifyNormalizarTest.php ------------------------------------------------------------


def test_normaliza_cada_resultado_nos_campos_da_loja():
    """`normalizaCadaResultadoNosCamposDaLoja`."""
    _mesmo(normalizar_autocomplete(_resposta(_resultado())), [NORMALIZADO])


def test_mantem_a_ordem_da_geoapify():
    """`mantemAOrdemDaGeoapify`."""
    segundo = _resultado(housenumber="2", formatted="Rua Augusta 2, 1100-048 Lisboa, Portugal")

    normalizados = normalizar_autocomplete(_resposta(_resultado(), segundo))

    assert [n["rotulo"] for n in normalizados] == [
        "Rua Augusta 24, 1100-048 Lisboa, Portugal",
        "Rua Augusta 2, 1100-048 Lisboa, Portugal",
    ]


def test_o_rotulo_vem_sem_espacos_nas_pontas():
    """`oRotuloVemSemEspacosNasPontas`."""
    resultado = _resultado(formatted="  Rua Augusta 24, 1100-048 Lisboa, Portugal ")

    assert normalizar_autocomplete(_resposta(resultado))[0]["rotulo"] == "Rua Augusta 24, 1100-048 Lisboa, Portugal"


@pytest.mark.parametrize(
    ("alteracoes", "esperada"),
    [
        ({}, "Rua Augusta 24"),
        ({"housenumber": None}, "Rua Augusta"),
        ({"housenumber": " "}, "Rua Augusta"),
        ({"street": " Rua Augusta ", "housenumber": " 24 "}, "Rua Augusta 24"),
        ({"street": None, "housenumber": None, "address_line1": "Pastelaria Exemplo"}, None),
        ({"street": None}, None),
        ({"street": "  "}, None),
        ({"street": 7}, None),
    ],
    ids=[
        "rua e número",
        "só a rua",
        "número vazio",
        "espaços nas pontas",
        "sem rua, o nome de um sítio não passa para a morada",
        "sem rua, só o número",
        "rua vazia",
        "rua que não é texto",
    ],
)
def test_a_morada_e_a_rua_com_o_numero_de_policia(alteracoes, esperada):
    """`aMoradaEARuaComONumeroDePolicia`."""
    assert normalizar_autocomplete(_resposta(_resultado(**alteracoes)))[0]["morada"] == esperada


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("1100-048", "1100-048"),
        (" 4000-322 ", "4000-322"),
        ("1100", None),
        ("1100048", None),
        ("1100 048", None),
        ("1100-04", None),
        ("1100-0488", None),
        ("A100-048", None),
        ("１１００-０４８", None),
        (1100, None),
        (None, None),
    ],
    ids=[
        "completo",
        "com espaços nas pontas",
        "só os 4 primeiros algarismos",
        "sem hífen",
        "com espaço em vez de hífen",
        "final curto",
        "final comprido",
        "com letras",
        "algarismos de largura total",
        "número",
        "não vem",
    ],
)
def test_o_codigo_postal_so_passa_com_o_formato_0000_000(codigo, esperado):
    """`oCodigoPostalSoPassaComOFormato0000000`."""
    assert normalizar_autocomplete(_resposta(_resultado(postcode=codigo)))[0]["codigo_postal"] == esperado


_TODAS = {"city": "Lisboa", "town": "Sintra", "village": "Colares", "county": "Concelho"}


@pytest.mark.parametrize(
    ("alteracoes", "esperada"),
    [
        (_TODAS, "Lisboa"),
        ({**_TODAS, "city": None}, "Sintra"),
        ({**_TODAS, "city": None, "town": None}, "Colares"),
        ({"city": None, "county": "Sintra"}, "Sintra"),
        ({"city": " ", "town": "Sintra"}, "Sintra"),
        ({"city": 1, "village": "Colares"}, "Colares"),
        ({"city": " Lisboa "}, "Lisboa"),
        ({"city": None}, None),
    ],
    ids=[
        "city primeiro",
        "sem city, town",
        "sem city nem town, village",
        "só county",
        "city vazia passa à seguinte",
        "city que não é texto passa à seguinte",
        "sem espaços nas pontas",
        "nenhuma",
    ],
)
def test_a_localidade_vem_da_city_town_village_ou_county(alteracoes, esperada):
    """`aLocalidadeVemDaCityTownVillageOuCounty`."""
    assert normalizar_autocomplete(_resposta(_resultado(**alteracoes)))[0]["localidade"] == esperada


@pytest.mark.parametrize(
    "alteracoes",
    [
        {"lat": None},
        {"lon": None},
        {"lat": "38.70921"},
        {"lon": True},
        # Badajoz fica dentro da caixa de Portugal continental: conta o country_code.
        {"country_code": "es", "lat": 38.8794, "lon": -6.9707},
        {"country_code": None},
        {"country_code": 351},
        # A carrinha não serve as ilhas (plano §9 do autónomo): a loja não se poderia gravar.
        {"lat": 32.6669, "lon": -16.9241},
        {"lat": 37.7412, "lon": -25.6756},
        {"formatted": None},
        {"formatted": "  "},
    ],
    ids=[
        "sem lat",
        "sem lon",
        "lat em texto",
        "lon booleano",
        "Espanha, junto à fronteira",
        "sem country_code",
        "country_code que não é texto",
        "Madeira",
        "Açores",
        "sem formatted",
        "formatted vazio",
    ],
)
def test_ignora_resultados_sem_coordenadas_fora_de_portugal_ou_sem_rotulo(alteracoes):
    """`ignoraResultadosSemCoordenadasForaDePortugalOuSemRotulo`."""
    assert normalizar_autocomplete(_resposta(_resultado(**alteracoes))) == []


def test_aceita_o_country_code_em_maiusculas():
    """`aceitaOCountryCodeEmMaiusculas`."""
    _mesmo(normalizar_autocomplete(_resposta(_resultado(country_code="PT"))), [NORMALIZADO])


def test_coordenadas_inteiras_vem_como_numeros_decimais():
    """`coordenadasInteirasVemComoNumerosDecimais`."""
    normalizado = normalizar_autocomplete(_resposta(_resultado(lat=39, lon=-8)))[0]

    assert [normalizado["lat"], normalizado["lng"]] == [39.0, -8.0]
    assert [type(normalizado["lat"]), type(normalizado["lng"])] == [float, float]


def test_fica_so_com_os_resultados_validos():
    """`ficaSoComOsResultadosValidos`."""
    resposta = {"results": [_resultado(lat=None), "texto", None, _resultado()]}

    _mesmo(normalizar_autocomplete(resposta), [NORMALIZADO])


@pytest.mark.parametrize(
    "resposta",
    [{"results": []}, {"query": {"text": "xyz"}}, {"results": "nada"}, {}],
    ids=["results vazio", "sem results", "results que não é lista", "resposta vazia"],
)
def test_sem_resultados_devolve_uma_lista_vazia(resposta):
    """`semResultadosDevolveUmaListaVazia`."""
    assert normalizar_autocomplete(resposta) == []


def test_a_resposta_gravada_da_pesquisa_da_rua_augusta():
    """`aRespostaGravadaDaPesquisaDaRuaAugusta`."""
    sugestoes = normalizar_autocomplete(_gravada("autocomplete-rua-augusta.json"))

    assert sugestoes != []
    assert len(sugestoes) <= 5

    for sugestao in sugestoes:
        assert list(sugestao) == CHAVES_NORMALIZADO
        assert isinstance(sugestao["rotulo"], str)
        assert sugestao["codigo_postal"] is None or CODIGO_POSTAL.fullmatch(sugestao["codigo_postal"])
        assert contem_latitude(sugestao["lat"]) is True
        assert contem_longitude(sugestao["lng"]) is True

    assert sugestoes[0]["rotulo"].startswith("Rua Augusta")
    assert sugestoes[0]["localidade"] == "Lisboa"


def test_normalizar_inversa_devolve_o_primeiro_resultado_valido():
    """`normalizarInversaDevolveOPrimeiroResultadoValido`."""
    espanha = _resultado(country_code="es", formatted="Calle Mayor, Badajoz, España")

    _mesmo(normalizar_inversa(_resposta(espanha, _resultado())), NORMALIZADO)


def test_normalizar_inversa_com_varios_validos_fica_com_o_primeiro():
    """Pela ordem da Geoapify (a mais perto do ponto vem primeiro), nunca a
    última."""
    segundo = _resultado(housenumber="2", formatted="Rua Augusta 2, 1100-048 Lisboa, Portugal")

    _mesmo(normalizar_inversa(_resposta(_resultado(), segundo)), NORMALIZADO)


@pytest.mark.parametrize(
    "resposta",
    [{"results": []}, {}, {"results": [_resultado(lat=None)]}],
    ids=["results vazio", "sem results", "só resultados inválidos"],
)
def test_normalizar_inversa_sem_resultado_valido_devolve_null(resposta):
    """`normalizarInversaSemResultadoValidoDevolveNull`."""
    assert normalizar_inversa(resposta) is None


def test_a_resposta_gravada_da_inversa_da_praca_do_comercio():
    """`aRespostaGravadaDaInversaDaPracaDoComercio`."""
    morada = normalizar_inversa(_gravada("reverse-praca-comercio.json"))

    assert morada is not None
    assert list(morada) == CHAVES_NORMALIZADO
    assert morada["localidade"] == "Lisboa"
    assert distancia_metros(38.7075, -9.1364, morada["lat"], morada["lng"]) < 100


# --- Armadilhas do Python e do portal (conferidas com o PHP) -----------------------------


def test_as_respostas_gravadas_por_inteiro():
    """As duas respostas gravadas, normalizadas campo a campo (o mesmo que a
    classe do autónomo dá com elas no PHP 8.4.26): o terceiro resultado da
    pesquisa (Cascais) só traz os 4 primeiros algarismos do código postal."""
    _mesmo(
        normalizar_autocomplete(_gravada("autocomplete-rua-augusta.json")),
        [
            {
                "rotulo": "Rua Augusta, 1100-053 Lisboa, Portugal",
                "morada": "Rua Augusta",
                "codigo_postal": "1100-053",
                "localidade": "Lisboa",
                "lat": 38.7104,
                "lng": -9.1377,
            },
            NORMALIZADO,
            {
                "rotulo": "Rua Augusta, 2750 Cascais, Portugal",
                "morada": "Rua Augusta",
                "codigo_postal": None,
                "localidade": "Cascais",
                "lat": 38.6979,
                "lng": -9.4215,
            },
        ],
    )
    _mesmo(
        normalizar_inversa(_gravada("reverse-praca-comercio.json")),
        {
            "rotulo": "Praça do Comércio, 1100-148 Lisboa, Portugal",
            "morada": "Praça do Comércio",
            "codigo_postal": "1100-148",
            "localidade": "Lisboa",
            "lat": 38.70749,
            "lng": -9.13648,
        },
    )


def test_as_respostas_gravadas_estao_marcadas_para_regravar_e_sem_chave():
    """Copiadas do autónomo com o `_origem` "manual — regravar" (plano T2.14),
    que a normalização ignora; nenhuma traz um `apiKey`."""
    for ficheiro in ("autocomplete-rua-augusta.json", "reverse-praca-comercio.json"):
        gravada = _gravada(ficheiro)
        assert gravada["_origem"] == "manual — regravar"
        assert "apiKey" not in (GRAVADAS / ficheiro).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "alteracoes",
    [
        {"lat": True},
        {"lat": False},
        {"lat": math.nan},
        {"lon": math.inf},
        {"lat": -math.inf},
        {"lat": 10**400},
        {"lat": [38.70921]},
        {"lat": {"valor": 38.70921}},
        {"lat": 42.2000001},
        {"lat": 0},
        {"country_code": "pt "},
        {"country_code": "ＰＴ"},
        {"country_code": "p"},
        {"country_code": True},
        {"formatted": 7},
        {"formatted": ["Rua Augusta"]},
        {"formatted": "\t\n\r\x00\x0b"},
    ],
    ids=[
        "lat True (em Python é 1)",
        "lat False (em Python é 0)",
        "lat NaN (o json do Python lê-o)",
        "lon infinito",
        "lat menos infinito",
        "lat inteiro maior do que um float (o PHP lia INF)",
        "lat numa lista",
        "lat num objeto",
        "lat logo acima do limite norte",
        "lat zero",
        "country_code com espaço sem quebra (o trim do PHP não o tira)",
        "country_code em largura total (o strtolower do PHP só mexe no ASCII)",
        "country_code incompleto",
        "country_code booleano",
        "formatted que é um número",
        "formatted numa lista",
        "formatted só com os espaços que o trim do PHP tira",
    ],
)
def test_ignora_tambem_as_armadilhas_do_python(alteracoes):
    """Conferido com o PHP onde o JSON o permite (o `json_decode` do PHP não lê
    NaN nem Infinity; `1e400` dava INF e um inteiro enorme um float)."""
    assert normalizar_autocomplete(_resposta(_resultado(**alteracoes))) == []


@pytest.mark.parametrize(
    ("alteracoes", "campo", "esperado"),
    [
        ({"country_code": " PT "}, "rotulo", NORMALIZADO["rotulo"]),
        ({"country_code": "\tpt\n"}, "rotulo", NORMALIZADO["rotulo"]),
        ({"country_code": "pT"}, "rotulo", NORMALIZADO["rotulo"]),
        ({"formatted": "\x00\x0bRua\x0b\x00"}, "rotulo", "Rua"),
        ({"formatted": " Rua Augusta 24 "}, "rotulo", " Rua Augusta 24 "),
        ({"formatted": " "}, "rotulo", " "),
        ({"formatted": "﻿Rua﻿"}, "rotulo", "﻿Rua﻿"),
        ({"formatted": "\x0cRua\x0c"}, "rotulo", "\x0cRua\x0c"),
        ({"housenumber": 24}, "morada", "Rua Augusta"),
        ({"street": "\tRua Augusta\n", "housenumber": "\r24\x0b"}, "morada", "Rua Augusta 24"),
        ({"postcode": "1100-048\n"}, "codigo_postal", "1100-048"),
        ({"postcode": "1100-048 "}, "codigo_postal", None),
        ({"postcode": "1100-048 "}, "codigo_postal", None),
        ({"city": " ", "town": "Sintra"}, "localidade", " "),
        ({"lat": 42.2, "lon": -6.1}, "lat", 42.2),
        ({"lat": 36.8, "lon": -9.6}, "lng", -9.6),
    ],
    ids=[
        "country_code com espaços nas pontas",
        "country_code com tab e mudança de linha",
        "country_code com maiúsculas e minúsculas",
        "o trim do PHP tira o NUL e o \\x0B",
        "o trim do PHP não tira o espaço sem quebra",
        "um rótulo só com um espaço sem quebra conta",
        "o trim do PHP não tira o U+FEFF",
        "o trim do PHP não tira o \\f",
        "número de polícia que não é texto fica de fora",
        "rua e número com tab, mudança de linha e \\x0B nas pontas",
        "código postal com mudança de linha no fim",
        "código postal com espaço sem quebra no fim",
        "código postal com separador de linha no fim",
        "city só com um espaço sem quebra não passa à seguinte",
        "canto nordeste da caixa de Portugal",
        "canto sudoeste da caixa de Portugal",
    ],
)
def test_os_textos_seguem_o_trim_e_o_strtolower_do_php(alteracoes, campo, esperado):
    """Conferidos com o PHP: o `trim()` só tira `" \\t\\n\\r\\0\\x0B"` e o
    `strtolower` só mexe no ASCII. Diferente do `texto.aparar` das escritas, de
    propósito: é a porta fiel; a pessoa revê a sugestão e a loja, ao gravar, é
    aparada pelo validador."""
    normalizados = normalizar_autocomplete(_resposta(_resultado(**alteracoes)))

    assert len(normalizados) == 1
    _mesmo(normalizados[0][campo], esperado)


def test_results_que_e_um_objeto_percorre_os_valores_como_o_php():
    """Conferido com o PHP: o `json_decode(…, true)` faz de um objeto JSON um
    array, e o `foreach` percorre-lhe os valores pela ordem."""
    resposta = json.loads('{"results": {"b": ' + json.dumps(RESULTADO) + ', "a": 1}}')

    _mesmo(normalizar_autocomplete(resposta), [NORMALIZADO])


@pytest.mark.parametrize(
    "resposta",
    [[{"results": [RESULTADO]}], [], None, "texto", 1, True],
    ids=[
        "uma lista JSON (no PHP, um array sem 'results')",
        "uma lista vazia",
        "null",
        "um texto",
        "um número",
        "um booleano",
    ],
)
def test_uma_resposta_que_nao_e_um_objeto_nao_tem_resultados(resposta):
    """A lista conferida com o PHP. O cliente do autónomo dava falha (503) a um
    JSON que não fosse objeto nem lista; aqui a normalização também não
    rebenta com ele."""
    assert normalizar_autocomplete(resposta) == []
    assert normalizar_inversa(resposta) is None


def test_um_resultado_que_e_uma_lista_fica_de_fora():
    """Conferido com o PHP: uma lista não tem `lat` nem `lon`."""
    resposta = {"results": [[1, 2], list(RESULTADO.values()), RESULTADO]}

    _mesmo(normalizar_autocomplete(resposta), [NORMALIZADO])


def test_os_outros_campos_da_geoapify_nao_passam():
    """Nome e telefone são sempre escritos pela pessoa (dossiê §0 e §5.15): o
    `name`, o `address_line1` e o resto da Geoapify não passam para a
    sugestão."""
    resultado = _resultado(name="Pastelaria Exemplo", phone="+351 210 000 000", address_line1="Pastelaria Exemplo")

    _mesmo(normalizar_autocomplete(_resposta(resultado)), [NORMALIZADO])


def test_a_normalizacao_nao_mexe_na_resposta():
    resposta = _gravada("autocomplete-rua-augusta.json")
    antes = copy.deepcopy(resposta)

    normalizar_autocomplete(resposta)
    normalizar_inversa(resposta)

    assert resposta == antes


def test_sem_limite_proprio_a_lista_e_a_que_a_geoapify_manda():
    """Como no autónomo: a normalização não corta (o limite de 5 ia no pedido
    da pesquisa, que saiu na G18; a inversa fica com o primeiro válido)."""
    resposta = _resposta(*[_resultado(housenumber=str(n)) for n in range(1, 8)])

    assert [n["morada"] for n in normalizar_autocomplete(resposta)] == [f"Rua Augusta {n}" for n in range(1, 8)]
    assert normalizar_inversa(resposta)["morada"] == "Rua Augusta 1"


# --- G18 do plano do mapa Google: a Geoapify fica só para a morada inversa ------------------


def test_a_pesquisa_saiu_do_servico_e_fica_a_inversa():
    """A pesquisa de moradas é a da Google, no browser: o URL do autocomplete
    e o limite de 5 saíram. Ficam o URL da inversa, os dois normalizadores (o
    da inversa assenta no `normalizar_autocomplete`, que não muda de nome), o
    cliente e o silêncio dos registos."""
    for nome in ("url_pesquisa", "LIMITE_PESQUISA"):
        assert not hasattr(geoapify, nome), nome
    for nome in ("url_inversa", "normalizar_autocomplete", "normalizar_inversa", "obter_json", "ler_json",
                 "chave_servidor", "url_base", "silenciar_registos", "FalhaServicoExterno"):
        assert hasattr(geoapify, nome), nome


def test_nenhum_codigo_do_crm_pede_o_autocomplete_da_geoapify():
    """Nem uma chamada esquecida ao `url_pesquisa`, nem o caminho
    `autocomplete` montado à mão: no código do CRM, a Geoapify só recebe o
    `reverse` (a morada sugerida do ponto do GPS)."""
    raiz = Path(geoapify.__file__).resolve().parents[1]
    ficheiros = sorted(raiz.rglob("*.py"))
    assert raiz / "morada.py" in ficheiros
    for ficheiro in ficheiros:
        codigo = ficheiro.read_text(encoding="utf-8")
        assert "url_pesquisa" not in codigo, ficheiro
        assert re.search(r"[\"'/]autocomplete[\"'?/]", codigo) is None, ficheiro
