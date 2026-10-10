"""A validação de uma loja nova (crm/dominio/validador_loja.py, `criacao`).

Porta de `ValidadorLoja::criacao` (src/Dominio/Lojas/ValidadorLoja.php) do
CRM autónomo, com todos os cenários do ValidadorLojaCriacaoTest.php e os
mesmos nomes nos `ids`. Devolve `(dados, erros)`: os dados têm sempre os 18
campos de `CAMPOS`, por essa ordem (os que faltam ficam `None`), e só se usam
quando não há erros; os erros são `{campo: mensagem pt-PT}`, também pela
ordem de `CAMPOS`. A ordem dos dicionários conta, por isso compara-se
`list(….items())` (o `==` de dois `dict` ignora a ordem), e o tipo também
(o `assertSame` do PHP: 39 → 39.0, `precisao_m` é `int`).

Adaptação do portal (plano T2.5; dossiê §5.2): `regiao_id` é `None` ou o
uuid4 em texto (minúsculas) de uma região; o inteiro do autónomo (`1`) já não
é uma região. Se a região existe decide a rota (T2.10).

Armadilhas do Python (plano §10; dossiê §2.1): `bool` nunca conta como
número (nem coordenada, nem precisão, nem região); o `round()` do Python
arredonda para o par (`arredondar` do domínio vai para longe do zero);
`json.loads` aceita NaN, Infinity e inteiros de qualquer tamanho; `in`
numa lista não é o `in_array(…, true)`.
"""
import copy
import json
import uuid

import pytest

from crm.dominio.validador_loja import CAMPOS, NOME_MAXIMO, ORIGENS, TEXTOS, criacao

TELEFONE = "O telefone tem de ter 9 a 15 algarismos (aceita + e espaços)."
DIAS = "Os dias têm de ser seg, ter, qua, qui, sex, sab ou dom."
POSTAL = "O código postal tem de ter o formato 0000-000."
REGIAO = "A região não é válida."
GPS = "Localização imprecisa — ajuste o pino"
FORA = "Fora de Portugal"
FORMATO_HORA = "A hora tem de estar no formato HH:MM."
ORIGEM_INVALIDA = "A origem das coordenadas não é válida."

# Um uuid4 como os que o portal grava (`str(uuid.uuid4())`): minúsculas, a
# versão 4 no 13.º algarismo e a variante (8, 9, a ou b) no 17.º.
REGIAO_ID = "5b0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e5f"


def minima(alteracoes=None):
    """Uma loja válida só com os obrigatórios, com as alterações por cima (o `minima()` do PHP)."""
    return {
        "nome": "Café Central",
        "fase": "potencial",
        "lat": 38.7075,
        "lng": -9.1364,
        "origem_coords": "pin_manual",
        **(alteracoes or {}),
    }


def erros_de(alteracoes):
    return list(criacao(minima(alteracoes))[1].items())


def mesmo_valor(a, b):
    """O `assertSame` do PHP: o mesmo valor e o mesmo tipo (True não é 1, 39 não é 39.0)."""
    return type(a) is type(b) and a == b


# --- As constantes ---


def test_os_campos_sao_os_da_tabela_da_loja_por_ordem():
    assert CAMPOS == (
        "nome", "fase", "regiao_id", "morada", "codigo_postal", "localidade",
        "lat", "lng", "origem_coords", "precisao_m", "telefone", "pessoa_contacto", "notas",
        "janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim", "dias_fechada",
    )


def test_as_origens_os_textos_e_o_tamanho_do_nome():
    assert ORIGENS == ("pin_manual", "gps", "geocoder")
    assert NOME_MAXIMO == 150
    assert TEXTOS == {
        "morada": ("A morada", 255),
        "localidade": ("A localidade", 100),
        "pessoa_contacto": ("A pessoa de contacto", 100),
    }


# --- ValidadorLojaCriacaoTest.php ---


def test_so_com_os_obrigatorios_os_outros_campos_ficam_vazios():
    dados, erros = criacao(minima())

    assert erros == {}
    assert list(dados.items()) == [
        ("nome", "Café Central"),
        ("fase", "potencial"),
        ("regiao_id", None),
        ("morada", None),
        ("codigo_postal", None),
        ("localidade", None),
        ("lat", 38.7075),
        ("lng", -9.1364),
        ("origem_coords", "pin_manual"),
        ("precisao_m", None),
        ("telefone", None),
        ("pessoa_contacto", None),
        ("notas", None),
        ("janela1_inicio", None),
        ("janela1_fim", None),
        ("janela2_inicio", None),
        ("janela2_fim", None),
        ("dias_fechada", []),
    ]
    assert type(dados["lat"]) is float and type(dados["lng"]) is float


def test_normaliza_uma_loja_completa():
    dados, erros = criacao({
        "nome": "  Gelataria do Rato ",
        "fase": "contactada",
        "regiao_id": REGIAO_ID,
        "morada": " Rua do Salitre 1 ",
        "codigo_postal": " 1250-198 ",
        "localidade": "Lisboa",
        "lat": 38.72240049,
        "lng": -9.1452,
        "origem_coords": "gps",
        "precisao_m": 12.4,
        "telefone": " +351  912 345   678 ",
        "pessoa_contacto": " Ana ",
        "notas": " Descarga pela porta lateral.\nFérias em agosto. ",
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
        "janela2_inicio": "15:00",
        "janela2_fim": "19:00",
        "dias_fechada": ["dom", "sab"],
    })

    assert erros == {}
    assert list(dados.items()) == [
        ("nome", "Gelataria do Rato"),
        ("fase", "contactada"),
        ("regiao_id", REGIAO_ID),
        ("morada", "Rua do Salitre 1"),
        ("codigo_postal", "1250-198"),
        ("localidade", "Lisboa"),
        ("lat", 38.7224),
        ("lng", -9.1452),
        ("origem_coords", "gps"),
        ("precisao_m", 12),
        ("telefone", "+351 912 345 678"),
        ("pessoa_contacto", "Ana"),
        ("notas", "Descarga pela porta lateral.\nFérias em agosto."),
        ("janela1_inicio", "10:00"),
        ("janela1_fim", "13:00"),
        ("janela2_inicio", "15:00"),
        ("janela2_fim", "19:00"),
        ("dias_fechada", ["sab", "dom"]),
    ]
    assert type(dados["precisao_m"]) is int


def test_ignora_os_campos_que_nao_sao_da_loja():
    dados, erros = criacao(minima({
        "id": 99,
        "fase_desde": "2020-01-01 00:00:00",
        "criado_por": 1,
        "criado_em": "2020-01-01 00:00:00",
        "atualizado_em": "2020-01-01T00:00:00.000000Z",
        "ultima_interacao_em": "2020-01-01 00:00:00",
        "confirmar_duplicado": True,
    }))

    assert erros == {}
    assert tuple(dados) == CAMPOS


def test_sem_nada_diz_o_que_falta_nos_obrigatorios():
    assert list(criacao({})[1].items()) == [
        ("nome", "Indique o nome."),
        ("fase", "Indique a fase."),
        ("lat", "Coloque o pino no mapa."),
        ("lng", "Coloque o pino no mapa."),
        ("origem_coords", "Indique a origem das coordenadas."),
    ]


CASOS_NOME = [
    ("nome vazio", {"nome": ""}, {"nome": "Indique o nome."}),
    ("nome só com espaços", {"nome": "   "}, {"nome": "Indique o nome."}),
    ("nome nulo", {"nome": None}, {"nome": "Indique o nome."}),
    ("nome que não é texto", {"nome": 123}, {"nome": "Indique o nome."}),
    ("nome com 151 caracteres", {"nome": "a" * 151}, {"nome": "O nome tem no máximo 150 caracteres."}),
    ("nome com 150 caracteres e espaços nas pontas", {"nome": " " + "a" * 150 + " "}, {}),
    ("nome só com um espaço sem quebra", {"nome": " "}, {"nome": "Indique o nome."}),
    ("nome só com um espaço ideográfico", {"nome": "　"}, {"nome": "Indique o nome."}),
    ("nome só com um espaço em m", {"nome": " "}, {"nome": "Indique o nome."}),
    ("nome só com espaços misturados", {"nome": "\t  ﻿"}, {"nome": "Indique o nome."}),
    ("nome só com o separador de vogais mongol (U+180E)", {"nome": "\u180e"}, {"nome": "Indique o nome."}),
]

CASOS_FASE = [
    ("fase nula", {"fase": None}, {"fase": "Indique a fase."}),
    ("fase vazia", {"fase": ""}, {"fase": "Indique a fase."}),
    ("fase desconhecida", {"fase": "arquivada"}, {"fase": "A fase não é válida."}),
    ("fase com maiúscula", {"fase": "Cliente"}, {"fase": "A fase não é válida."}),
    ("fase que não é texto", {"fase": 1}, {"fase": "A fase não é válida."}),
]

CASOS_COORDENADAS = [
    ("latitude em texto", {"lat": "38.7075"}, {"lat": "A latitude tem de ser um número."}),
    ("longitude em texto", {"lng": "-9.1364"}, {"lng": "A longitude tem de ser um número."}),
    ("latitude verdadeira", {"lat": True}, {"lat": "A latitude tem de ser um número."}),
    ("longitude infinita", {"lng": float("-inf")}, {"lng": "A longitude tem de ser um número."}),
    ("latitude nula", {"lat": None}, {"lat": "Coloque o pino no mapa."}),
    ("nos limites da caixa (sudoeste)", {"lat": 36.8, "lng": -9.6}, {}),
    ("nos limites da caixa (nordeste)", {"lat": 42.2, "lng": -6.1}, {}),
    ("a sul do continente", {"lat": 36.79}, {"lat": FORA}),
    ("a norte do continente", {"lat": 42.21}, {"lat": FORA}),
    ("a oeste do continente", {"lng": -9.61}, {"lng": FORA}),
    ("em Espanha (Madrid)", {"lat": 40.4168, "lng": -3.7038}, {"lng": FORA}),
    ("na Madeira (a carrinha não serve as ilhas)", {"lat": 32.65, "lng": -16.9}, {"lat": FORA, "lng": FORA}),
    ("nos Açores", {"lat": 37.74, "lng": -25.67}, {"lng": FORA}),
    ("em 0,0", {"lat": 0, "lng": 0}, {"lat": FORA, "lng": FORA}),
    ("origem nula", {"origem_coords": None}, {"origem_coords": "Indique a origem das coordenadas."}),
    ("origem desconhecida", {"origem_coords": "google"}, {"origem_coords": ORIGEM_INVALIDA}),
    ("origem com maiúsculas", {"origem_coords": "GPS"}, {"origem_coords": ORIGEM_INVALIDA}),
]

CASOS_TELEFONE = [
    ("telefone com 8 algarismos", {"telefone": "91234567"}, {"telefone": TELEFONE}),
    ("telefone com 16 algarismos", {"telefone": "+351 912 345 678 9012"}, {"telefone": TELEFONE}),
    ("telefone com hífens", {"telefone": "912-345-678"}, {"telefone": TELEFONE}),
    ("telefone com parênteses", {"telefone": "(+351) 912345678"}, {"telefone": TELEFONE}),
    ("telefone com letras", {"telefone": "91234567a"}, {"telefone": TELEFONE}),
    ("telefone com + no meio", {"telefone": "351+912345678"}, {"telefone": TELEFONE}),
    ("telefone com dois +", {"telefone": "++351912345678"}, {"telefone": TELEFONE}),
    ("telefone só com +", {"telefone": "+"}, {"telefone": TELEFONE}),
    ("telefone com tabulação no meio", {"telefone": "912\t345678"}, {"telefone": TELEFONE}),
    ("telefone em número", {"telefone": 912345678}, {"telefone": TELEFONE}),
]

CASOS_OUTROS_CAMPOS = [
    ("código postal sem hífen", {"codigo_postal": "1250198"}, {"codigo_postal": POSTAL}),
    ("código postal curto", {"codigo_postal": "1250-19"}, {"codigo_postal": POSTAL}),
    ("código postal com letras", {"codigo_postal": "abcd-efg"}, {"codigo_postal": POSTAL}),
    ("código postal com algarismos árabes", {"codigo_postal": "١٢٥٠-١٩٨"}, {"codigo_postal": POSTAL}),
    ("código postal em número", {"codigo_postal": 1250198}, {"codigo_postal": POSTAL}),
    ("morada com 256 caracteres", {"morada": "m" * 256}, {"morada": "A morada tem no máximo 255 caracteres."}),
    (
        "localidade com 101 caracteres",
        {"localidade": "l" * 101},
        {"localidade": "A localidade tem no máximo 100 caracteres."},
    ),
    (
        "pessoa de contacto com 101 caracteres",
        {"pessoa_contacto": "p" * 101},
        {"pessoa_contacto": "A pessoa de contacto tem no máximo 100 caracteres."},
    ),
    ("notas com mais de 65 535 bytes", {"notas": "é" * 32768}, {"notas": "As notas são demasiado compridas."}),
    ("morada que não é texto", {"morada": ["Rua"]}, {"morada": "Tem de ser texto."}),
    ("notas que não são texto", {"notas": 42}, {"notas": "Tem de ser texto."}),
    ("região em texto", {"regiao_id": "3"}, {"regiao_id": REGIAO}),
    ("região zero", {"regiao_id": 0}, {"regiao_id": REGIAO}),
    ("região negativa", {"regiao_id": -1}, {"regiao_id": REGIAO}),
    ("região decimal", {"regiao_id": 1.0}, {"regiao_id": REGIAO}),
    ("região verdadeira", {"regiao_id": True}, {"regiao_id": REGIAO}),
    ("dia desconhecido", {"dias_fechada": ["domingo"]}, {"dias_fechada": DIAS}),
    ("dia com maiúscula", {"dias_fechada": ["Sab"]}, {"dias_fechada": DIAS}),
    ("dia em número", {"dias_fechada": [7]}, {"dias_fechada": DIAS}),
    ("dias num texto", {"dias_fechada": "sab,dom"}, {"dias_fechada": DIAS}),
    ("dias num objeto", {"dias_fechada": {"a": "sab"}}, {"dias_fechada": DIAS}),
    ("dias repetidos", {"dias_fechada": ["sab", "dom", "sab"]}, {"dias_fechada": "Há dias repetidos."}),
    (
        "hora inválida",
        {"janela1_inicio": "25:00", "janela1_fim": "13:00"},
        {"janela1_inicio": FORMATO_HORA},
    ),
    ("janela incoerente", {"janela1_inicio": "10:00"}, {"janela1_fim": "Indique também o fim."}),
]

CASOS = CASOS_NOME + CASOS_FASE + CASOS_COORDENADAS + CASOS_TELEFONE + CASOS_OUTROS_CAMPOS


@pytest.mark.parametrize(
    "alteracoes, erros",
    [caso[1:] for caso in CASOS],
    ids=[caso[0] for caso in CASOS],
)
def test_valida_cada_campo(alteracoes, erros):
    assert erros_de(alteracoes) == list(erros.items())


NORMALIZACOES = [
    ("nome com 150 caracteres (os acentos contam como um)", "nome", "é" * 150, "é" * 150),
    ("nome sem os espaços Unicode nas pontas", "nome", "  Loja 　", "Loja"),
    ("nome com um espaço sem quebra no meio", "nome", "Café Central", "Café Central"),
    ("cada fase: perdida", "fase", "perdida", "perdida"),
    ("cada fase: cliente", "fase", "cliente", "cliente"),
    ("latitude arredondada a 6 casas (para baixo)", "lat", 38.1234564, 38.123456),
    ("latitude arredondada a 6 casas (para cima)", "lat", 38.1234566, 38.123457),
    ("latitude inteira", "lat", 39, 39.0),
    ("latitude que arredondada fica no limite", "lat", 36.7999996, 36.8),
    ("longitude arredondada a 6 casas", "lng", -9.13640049, -9.1364),
    ("telefone só com algarismos", "telefone", "912345678", "912345678"),
    ("telefone com 9 algarismos", "telefone", "212 345 678", "212 345 678"),
    ("telefone com 15 algarismos", "telefone", "+351 912 345 678 901", "+351 912 345 678 901"),
    ("telefone com espaço depois do +", "telefone", "+ 351 912345678", "+351 912345678"),
    ("telefone com 00 em vez de +", "telefone", "00351 912 345 678", "00351 912 345 678"),
    ("telefone vazio", "telefone", "   ", None),
    ("telefone nulo", "telefone", None, None),
    ("código postal vazio", "codigo_postal", "", None),
    ("morada com 255 caracteres", "morada", "m" * 255, "m" * 255),
    ("morada vazia", "morada", "  ", None),
    ("morada só com um espaço sem quebra", "morada", " ", None),
    ("localidade sem os espaços Unicode nas pontas", "localidade", "　Lisboa ", "Lisboa"),
    ("localidade com 100 caracteres", "localidade", "l" * 100, "l" * 100),
    ("pessoa de contacto com 100 caracteres", "pessoa_contacto", "p" * 100, "p" * 100),
    ("notas com 65 535 bytes", "notas", "n" * 65535, "n" * 65535),
    ("notas vazias", "notas", "", None),
    ("região", "regiao_id", REGIAO_ID, REGIAO_ID),
    ("sem região", "regiao_id", None, None),
    ("dias fechada pela ordem da semana", "dias_fechada", ["dom", "qua", "seg"], ["seg", "qua", "dom"]),
    (
        "todos os dias",
        "dias_fechada",
        ["seg", "ter", "qua", "qui", "sex", "sab", "dom"],
        ["seg", "ter", "qua", "qui", "sex", "sab", "dom"],
    ),
    ("sem dias fechada", "dias_fechada", [], []),
    ("dias fechada nulos", "dias_fechada", None, []),
    ("hora vazia", "janela2_inicio", "", None),
]


@pytest.mark.parametrize(
    "campo, enviado, guardado",
    [caso[1:] for caso in NORMALIZACOES],
    ids=[caso[0] for caso in NORMALIZACOES],
)
def test_normaliza_cada_campo(campo, enviado, guardado):
    dados, erros = criacao(minima({campo: enviado}))

    assert erros == {}
    assert mesmo_valor(dados[campo], guardado)


@pytest.mark.parametrize("origem", ["pin_manual", "geocoder"], ids=["pino manual", "pesquisa de morada"])
def test_sem_gps_a_precisao_fica_nula(origem):
    dados, erros = criacao(minima({"origem_coords": origem, "precisao_m": 999}))

    assert erros == {}
    assert dados["origem_coords"] == origem
    assert dados["precisao_m"] is None


def test_gps_com_50_metros_e_aceite():
    dados, erros = criacao(minima({"origem_coords": "gps", "precisao_m": 50}))

    assert erros == {}
    assert mesmo_valor(dados["precisao_m"], 50)


@pytest.mark.parametrize(
    "precisao",
    [{"precisao_m": 51}, {"precisao_m": 80}, {"precisao_m": None}, {}, {"precisao_m": "10"}],
    ids=["51 m", "80 m", "nula", "sem precisão", "texto"],
)
def test_gps_sem_precisao_ate_50_metros_e_recusado(precisao):
    assert erros_de({"origem_coords": "gps", **precisao}) == [("precisao_m", GPS)]


def test_as_janelas_so_se_comparam_quando_todas_as_horas_sao_validas():
    assert erros_de({"janela1_inicio": "9:00", "janela1_fim": "08:00"}) == [("janela1_inicio", FORMATO_HORA)]


def test_devolve_os_erros_de_todos_os_campos_de_uma_vez():
    erros = criacao(minima({
        "nome": "",
        "telefone": "123",
        "lat": 32.65,
        "janela1_inicio": "13:00",
        "janela1_fim": "10:00",
    }))[1]

    assert list(erros) == ["nome", "lat", "telefone", "janela1_fim"]


# --- Adaptação do portal: a região é um uuid4 em texto ---


def test_regiao_aceita_os_uuid4_que_o_portal_grava():
    for _ in range(50):
        regiao_id = str(uuid.uuid4())
        dados, erros = criacao(minima({"regiao_id": regiao_id}))

        assert erros == {}
        assert dados["regiao_id"] == regiao_id


@pytest.mark.parametrize(
    "regiao_id",
    [
        1,
        0,
        True,
        False,
        "3",
        "",
        " ",
        1.0,
        REGIAO_ID.upper(),
        "5B0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e5f",
        "5b0c6f1e-2D3a-4b8c-9e7f-0a1b2c3d4e5f",
        "5b0c6f1e-2d3a-4B8c-9e7f-0a1b2c3d4e5f",
        "5b0c6f1e-2d3a-4b8c-9E7f-0a1b2c3d4e5f",
        "5b0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e5F",
        " " + REGIAO_ID,
        REGIAO_ID + " ",
        REGIAO_ID + "\n",
        REGIAO_ID.replace("-", ""),
        "{" + REGIAO_ID + "}",
        "urn:uuid:" + REGIAO_ID,
        REGIAO_ID[:-1],
        REGIAO_ID + "0",
        "5b0c6f1e-2d3a-1b8c-9e7f-0a1b2c3d4e5f",
        "5b0c6f1e-2d3a-4b8c-7e7f-0a1b2c3d4e5f",
        "5b0c6f1e-2d3a-4b8c-ce7f-0a1b2c3d4e5f",
        "00000000-0000-0000-0000-000000000000",
        "5b0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e5g",
        "5b0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e٥f",
        "5b0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e５f",
        [REGIAO_ID],
        {"$ne": None},
        {"$gt": ""},
        {"id": REGIAO_ID},
    ],
    ids=[
        "o inteiro do autónomo",
        "zero",
        "verdadeira",
        "falsa",
        "número em texto",
        "vazia",
        "só um espaço",
        "decimal",
        "uuid em maiúsculas",
        "uuid com uma maiúscula no 1.º grupo",
        "uuid com uma maiúscula no 2.º grupo",
        "uuid com uma maiúscula no 3.º grupo",
        "uuid com uma maiúscula no 4.º grupo",
        "uuid com uma maiúscula no 5.º grupo",
        "uuid com espaço antes",
        "uuid com espaço depois",
        "uuid com mudança de linha no fim",
        "uuid sem hífenes",
        "uuid entre chavetas",
        "uuid com urn",
        "uuid curto",
        "uuid comprido",
        "uuid da versão 1",
        "uuid com a variante 7",
        "uuid com a variante c",
        "uuid nulo",
        "uuid com uma letra que não é hexadecimal",
        "uuid com um algarismo árabe",
        "uuid com um algarismo de largura total",
        "uuid numa lista",
        "operador $ne do Mongo",
        "operador $gt do Mongo",
        "objeto com o id",
    ],
)
def test_regiao_recusa_o_que_nao_e_um_uuid4_em_texto(regiao_id):
    dados, erros = criacao(minima({"regiao_id": regiao_id}))

    assert list(erros.items()) == [("regiao_id", REGIAO)]
    assert dados["regiao_id"] is None


# --- Armadilhas do Python ---


@pytest.mark.parametrize(
    "alteracoes, erros",
    [
        ({"lat": False}, {"lat": "A latitude tem de ser um número."}),
        ({"lng": True}, {"lng": "A longitude tem de ser um número."}),
        ({"lat": float("nan")}, {"lat": "A latitude tem de ser um número."}),
        ({"lat": float("inf")}, {"lat": "A latitude tem de ser um número."}),
        ({"lat": [38.7075]}, {"lat": "A latitude tem de ser um número."}),
        ({"lng": {"$gt": 0}}, {"lng": "A longitude tem de ser um número."}),
        (
            {"lat": "", "lng": ""},
            {"lat": "A latitude tem de ser um número.", "lng": "A longitude tem de ser um número."},
        ),
        ({"lat": 10**400}, {"lat": "A latitude tem de ser um número."}),
        ({"lat": 2**63}, {"lat": FORA}),
        ({"lat": -0.0, "lng": -0.0}, {"lat": FORA, "lng": FORA}),
        ({"lat": 42.2000005}, {"lat": FORA}),
        ({"lng": -9.6000005}, {"lng": FORA}),
        ({"lat": 36.7999995}, {}),
        ({"lng": -6.0999995}, {}),
    ],
    ids=[
        "latitude falsa (em Python seria 0)",
        "longitude verdadeira (em Python seria 1)",
        "latitude NaN",
        "latitude infinita",
        "latitude numa lista",
        "longitude num objeto",
        "coordenadas vazias",
        "latitude que nem num float cabe (o PHP lia INF)",
        "latitude fora dos 64 bits (o PHP lia um float)",
        "menos zero",
        "latitude a norte depois de arredondada",
        "longitude a oeste depois de arredondada",
        "latitude que arredondada para longe do zero fica no limite sul",
        "longitude que arredondada para longe do zero fica no limite leste",
    ],
)
def test_coordenadas_armadilhas_do_python(alteracoes, erros):
    assert erros_de(alteracoes) == list(erros.items())


@pytest.mark.parametrize(
    "texto_json, erro",
    [
        ("NaN", "A latitude tem de ser um número."),
        ("Infinity", "A latitude tem de ser um número."),
        ("-Infinity", "A latitude tem de ser um número."),
        ("1e400", "A latitude tem de ser um número."),
        ("9223372036854775808", FORA),
        ("38.7075", None),
        ("39", None),
    ],
    ids=["NaN", "Infinity", "-Infinity", "1e400", "2**63", "decimal", "inteiro"],
)
def test_latitude_lida_pelo_json_loads(texto_json, erro):
    corpo = json.loads('{"nome": "Café", "fase": "potencial", "lng": -9.1364, "origem_coords": "pin_manual", '
                       f'"lat": {texto_json}}}')

    assert list(criacao(corpo)[1].items()) == ([] if erro is None else [("lat", erro)])


@pytest.mark.parametrize(
    "enviado, guardado",
    [
        (42.1999995, 42.2),
        (-9.5999995, -9.6),
        (39.0000005, 39.000001),
        (41.1500005, 41.150001),
        (-8.6100005, -8.610001),
        (-9.1452005, -9.145201),
    ],
    ids=[
        "latitude 42,1999995 (o round do Python dava 42,199999)",
        "longitude −9,5999995 (o round do Python dava −9,599999)",
        "latitude 39,0000005 (o round do Python dava 39,0)",
        "latitude 41,1500005 (o round do Python dava 41,15)",
        "longitude −8,6100005 (o round do Python dava −8,61)",
        "longitude −9,1452005 (o round do Python dava −9,1452)",
    ],
)
def test_coordenadas_arredondadas_meio_para_longe_do_zero(enviado, guardado):
    campo = "lat" if enviado > 0 else "lng"
    dados, erros = criacao(minima({campo: enviado}))

    assert erros == {}
    assert mesmo_valor(dados[campo], guardado)


def test_coordenada_fora_de_portugal_fica_nos_dados_arredondada():
    # Como no PHP: o erro é "Fora de Portugal", mas o valor arredondado fica
    # nos dados (que só se usam sem erros).
    dados, erros = criacao(minima({"lat": 32.6500004, "lng": -16.9000006}))

    assert list(erros.items()) == [("lat", FORA), ("lng", FORA)]
    assert mesmo_valor(dados["lat"], 32.65)
    assert mesmo_valor(dados["lng"], -16.900001)


@pytest.mark.parametrize(
    "precisao, guardada",
    [
        (12.5, 13),
        (0.5, 1),
        (2.5, 3),
        (49.5, 50),
        (50.4, 50),
        (50.49999999999999, 50),
        (0, 0),
        (-0.0, 0),
        (12, 12),
        (12.0, 12),
    ],
    ids=[
        "12,5 m (o round do Python dava 12)",
        "0,5 m (o round do Python dava 0)",
        "2,5 m (o round do Python dava 2)",
        "49,5 m",
        "50,4 m",
        "50,49999999999999 m",
        "0 m",
        "menos zero",
        "inteiro",
        "decimal redondo",
    ],
)
def test_gps_guarda_a_precisao_inteira_arredondada_para_longe_do_zero(precisao, guardada):
    dados, erros = criacao(minima({"origem_coords": "gps", "precisao_m": precisao}))

    assert erros == {}
    assert mesmo_valor(dados["precisao_m"], guardada)


@pytest.mark.parametrize(
    "precisao",
    [50.5, True, False, -1, -0.4, float("inf"), float("nan"), 2**63, 10**400, [10], {"m": 10}],
    ids=[
        "50,5 m (o round do Python dava 50)",
        "verdadeira (em Python seria 1 m)",
        "falsa (em Python seria 0 m)",
        "negativa",
        "−0,4 m",
        "infinita",
        "NaN",
        "fora dos 64 bits",
        "que nem num float cabe",
        "numa lista",
        "num objeto",
    ],
)
def test_gps_recusa_estas_precisoes(precisao):
    dados, erros = criacao(minima({"origem_coords": "gps", "precisao_m": precisao}))

    assert list(erros.items()) == [("precisao_m", GPS)]
    assert dados["precisao_m"] is None


@pytest.mark.parametrize(
    "origem, precisao",
    [
        ("pin_manual", True),
        ("pin_manual", "10"),
        ("geocoder", -5),
        ("geocoder", float("nan")),
        ("pin_manual", {"$gt": 0}),
        ("pin_manual", 12),
        ("geocoder", 0),
        ("geocoder", 50.4),
    ],
    ids=[
        "verdadeira",
        "texto",
        "negativa",
        "NaN",
        "objeto",
        "aceitável com o pino manual",
        "zero com a pesquisa de morada",
        "50,4 m com a pesquisa de morada",
    ],
)
def test_sem_gps_a_precisao_nem_se_valida(origem, precisao):
    dados, erros = criacao(minima({"origem_coords": origem, "precisao_m": precisao}))

    assert erros == {}
    assert dados["precisao_m"] is None


@pytest.mark.parametrize(
    "origem, erro",
    [
        ("", "Indique a origem das coordenadas."),
        (" gps", ORIGEM_INVALIDA),
        ("gps ", ORIGEM_INVALIDA),
        ("gps\n", ORIGEM_INVALIDA),
        ("Gps", ORIGEM_INVALIDA),
        (" ", ORIGEM_INVALIDA),
        (True, ORIGEM_INVALIDA),
        (1, ORIGEM_INVALIDA),
        (0, ORIGEM_INVALIDA),
        (["gps"], ORIGEM_INVALIDA),
        ({"gps": 1}, ORIGEM_INVALIDA),
    ],
    ids=[
        "vazia",
        "com espaço antes",
        "com espaço depois",
        "com mudança de linha",
        "com maiúscula",
        "só um espaço",
        "verdadeira",
        "um",
        "zero",
        "numa lista",
        "num objeto",
    ],
)
def test_origem_armadilhas_do_python(origem, erro):
    # Nem a precisão se valida: só a origem "gps", tal e qual, a exige.
    dados, erros = criacao(minima({"origem_coords": origem, "precisao_m": 999}))

    assert list(erros.items()) == [("origem_coords", erro)]
    assert dados["origem_coords"] is None
    assert dados["precisao_m"] is None


def test_precisao_sem_origem_so_diz_que_falta_a_origem():
    corpo = minima({"precisao_m": 999})
    del corpo["origem_coords"]

    assert list(criacao(corpo)[1].items()) == [("origem_coords", "Indique a origem das coordenadas.")]


@pytest.mark.parametrize(
    "fase",
    [" cliente", "cliente ", "cliente\n", " ", True, False, 0, 4, ["cliente"], {"fase": "cliente"}],
    ids=[
        "com espaço antes",
        "com espaço depois",
        "com mudança de linha",
        "só um espaço",
        "verdadeira",
        "falsa",
        "zero",
        "a posição de cliente",
        "numa lista",
        "num objeto",
    ],
)
def test_fase_armadilhas_do_python(fase):
    dados, erros = criacao(minima({"fase": fase}))

    assert list(erros.items()) == [("fase", "A fase não é válida.")]
    assert dados["fase"] is None


@pytest.mark.parametrize(
    "nome, guardado",
    [
        ("﻿Café Central﻿", "Café Central"),
        ("Café Central\n", "Café Central"),
        (" Café ", "Café"),
        ("🍧" * 150, "🍧" * 150),
        ("  Café  do  Largo  ", "Café  do  Largo"),
    ],
    ids=[
        "U+FEFF nas pontas (o str.strip() não o tira)",
        "mudança de linha no fim",
        "separadores de linha e de parágrafo nas pontas",
        "150 emojis (cada um conta como um)",
        "os espaços do meio ficam",
    ],
)
def test_nome_armadilhas_aceites(nome, guardado):
    dados, erros = criacao(minima({"nome": nome}))

    assert erros == {}
    assert dados["nome"] == guardado


@pytest.mark.parametrize(
    "nome, erro",
    [
        (True, "Indique o nome."),
        (False, "Indique o nome."),
        (0, "Indique o nome."),
        (["Café"], "Indique o nome."),
        ({"nome": "Café"}, "Indique o nome."),
        ("﻿", "Indique o nome."),
        ("🍧" * 151, "O nome tem no máximo 150 caracteres."),
        (" " + "a" * 151 + " ", "O nome tem no máximo 150 caracteres."),
    ],
    ids=[
        "verdadeiro",
        "falso",
        "zero",
        "numa lista",
        "num objeto",
        "só o U+FEFF",
        "151 emojis",
        "151 caracteres entre espaços sem quebra",
    ],
)
def test_nome_armadilhas_recusadas(nome, erro):
    assert erros_de({"nome": nome}) == [("nome", erro)]


def test_os_dados_de_uma_loja_vazia_sao_os_do_autonomo():
    # O que o PHP 8.4.26 devolve em `ValidadorLoja::criacao([])[0]`: o nome
    # que não é texto fica "", as outras coisas sem valor ficam None e os dias
    # []. Com erros, estes dados não se gravam.
    assert list(criacao({})[0].items()) == [
        ("nome", ""), ("fase", None), ("regiao_id", None), ("morada", None), ("codigo_postal", None),
        ("localidade", None), ("lat", None), ("lng", None), ("origem_coords", None), ("precisao_m", None),
        ("telefone", None), ("pessoa_contacto", None), ("notas", None), ("janela1_inicio", None),
        ("janela1_fim", None), ("janela2_inicio", None), ("janela2_fim", None), ("dias_fechada", []),
    ]


def test_um_nome_comprido_fica_nos_dados_aparado():
    # Como no PHP: com o erro do tamanho, o nome aparado fica nos dados.
    dados, erros = criacao(minima({"nome": " " + "a" * 151 + " "}))

    assert list(erros) == ["nome"]
    assert dados["nome"] == "a" * 151


def test_os_dados_vem_sempre_pela_ordem_dos_campos():
    corpo = dict(reversed(list(minima({
        "dias_fechada": ["sab"],
        "notas": "x",
        "janela1_fim": "13:00",
        "janela1_inicio": "10:00",
        "regiao_id": REGIAO_ID,
        "telefone": "912345678",
    }).items())))

    dados, erros = criacao(corpo)

    assert erros == {}
    assert tuple(dados) == CAMPOS


def test_os_erros_vem_sempre_pela_ordem_dos_campos():
    corpo = dict(reversed(list({
        "nome": "",
        "fase": "x",
        "regiao_id": 1,
        "morada": ["m"],
        "codigo_postal": "x",
        "localidade": 1,
        "lat": "x",
        "lng": "x",
        "origem_coords": "x",
        "telefone": "x",
        "pessoa_contacto": 1,
        "notas": 1,
        "janela1_inicio": "x",
        "janela1_fim": "x",
        "janela2_inicio": "x",
        "janela2_fim": "x",
        "dias_fechada": "x",
    }.items())))

    assert tuple(criacao(corpo)[1]) == tuple(campo for campo in CAMPOS if campo != "precisao_m")


def test_chaves_parecidas_com_os_campos_ignoram_se():
    dados, erros = criacao(minima({"Nome": "Outra", " nome": "Outra", "nome ": "Outra", "LAT": 0, "regiao": 1}))

    assert erros == {}
    assert dados["nome"] == "Café Central"
    assert tuple(dados) == CAMPOS


# --- As janelas na criação ---


def test_os_erros_das_janelas_entram_pela_ordem_dos_campos():
    # O Janelas::erros dá primeiro o fim da janela 2 e depois o "Preencha
    # primeiro a janela 1."; o validador volta a pôr pela ordem de CAMPOS.
    assert erros_de({"janela2_inicio": "15:00", "dias_fechada": ["x"], "nome": ""}) == [
        ("nome", "Indique o nome."),
        ("janela2_inicio", "Preencha primeiro a janela 1."),
        ("janela2_fim", "Indique também o fim."),
        ("dias_fechada", DIAS),
    ]


@pytest.mark.parametrize(
    "horas, erros",
    [
        (
            {"janela1_inicio": "13:00", "janela1_fim": "10:00", "janela2_fim": "24:00"},
            {"janela2_fim": FORMATO_HORA},
        ),
        (
            {"janela1_inicio": "13:00", "janela1_fim": "10:00", "janela2_inicio": " 15:00", "janela2_fim": "19:00"},
            {"janela2_inicio": FORMATO_HORA},
        ),
        ({"janela1_inicio": 1000, "janela1_fim": True}, {"janela1_inicio": FORMATO_HORA, "janela1_fim": FORMATO_HORA}),
        ({"janela1_inicio": "10:00", "janela1_fim": ["13:00"]}, {"janela1_fim": FORMATO_HORA}),
        ({"janela1_inicio": "10:00\n", "janela1_fim": "09:00"}, {"janela1_inicio": FORMATO_HORA}),
        ({"janela1_inicio": "1٠:00", "janela1_fim": "09:00"}, {"janela1_inicio": FORMATO_HORA}),
    ],
    ids=[
        "uma hora má na janela 2 impede comparar a janela 1",
        "uma hora com espaço impede comparar",
        "horas que não são texto (nunca TypeError)",
        "hora numa lista",
        "hora com mudança de linha no fim",
        "hora com um algarismo árabe",
    ],
)
def test_com_uma_hora_ma_as_janelas_nao_se_comparam(horas, erros):
    assert erros_de(horas) == list(erros.items())


@pytest.mark.parametrize(
    "horas, erros",
    [
        ({"janela1_inicio": "10:00", "janela1_fim": "10:00"}, {"janela1_fim": "O fim tem de ser depois do início."}),
        ({"janela1_fim": "13:00"}, {"janela1_inicio": "Indique também o início."}),
        (
            {"janela1_inicio": "10:00", "janela1_fim": "13:00", "janela2_inicio": "13:00", "janela2_fim": "19:00"},
            {"janela2_inicio": "A janela 2 tem de começar depois do fim da janela 1."},
        ),
        ({"janela2_fim": "19:00"}, {"janela2_inicio": "Indique também o início."}),
        ({"janela1_inicio": "", "janela1_fim": "", "janela2_inicio": "", "janela2_fim": ""}, {}),
    ],
    ids=[
        "fim igual ao início",
        "só o fim da janela 1",
        "janela 2 a começar no fim da janela 1",
        "só o fim da janela 2",
        "todas as horas vazias",
    ],
)
def test_com_as_horas_validas_as_janelas_comparam_se(horas, erros):
    assert erros_de(horas) == list(erros.items())


# --- O que entra e o que sai ---


def test_nao_mexe_no_corpo_recebido():
    corpo = minima({
        "nome": "  Café  ",
        "lat": 38.72240049,
        "telefone": " +351  912 345   678 ",
        "dias_fechada": ["dom", "sab"],
        "origem_coords": "gps",
        "precisao_m": 12.4,
        "id": "x",
    })
    original = copy.deepcopy(corpo)

    criacao(corpo)

    assert corpo == original
    assert list(corpo) == list(original)


def test_devolve_estruturas_novas_em_cada_chamada():
    dias = ["seg"]
    primeiro, _ = criacao(minima({"dias_fechada": dias}))
    segundo, _ = criacao(minima({"dias_fechada": dias}))

    assert primeiro["dias_fechada"] is not dias
    assert primeiro["dias_fechada"] is not segundo["dias_fechada"]
    primeiro["nome"] = "outro"
    assert criacao(minima())[0]["nome"] == "Café Central"

