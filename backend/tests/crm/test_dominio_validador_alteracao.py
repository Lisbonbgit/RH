"""A validação de uma alteração a uma loja e as janelas em lista (crm/dominio/validador_loja.py).

`alteracao` é a porta de `ValidadorLoja::alteracao`
(src/Dominio/Lojas/ValidadorLoja.php) do CRM autónomo, com todos os cenários
do ValidadorLojaAlteracaoTest.php e os mesmos nomes nos `ids`: só as chaves
enviadas, com as regras da criação; a localização (lat, lng, origem_coords e
precisao_m) vai sempre junta; as janelas não se comparam aqui, porque a
coerência depende das horas que a loja já tem (a rota, na T2.11, chama
`janelas.erros` sobre a loja já alterada). A ordem dos dicionários conta,
por isso compara-se `list(….items())`, e o tipo também (o `assertSame` do
PHP).

`janelas_para_lista` e `campos_de_janelas` são do portal (plano §1
"Janelas"): na API as janelas são as quatro horas planas, na base ficam em
lista (`janelas: [{inicio, fim}]`, 0 a 2, por ordem). Só convertem horas já
validadas e coerentes; o resto é um erro de programação (`ValueError`), para
nunca se gravar uma janela a meio nem se perder uma janela na volta.
"""
import copy
import itertools
import json

import pytest

from crm.dominio import janelas
from crm.dominio.validador_loja import (
    CAMPOS,
    MENSAGEM_LOCALIZACAO_INCOMPLETA,
    alteracao,
    campos_de_janelas,
    criacao,
    janelas_para_lista,
)

INCOMPLETA = "A localização tem de vir completa (lat, lng e origem_coords)."
TELEFONE = "O telefone tem de ter 9 a 15 algarismos (aceita + e espaços)."
DIAS = "Os dias têm de ser seg, ter, qua, qui, sex, sab ou dom."
REGIAO = "A região não é válida."
GPS = "Localização imprecisa — ajuste o pino"
FORMATO_HORA = "A hora tem de estar no formato HH:MM."
ORIGEM_INVALIDA = "A origem das coordenadas não é válida."

REGIAO_ID = "5b0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e5f"

# Uma localização completa e válida, a base dos casos "com as regras da criação".
LOCALIZACAO = {"lat": 38.7075, "lng": -9.1364, "origem_coords": "pin_manual"}


def pares(resultado):
    """`(dados, erros)` como listas de pares: a ordem conta."""
    dados, erros = resultado
    return list(dados.items()), list(erros.items())


def mesmo_valor(a, b):
    """O `assertSame` do PHP: o mesmo valor e o mesmo tipo (True não é 1, 39 não é 39.0)."""
    return type(a) is type(b) and a == b


def test_a_mensagem_da_localizacao_incompleta():
    assert MENSAGEM_LOCALIZACAO_INCOMPLETA == INCOMPLETA


# --- ValidadorLojaAlteracaoTest.php ---


def test_sem_campos_nao_ha_nada_para_alterar():
    assert pares(alteracao({})) == ([], [])


def test_so_devolve_os_campos_enviados():
    assert pares(alteracao({"telefone": " 912  345 678 "})) == ([("telefone", "912 345 678")], [])


def test_ignora_os_campos_que_nao_sao_da_loja():
    assert pares(alteracao({
        "fase": "cliente",
        "atualizado_em": "2026-10-03T09:00:00.123456Z",
        "confirmar_duplicado": True,
        "fase_desde": "2020-01-01 00:00:00",
        "criado_por": 7,
        "id": "outra",
        "criado_em": "2020-01-01T00:00:00Z",
    })) == ([("fase", "cliente")], [])


def test_devolve_os_campos_pela_ordem_da_loja():
    dados, _ = alteracao({"notas": "x", "nome": "Café", "dias_fechada": ["seg"]})

    assert list(dados) == ["nome", "notas", "dias_fechada"]


LIMPEZAS = [
    ("telefone nulo", "telefone", None, None),
    ("telefone vazio", "telefone", "", None),
    ("sem região", "regiao_id", None, None),
    ("morada nula", "morada", None, None),
    ("pessoa de contacto só com um espaço ideográfico", "pessoa_contacto", "　", None),
    ("notas vazias", "notas", "", None),
    ("código postal nulo", "codigo_postal", None, None),
    ("hora nula", "janela1_inicio", None, None),
    ("dias fechada nulos", "dias_fechada", None, []),
    ("dias fechada vazios", "dias_fechada", [], []),
]


@pytest.mark.parametrize(
    "campo, enviado, guardado",
    [caso[1:] for caso in LIMPEZAS],
    ids=[caso[0] for caso in LIMPEZAS],
)
def test_limpar_um_campo_opcional_deixa_o_nulo(campo, enviado, guardado):
    dados, erros = alteracao({campo: enviado})

    assert erros == {}
    assert list(dados) == [campo]
    assert mesmo_valor(dados[campo], guardado)


INVALIDOS = [
    ("nome vazio", {"nome": "  "}, {"nome": "Indique o nome."}),
    ("nome nulo", {"nome": None}, {"nome": "Indique o nome."}),
    ("nome só com um espaço sem quebra", {"nome": " "}, {"nome": "Indique o nome."}),
    ("fase nula", {"fase": None}, {"fase": "Indique a fase."}),
    ("fase desconhecida", {"fase": "arquivada"}, {"fase": "A fase não é válida."}),
    ("telefone curto", {"telefone": "1234"}, {"telefone": TELEFONE}),
    ("código postal", {"codigo_postal": "1250"}, {"codigo_postal": "O código postal tem de ter o formato 0000-000."}),
    ("região em texto", {"regiao_id": "2"}, {"regiao_id": REGIAO}),
    ("dias repetidos", {"dias_fechada": ["seg", "seg"]}, {"dias_fechada": "Há dias repetidos."}),
    ("hora inválida", {"janela2_fim": "7:00"}, {"janela2_fim": FORMATO_HORA}),
    ("notas que não são texto", {"notas": False}, {"notas": "Tem de ser texto."}),
]


@pytest.mark.parametrize(
    "parcial, erros",
    [caso[1:] for caso in INVALIDOS],
    ids=[caso[0] for caso in INVALIDOS],
)
def test_usa_as_mesmas_regras_da_criacao(parcial, erros):
    assert list(alteracao(parcial)[1].items()) == list(erros.items())


def test_uma_hora_sozinha_nao_se_compara_com_as_outras():
    # A coerência das janelas depende das horas que a loja já tem: a rota
    # verifica-a com janelas.erros sobre a loja já alterada (T2.11).
    assert pares(alteracao({"janela1_fim": "13:00"})) == ([("janela1_fim", "13:00")], [])


def test_a_localizacao_completa_devolve_os_quatro_campos():
    dados, erros = alteracao({
        "lat": 41.15780049,
        "lng": -8.6296,
        "origem_coords": "pin_manual",
        "precisao_m": 30,
    })

    assert erros == {}
    assert list(dados.items()) == [
        ("lat", 41.1578),
        ("lng", -8.6296),
        ("origem_coords", "pin_manual"),
        ("precisao_m", None),
    ]


def test_a_localizacao_por_gps_guarda_a_precisao():
    dados, erros = alteracao({"lat": 41.1578, "lng": -8.6296, "origem_coords": "gps", "precisao_m": 50})

    assert erros == {}
    assert list(dados.items()) == [
        ("lat", 41.1578),
        ("lng", -8.6296),
        ("origem_coords", "gps"),
        ("precisao_m", 50),
    ]
    assert type(dados["precisao_m"]) is int


LOCALIZACOES_INCOMPLETAS = [
    ("só a latitude", {"lat": 38.7075}, {"lng": INCOMPLETA, "origem_coords": INCOMPLETA}),
    ("só a longitude", {"lng": -9.1364}, {"lat": INCOMPLETA, "origem_coords": INCOMPLETA}),
    ("latitude e longitude sem origem", {"lat": 38.7075, "lng": -9.1364}, {"origem_coords": INCOMPLETA}),
    ("só a origem", {"origem_coords": "gps"}, {"lat": INCOMPLETA, "lng": INCOMPLETA}),
    ("só a precisão", {"precisao_m": 10}, {"lat": INCOMPLETA, "lng": INCOMPLETA, "origem_coords": INCOMPLETA}),
]


@pytest.mark.parametrize(
    "parcial, erros",
    [caso[1:] for caso in LOCALIZACOES_INCOMPLETAS],
    ids=[caso[0] for caso in LOCALIZACOES_INCOMPLETAS],
)
def test_a_localizacao_incompleta_e_recusada(parcial, erros):
    assert list(alteracao(parcial)[1].items()) == list(erros.items())


def test_a_localizacao_incompleta_nao_entra_nos_dados():
    assert pares(alteracao({"nome": "Café", "lat": 38.7075}))[0] == [("nome", "Café")]


LOCALIZACOES_INVALIDAS = [
    ("fora de Portugal", {"lat": 40.4168, "lng": -3.7038}, {"lng": "Fora de Portugal"}),
    ("latitude nula", {"lat": None}, {"lat": "Coloque o pino no mapa."}),
    ("origem desconhecida", {"origem_coords": "google"}, {"origem_coords": ORIGEM_INVALIDA}),
    ("GPS com 80 m", {"origem_coords": "gps", "precisao_m": 80}, {"precisao_m": GPS}),
    ("GPS sem precisão", {"origem_coords": "gps"}, {"precisao_m": GPS}),
]


@pytest.mark.parametrize(
    "localizacao, erros",
    [caso[1:] for caso in LOCALIZACOES_INVALIDAS],
    ids=[caso[0] for caso in LOCALIZACOES_INVALIDAS],
)
def test_a_localizacao_completa_tem_as_regras_da_criacao(localizacao, erros):
    # O `$localizacao + [base]` do PHP: as chaves do caso ficam por cima da base.
    parcial = {**LOCALIZACAO, **localizacao}

    assert list(alteracao(parcial)[1].items()) == list(erros.items())


# --- Armadilhas do Python e casos a mais ---


@pytest.mark.parametrize(
    "parcial, erros",
    [
        ({"lat": None}, {"lng": INCOMPLETA, "origem_coords": INCOMPLETA}),
        ({"precisao_m": None}, {"lat": INCOMPLETA, "lng": INCOMPLETA, "origem_coords": INCOMPLETA}),
        ({"origem_coords": None, "precisao_m": None}, {"lat": INCOMPLETA, "lng": INCOMPLETA}),
    ],
    ids=["latitude nula sozinha", "precisão nula sozinha", "origem e precisão nulas"],
)
def test_uma_chave_da_localizacao_conta_mesmo_nula(parcial, erros):
    # O `array_intersect_key` do PHP vê as chaves, não os valores: `"lat": null` foi enviada.
    assert pares(alteracao(parcial)) == ([], list(erros.items()))


def test_a_localizacao_com_as_tres_chaves_nulas_e_completa_e_valida_se():
    assert pares(alteracao({"lat": None, "lng": None, "origem_coords": None})) == (
        [("lat", None), ("lng", None), ("origem_coords", None), ("precisao_m", None)],
        [
            ("lat", "Coloque o pino no mapa."),
            ("lng", "Coloque o pino no mapa."),
            ("origem_coords", "Indique a origem das coordenadas."),
        ],
    )


def test_a_localizacao_incompleta_nao_valida_os_valores_que_vieram():
    # Como no PHP: só se diz o que falta; a latitude má e a precisão má nem se olham.
    assert pares(alteracao({"lat": "x", "precisao_m": True})) == (
        [],
        [("lng", INCOMPLETA), ("origem_coords", INCOMPLETA)],
    )


def test_a_localizacao_incompleta_junta_se_aos_outros_erros_pela_ordem_dos_campos():
    dados, erros = alteracao({"telefone": "1", "lng": -9.1364, "nome": "", "dias_fechada": ["x"]})

    assert list(erros.items()) == [
        ("nome", "Indique o nome."),
        ("lat", INCOMPLETA),
        ("origem_coords", INCOMPLETA),
        ("telefone", TELEFONE),
        ("dias_fechada", DIAS),
    ]
    assert list(dados) == ["nome", "telefone", "dias_fechada"]


def test_a_localizacao_completa_vem_pela_ordem_dos_campos_mesmo_com_o_corpo_ao_contrario():
    dados, erros = alteracao({
        "precisao_m": 12.5,
        "origem_coords": "gps",
        "lng": -9.1364,
        "notas": " x ",
        "lat": 38.7075,
        "nome": " Café ",
    })

    assert erros == {}
    assert list(dados.items()) == [
        ("nome", "Café"),
        ("lat", 38.7075),
        ("lng", -9.1364),
        ("origem_coords", "gps"),
        ("precisao_m", 13),
        ("notas", "x"),
    ]
    assert type(dados["precisao_m"]) is int


@pytest.mark.parametrize(
    "localizacao, erros",
    [
        ({"lat": True}, {"lat": "A latitude tem de ser um número."}),
        ({"lng": False}, {"lng": "A longitude tem de ser um número."}),
        ({"lat": "38.7075"}, {"lat": "A latitude tem de ser um número."}),
        ({"lat": 42.1999995}, {}),
        ({"lat": 42.2000005}, {"lat": "Fora de Portugal"}),
        ({"origem_coords": " gps", "precisao_m": 80}, {"origem_coords": ORIGEM_INVALIDA}),
        ({"origem_coords": "", "precisao_m": 80}, {"origem_coords": "Indique a origem das coordenadas."}),
        ({"origem_coords": "gps", "precisao_m": True}, {"precisao_m": GPS}),
        ({"origem_coords": "gps", "precisao_m": 50.5}, {"precisao_m": GPS}),
        ({"origem_coords": "geocoder", "precisao_m": 500}, {}),
    ],
    ids=[
        "latitude verdadeira",
        "longitude falsa",
        "latitude em texto",
        "latitude que arredondada fica no limite",
        "latitude que arredondada passa o limite",
        "origem com espaço (a precisão nem se valida)",
        "origem vazia",
        "precisão verdadeira",
        "precisão de 50,5 m",
        "outra origem ignora a precisão",
    ],
)
def test_a_localizacao_completa_armadilhas_do_python(localizacao, erros):
    assert list(alteracao({**LOCALIZACAO, **localizacao})[1].items()) == list(erros.items())


@pytest.mark.parametrize("texto_json", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_latitude_lida_pelo_json_loads(texto_json):
    parcial = json.loads(f'{{"lat": {texto_json}, "lng": -9.1364, "origem_coords": "pin_manual"}}')

    assert pares(alteracao(parcial))[1] == [("lat", "A latitude tem de ser um número.")]


def test_a_latitude_e_arredondada_meio_para_longe_do_zero():
    dados, erros = alteracao({**LOCALIZACAO, "lat": 42.1999995})

    assert erros == {}
    assert mesmo_valor(dados["lat"], 42.2)


@pytest.mark.parametrize(
    "parcial",
    [
        {"Lat": 38.7075},
        {" lat": 38.7075},
        {"LAT": 38.7075, "Nome": "Outra"},
        {"precisao": 10},
        {"origem": "gps"},
    ],
    ids=["Lat", "lat com espaço", "LAT e Nome", "precisao", "origem"],
)
def test_chaves_parecidas_com_as_da_localizacao_nao_contam(parcial):
    assert pares(alteracao(parcial)) == ([], [])


@pytest.mark.parametrize(
    "horas",
    [
        {"janela1_inicio": "13:00", "janela1_fim": "10:00"},
        {"janela2_inicio": "15:00"},
        {"janela1_inicio": "10:00", "janela1_fim": "13:00", "janela2_inicio": "12:00", "janela2_fim": "19:00"},
    ],
    ids=["fim antes do início", "janela 2 sem a janela 1", "janela 2 antes do fim da janela 1"],
)
def test_nem_as_horas_enviadas_juntas_se_comparam(horas):
    # Mesmo com as horas todas, a alteração não chama janelas.erros: quem
    # compara é a rota, com as horas que a loja já tem (T2.11).
    assert pares(alteracao(horas)) == (list(horas.items()), [])


@pytest.mark.parametrize(
    "hora",
    [1000, True, ["10:00"], "10:00\n", " 10:00", "1٠:00", "24:00"],
    ids=["número", "verdadeiro", "lista", "mudança de linha", "espaço", "algarismo árabe", "24:00"],
)
def test_uma_hora_ma_da_o_erro_do_formato_e_nunca_type_error(hora):
    assert pares(alteracao({"janela1_inicio": hora})) == (
        [("janela1_inicio", None)],
        [("janela1_inicio", FORMATO_HORA)],
    )


def test_o_nome_que_nao_e_texto_fica_vazio_nos_dados_como_no_php():
    assert pares(alteracao({"nome": 5})) == ([("nome", "")], [("nome", "Indique o nome.")])


@pytest.mark.parametrize(
    "regiao_id, guardado, erros",
    [
        (REGIAO_ID, REGIAO_ID, []),
        ("", None, [("regiao_id", REGIAO)]),
        (1, None, [("regiao_id", REGIAO)]),
        ({"$ne": None}, None, [("regiao_id", REGIAO)]),
        (REGIAO_ID.upper(), None, [("regiao_id", REGIAO)]),
    ],
    ids=["uuid4", "vazia", "inteiro do autónomo", "operador do Mongo", "maiúsculas"],
)
def test_regiao_e_um_uuid4_em_texto(regiao_id, guardado, erros):
    assert pares(alteracao({"regiao_id": regiao_id})) == ([("regiao_id", guardado)], erros)


def test_fase_vazia_diz_que_falta():
    assert pares(alteracao({"fase": ""})) == ([("fase", None)], [("fase", "Indique a fase.")])


def test_com_todos_os_campos_os_dados_sao_os_da_criacao():
    corpo = {
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
        "notas": " Descarga pela porta lateral. ",
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
        "janela2_inicio": "15:00",
        "janela2_fim": "19:00",
        "dias_fechada": ["dom", "sab"],
    }

    dados, erros = alteracao(corpo)

    assert erros == {}
    assert tuple(dados) == CAMPOS
    assert pares((dados, erros)) == pares(criacao(corpo))


def test_com_todos_os_campos_os_erros_sao_os_da_criacao_sem_comparar_as_janelas():
    corpo = {**dict.fromkeys(CAMPOS), "telefone": "1", "janela1_inicio": "13:00", "janela1_fim": "10:00"}

    dados, erros = alteracao(corpo)
    dados_criacao, erros_criacao = criacao(corpo)

    assert list(dados.items()) == list(dados_criacao.items())
    assert list(erros_criacao.items()) == [*erros.items(), ("janela1_fim", "O fim tem de ser depois do início.")]


def test_nao_mexe_no_corpo_recebido():
    corpo = {
        "nome": "  Café  ",
        "lat": 38.72240049,
        "lng": -9.1364,
        "origem_coords": "gps",
        "precisao_m": 12.4,
        "telefone": " +351  912 345   678 ",
        "dias_fechada": ["dom", "sab"],
        "atualizado_em": "2026-10-03T09:00:00.123456Z",
    }
    original = copy.deepcopy(corpo)

    alteracao(corpo)
    alteracao({"lng": -9.1364, "nome": "x", "dias_fechada": corpo["dias_fechada"]})

    assert corpo == original
    assert list(corpo) == list(original)


def test_devolve_estruturas_novas_em_cada_chamada():
    dias = ["seg"]
    primeiro, erros_primeiro = alteracao({"dias_fechada": dias})
    segundo, erros_segundo = alteracao({"dias_fechada": dias})

    assert primeiro["dias_fechada"] is not dias
    assert primeiro["dias_fechada"] is not segundo["dias_fechada"]
    assert primeiro is not segundo and erros_primeiro is not erros_segundo
    primeiro["dias_fechada"].append("ter")
    assert alteracao({"dias_fechada": dias})[0]["dias_fechada"] == ["seg"]


# --- Janelas: as quatro horas planas da API ↔ a lista da base ---


def planas(inicio1=None, fim1=None, inicio2=None, fim2=None):
    return {"janela1_inicio": inicio1, "janela1_fim": fim1, "janela2_inicio": inicio2, "janela2_fim": fim2}


def test_uma_janela_fica_uma_lista_com_uma_janela():
    assert janelas_para_lista(planas("10:00", "13:00")) == [{"inicio": "10:00", "fim": "13:00"}]


def test_duas_janelas_ficam_pela_ordem():
    lista = janelas_para_lista(planas("10:00", "13:00", "15:00", "19:00"))

    assert lista == [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}]
    assert all(list(janela) == ["inicio", "fim"] for janela in lista)


def test_sem_janelas_fica_uma_lista_vazia():
    assert janelas_para_lista(planas()) == []
    # As chaves que faltam contam como None (como no janelas.erros).
    assert janelas_para_lista({}) == []


def test_le_so_as_quatro_horas_dos_dados_validados_da_loja():
    dados, erros = criacao({
        "nome": "Café",
        "fase": "potencial",
        **LOCALIZACAO,
        "janela1_inicio": "08:30",
        "janela1_fim": "12:00",
    })

    assert erros == {}
    assert janelas_para_lista(dados) == [{"inicio": "08:30", "fim": "12:00"}]


def test_sem_janelas_na_base_as_quatro_horas_ficam_nulas():
    assert list(campos_de_janelas([]).items()) == [
        ("janela1_inicio", None),
        ("janela1_fim", None),
        ("janela2_inicio", None),
        ("janela2_fim", None),
    ]


def test_uma_janela_na_base_e_a_janela_1():
    assert list(campos_de_janelas([{"inicio": "10:00", "fim": "13:00"}]).items()) == list(
        planas("10:00", "13:00").items()
    )


def test_duas_janelas_na_base_sao_as_janelas_1_e_2():
    # A ordem das chaves de cada janela na base não importa.
    lista = [{"fim": "13:00", "inicio": "10:00"}, {"inicio": "15:00", "fim": "19:00"}]

    assert list(campos_de_janelas(lista).items()) == list(planas("10:00", "13:00", "15:00", "19:00").items())


HORAS_IDA_E_VOLTA = [None, "00:00", "09:59", "10:00", "13:00", "13:01", "23:59"]


def combinacoes_coerentes():
    for horas in itertools.product(HORAS_IDA_E_VOLTA, repeat=4):
        campos = planas(*horas)
        if janelas.erros(campos) == {}:
            yield campos


def test_ida_e_volta_sem_perda():
    coerentes = list(combinacoes_coerentes())
    # Sem janelas, só a janela 1 e as duas: 1 + 15 + 15 × (pares depois do fim) > 30 casos.
    assert len(coerentes) > 30
    assert any(len(janelas_para_lista(c)) == 2 for c in coerentes)

    for campos in coerentes:
        lista = janelas_para_lista(campos)
        de_volta = campos_de_janelas(lista)
        assert list(de_volta.items()) == list(campos.items())
        assert janelas_para_lista(de_volta) == lista
        assert campos_de_janelas(copy.deepcopy(lista)) == de_volta


def test_as_conversoes_nao_mexem_no_que_recebem_e_devolvem_estruturas_novas():
    campos = planas("10:00", "13:00", "15:00", "19:00")
    original_campos = copy.deepcopy(campos)
    lista = janelas_para_lista(campos)
    original_lista = copy.deepcopy(lista)

    de_volta = campos_de_janelas(lista)

    assert campos == original_campos and lista == original_lista
    assert de_volta is not campos
    outra = janelas_para_lista(campos)
    assert outra is not lista and outra[0] is not lista[0]
    assert campos_de_janelas(lista) is not de_volta


@pytest.mark.parametrize(
    "campos",
    [
        planas("10:00"),
        planas(None, "13:00"),
        planas("13:00", "10:00"),
        planas("10:00", "10:00"),
        planas(None, None, "15:00", "19:00"),
        planas("10:00", "13:00", "15:00"),
        planas("10:00", "13:00", "12:00", "19:00"),
        planas("10:00", "13:00", "13:00", "19:00"),
        planas("25:00", "26:00"),
        planas(" 10:00", "13:00"),
        planas("10:00\n", "13:00"),
        planas("", ""),
        planas("", "13:00"),
        planas(1000, 1300),
        planas(True, "13:00"),
        planas(["10:00"], "13:00"),
    ],
    ids=[
        "só o início",
        "só o fim",
        "fim antes do início",
        "fim igual ao início",
        "janela 2 sem a janela 1",
        "janela 2 só com o início",
        "janela 2 antes do fim da janela 1",
        "janela 2 a começar no fim da janela 1",
        "horas fora do formato",
        "hora com espaço",
        "hora com mudança de linha",
        "horas vazias (não validadas)",
        "início vazio (não validado)",
        "horas em número",
        "hora verdadeira",
        "hora numa lista",
    ],
)
def test_para_lista_recusa_horas_por_validar_ou_incoerentes(campos):
    with pytest.raises(ValueError):
        janelas_para_lista(campos)


@pytest.mark.parametrize(
    "lista",
    [
        None,
        {},
        ({"inicio": "10:00", "fim": "13:00"},),
        "10:00-13:00",
        [{"inicio": "08:00", "fim": "09:00"}, {"inicio": "10:00", "fim": "11:00"}, {"inicio": "12:00", "fim": "13:00"}],
        [None],
        [["10:00", "13:00"]],
        [{"inicio": "10:00"}],
        [{"inicio": "10:00", "fim": "13:00", "dia": "seg"}],
        [{"inicio": None, "fim": None}],
        [{"inicio": "10:00", "fim": None}],
        [{"inicio": "13:00", "fim": "10:00"}],
        [{"inicio": "15:00", "fim": "19:00"}, {"inicio": "10:00", "fim": "13:00"}],
        [{"inicio": "10:00", "fim": "13:00"}, {"inicio": None, "fim": None}],
        [{"inicio": None, "fim": None}, {"inicio": "10:00", "fim": "13:00"}],
        [{"inicio": "1000", "fim": "1300"}],
        [{"inicio": 1000, "fim": 1300}],
    ],
    ids=[
        "nula",
        "objeto",
        "tuplo",
        "texto",
        "três janelas",
        "janela nula",
        "janela numa lista",
        "janela sem o fim",
        "janela com uma chave a mais",
        "janela vazia",
        "janela só com o início",
        "fim antes do início",
        "fora de ordem",
        "segunda janela vazia",
        "primeira janela vazia",
        "horas sem os dois pontos",
        "horas em número",
    ],
)
def test_de_lista_recusa_o_que_a_base_nunca_tem(lista):
    with pytest.raises(ValueError):
        campos_de_janelas(lista)
