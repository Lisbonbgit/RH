"""A validação dos pedidos às rotas (crm/dominio/validador_rota.py), F3 / T3.4.

O CRM autónomo não tem código de rotas: as regras e as mensagens vêm do plano
F3 (§1 e §4) e das correções obrigatórias ("T3.4 / T3.20": o `retirar` ganha
à `ordem` no mesmo PATCH). Cada função devolve `(dados, erros)`, com os erros
`{campo: mensagem pt-PT}` do 422 `validacao`:

- `data_do_caminho(texto, hoje)`: o dia do caminho `/rotas/{data}`, no
  formato `AAAA-MM-DD` e até 365 dias depois de hoje (o passado é válido
  aqui; o 409 `rota_fechada` vem depois, na rota);
- `intervalo(de, ate, hoje)`: o `GET /rotas` (por omissão hoje − 14 e
  hoje + 60, no máximo 120 dias);
- `adicao(corpo)`: o `POST /rotas/{data}/paragens` (`loja_id`, `motivo?`,
  `versao?`, onde a falta da versão e a versão `null` querem dizer coisas
  diferentes);
- `alteracao(corpo)`: o `PATCH /rotas/{data}`, com os erros por uma ordem
  fixa e as chaves desconhecidas ignoradas;
- `so_versao(corpo)`: o `recalcular` e o `otimizar`;
- `coerencia_horas(saida, regresso)`: a hora limite de regresso depois da
  saída, sobre os valores já juntos com os guardados (a rota chama-a).

A ordem dos dicionários conta, por isso compara-se `list(….items())`, e o
tipo também (`True` nunca vale 1, `10.0` nunca vale 10).
"""
import ast
import copy
import json
import math
import random
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import crm.dominio.validador_rota as validador_rota
from crm.dominio.rotas import MOTIVOS
from crm.dominio.validador_rota import adicao, alteracao, coerencia_horas, data_do_caminho, intervalo, so_versao

HOJE = date(2026, 10, 12)

# Uuid4 em texto minúsculo (versão 4, variante 8/9/a/b), legíveis nos testes.
A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-9222-222222222222"
C = "33333333-3333-4333-a333-333333333333"
D = "44444444-4444-4444-b444-444444444444"

# As mensagens do plano F3 §4, escritas aqui à mão (e não importadas do
# módulo): uma mensagem trocada no código fica vermelha.
DATA = "Indique o dia no formato AAAA-MM-DD."
HORIZONTE = "Escolha um dia até um ano a partir de hoje."
FIM_ANTES = "O fim do intervalo tem de ser depois do início."
INTERVALO_LONGO = "O intervalo tem no máximo 120 dias."
LOJA = "Escolha uma loja."
MOTIVO = "Escolha um motivo: entrega, amostra, acompanhamento ou angariação."
VERSAO_OBRIGATORIA = "Indique a versão da rota que recebeu."
VERSAO_INVALIDA = "A versão da rota não é válida."
HORA_VAZIA = "Indique a hora."
HORA_FORMATO = "A hora tem de estar no formato HH:MM."
COERENCIA = "A hora limite de regresso tem de ser depois da hora de saída."
SIM_OU_NAO = "Escolha sim ou não."
PONTO = "Escolha a fábrica ou um ponto no mapa."
LATITUDE = "A latitude tem de ser um número."
LONGITUDE = "A longitude tem de ser um número."
PORTUGAL = "Fora de Portugal"
ORDEM = "A ordem tem de ser uma lista de paragens, sem repetidas."
NAO_ESTA = "Esta paragem não está na rota."
PARAGENS = "Indique as alterações de cada paragem."
VAI_SER_RETIRADA = "Esta paragem vai ser retirada."
TEMPO = "O tempo de serviço é um número inteiro de minutos, de 1 a 240."
NAO_CABE = "Só se pode pôr de volta na rota."
RETIRAR = "Indique as paragens a retirar, sem repetidas."
ESTADO = "Só se pode marcar a rota como planeada."

# A ordem dos erros do PATCH (plano T3.4): os `paragens.*` entram no lugar de `paragens`.
ORDEM_DA_ALTERACAO = (
    "versao", "hora_saida", "hora_regresso_limite", "inicio", "fim", "evitar_portagens", "ordem", "paragens",
    "retirar", "estado",
)

# Valores que nunca são um inteiro ≥ 1 do JSON: o bool (em Python `True == 1`),
# o decimal `1.0`, o texto e o inteiro fora dos 64 bits (o PHP e o Mongo não o leem).
VERSOES_INVALIDAS = [0, -1, 1.0, True, False, "1", 2**63, [1], {"$gt": 0}, math.nan, math.inf]


def pares(dicionario):
    return list(dicionario.items())


def mesmo_valor(a, b):
    """Igual e do mesmo tipo (o `assertSame`): `1 == 1.0 == True` em Python."""
    return a == b and type(a) is type(b)


# --- data_do_caminho --------------------------------------------------------


@pytest.mark.parametrize(
    "texto, dia",
    [
        ("2026-10-12", date(2026, 10, 12)),  # hoje
        ("2026-10-13", date(2026, 10, 13)),
        ("2026-10-11", date(2026, 10, 11)),  # ontem: o 409 vem depois, na rota
        ("2020-01-01", date(2020, 1, 1)),  # o passado distante também se lê
        ("2027-10-12", date(2027, 10, 12)),  # hoje + 365: o último dia aceite
    ],
)
def test_data_do_caminho_aceita_o_dia_ate_um_ano(texto, dia):
    resultado, erros = data_do_caminho(texto, HOJE)
    assert resultado == dia and type(resultado) is date
    assert erros == {}


@pytest.mark.parametrize("texto", ["2027-10-13", "2028-01-01", "9999-12-31"])
def test_data_do_caminho_recusa_mais_de_um_ano(texto):
    assert data_do_caminho(texto, HOJE) == (None, {"data": HORIZONTE})


def test_o_horizonte_conta_dias_de_calendario_num_ano_bissexto():
    # 2027-03-01 + 365 dias = 2028-02-29 (2028 é bissexto).
    assert data_do_caminho("2028-02-29", date(2027, 3, 1)) == (date(2028, 2, 29), {})
    assert data_do_caminho("2028-03-01", date(2027, 3, 1)) == (None, {"data": HORIZONTE})


@pytest.mark.parametrize(
    "texto",
    [
        "abc", "", "2026-1-5", "2026-02-29", "2026-13-01", "20261012", " 2026-10-12", "2026-10-12\n",
        "２０２６-10-12", "2026-10-12T00:00:00", "12-10-2026", None, 20261012, True, ["2026-10-12"],
        {"$gt": ""}, date(2026, 10, 12),
    ],
)
def test_data_do_caminho_recusa_o_que_nao_e_um_dia(texto):
    assert data_do_caminho(texto, HOJE) == (None, {"data": DATA})


@pytest.mark.parametrize(
    "hoje", ["2026-10-12", datetime(2026, 10, 12, tzinfo=timezone.utc), None, 20261012]
)
def test_data_do_caminho_so_aceita_um_date_como_hoje(hoje):
    with pytest.raises(TypeError):
        data_do_caminho("2026-10-12", hoje)


def test_data_do_caminho_devolve_erros_novos_em_cada_chamada():
    _, primeiro = data_do_caminho("abc", HOJE)
    primeiro["data"] = "estragado"
    assert data_do_caminho("abc", HOJE) == (None, {"data": DATA})


# --- intervalo --------------------------------------------------------------


def test_intervalo_por_omissao_vai_de_hoje_menos_14_a_hoje_mais_60():
    periodo, erros = intervalo(None, None, HOJE)
    assert periodo == (date(2026, 9, 28), date(2026, 12, 11))
    assert all(type(dia) is date for dia in periodo)
    assert erros == {}


def test_intervalo_com_os_dois_dias():
    assert intervalo("2026-10-01", "2026-10-31", HOJE) == ((date(2026, 10, 1), date(2026, 10, 31)), {})


def test_intervalo_so_com_o_inicio_usa_o_fim_por_omissao():
    assert intervalo("2026-10-01", None, HOJE) == ((date(2026, 10, 1), date(2026, 12, 11)), {})


def test_intervalo_so_com_o_fim_usa_o_inicio_por_omissao():
    assert intervalo(None, "2026-10-20", HOJE) == ((date(2026, 9, 28), date(2026, 10, 20)), {})


def test_intervalo_de_um_so_dia_e_valido():
    assert intervalo("2026-10-12", "2026-10-12", HOJE) == ((HOJE, HOJE), {})


def test_intervalo_com_o_fim_antes_do_inicio():
    assert intervalo("2026-10-12", "2026-10-11", HOJE) == (None, {"ate": FIM_ANTES})


def test_intervalo_ate_120_dias_contando_os_dois_extremos():
    # De 1 de outubro a 28 de janeiro: 31 + 30 + 31 + 28 = 120 dias.
    assert intervalo("2026-10-01", "2027-01-28", HOJE) == ((date(2026, 10, 1), date(2027, 1, 28)), {})


@pytest.mark.parametrize("ate", ["2027-01-29", "2027-01-30", "2027-10-01"])
def test_intervalo_com_mais_de_120_dias(ate):
    # 121 dias (os dois extremos incluídos) ou mais.
    assert intervalo("2026-10-01", ate, HOJE) == (None, {"ate": INTERVALO_LONGO})


def test_o_inicio_antigo_com_o_fim_por_omissao_tambem_conta_os_120_dias():
    assert intervalo("2026-01-01", None, HOJE) == (None, {"ate": INTERVALO_LONGO})


def test_o_inicio_depois_do_fim_por_omissao():
    assert intervalo("2027-01-01", None, HOJE) == (None, {"ate": FIM_ANTES})


def test_o_passado_e_o_futuro_distantes_leem_se():
    assert intervalo("2019-01-01", "2019-02-01", HOJE) == ((date(2019, 1, 1), date(2019, 2, 1)), {})
    assert intervalo("2030-01-01", "2030-02-01", HOJE) == ((date(2030, 1, 1), date(2030, 2, 1)), {})


@pytest.mark.parametrize("texto", ["2026-1-1", "", "abc", "2026-02-29", "2026-10-12\n", 20261012, True, ["2026-10-01"]])
def test_intervalo_com_o_inicio_mal_escrito(texto):
    # "" (o `?de=` vazio) não é "por omissão": só a falta do parâmetro o é.
    assert intervalo(texto, "2026-10-31", HOJE) == (None, {"de": DATA})


@pytest.mark.parametrize("texto", ["2026-1-1", "", "abc", 20261012])
def test_intervalo_com_o_fim_mal_escrito(texto):
    assert intervalo("2026-10-01", texto, HOJE) == (None, {"ate": DATA})


def test_intervalo_com_os_dois_mal_escritos_pela_ordem_de_e_ate():
    periodo, erros = intervalo("x", "y", HOJE)
    assert periodo is None
    assert pares(erros) == [("de", DATA), ("ate", DATA)]


def test_com_o_inicio_mal_escrito_nao_se_comparam_os_dias():
    assert intervalo("x", "2020-01-01", HOJE) == (None, {"de": DATA})


@pytest.mark.parametrize("hoje", ["2026-10-12", datetime(2026, 10, 12, tzinfo=timezone.utc), None])
def test_intervalo_so_aceita_um_date_como_hoje(hoje):
    with pytest.raises(TypeError):
        intervalo(None, None, hoje)


# --- adicao -----------------------------------------------------------------


def test_adicao_so_com_a_loja():
    dados, erros = adicao({"loja_id": A})
    assert pares(dados) == [("loja_id", A), ("motivo", None), ("versao", None), ("com_versao", False)]
    assert erros == {}


@pytest.mark.parametrize("motivo", MOTIVOS)
def test_adicao_com_cada_motivo(motivo):
    assert adicao({"loja_id": A, "motivo": motivo})[0]["motivo"] == motivo


def test_adicao_com_o_motivo_nulo_deixa_a_rota_escolher_pela_fase():
    assert adicao({"loja_id": A, "motivo": None}) == (
        {"loja_id": A, "motivo": None, "versao": None, "com_versao": False},
        {},
    )


@pytest.mark.parametrize("motivo", ["", "Entrega", " entrega", "entrega\n", "visita", "angariação", 1, True, ["entrega"], {"$ne": None}])
def test_adicao_recusa_um_motivo_desconhecido(motivo):
    dados, erros = adicao({"loja_id": A, "motivo": motivo})
    assert erros == {"motivo": MOTIVO}
    assert dados["motivo"] is None


def test_sem_versao_o_cartao_do_mapa_nao_a_conhece():
    dados, _ = adicao({"loja_id": A})
    assert dados["versao"] is None and dados["com_versao"] is False


def test_a_versao_nula_quer_dizer_que_ainda_nao_ha_rota():
    dados, erros = adicao({"loja_id": A, "versao": None})
    assert (dados["versao"], dados["com_versao"], erros) == (None, True, {})


@pytest.mark.parametrize("versao", [1, 2, 37, 2**63 - 1])
def test_a_versao_inteira_positiva(versao):
    dados, erros = adicao({"loja_id": A, "versao": versao})
    assert mesmo_valor(dados["versao"], versao) and dados["com_versao"] is True
    assert erros == {}


@pytest.mark.parametrize("versao", VERSOES_INVALIDAS)
def test_adicao_recusa_uma_versao_que_nao_e_um_inteiro_positivo(versao):
    dados, erros = adicao({"loja_id": A, "versao": versao})
    assert erros == {"versao": VERSAO_INVALIDA}
    assert dados["versao"] is None and dados["com_versao"] is True


@pytest.mark.parametrize(
    "corpo",
    [
        {},
        {"loja_id": None},
        {"loja_id": ""},
        {"loja_id": C.upper()},
        {"loja_id": " " + A},
        {"loja_id": A + "\n"},
        {"loja_id": "abc"},
        {"loja_id": "11111111-1111-1111-8111-111111111111"},  # uuid1
        {"loja_id": 123},
        {"loja_id": True},
        {"loja_id": [A]},
        {"loja_id": {"$ne": None}},
    ],
)
def test_adicao_recusa_uma_loja_que_nao_e_um_uuid4(corpo):
    dados, erros = adicao(corpo)
    assert erros == {"loja_id": LOJA}
    assert dados["loja_id"] is None


def test_adicao_junta_os_erros_pela_ordem_do_corpo():
    _, erros = adicao({"versao": 0, "motivo": "x", "loja_id": "y"})
    assert pares(erros) == [("loja_id", LOJA), ("motivo", MOTIVO), ("versao", VERSAO_INVALIDA)]


def test_adicao_ignora_as_chaves_desconhecidas():
    corpo = {"loja_id": A, "estado": "feita", "ordem": 3, "paragem_id": B, "tempo_servico_min": 0, "data": "x"}
    assert adicao(corpo) == ({"loja_id": A, "motivo": None, "versao": None, "com_versao": False}, {})


def test_adicao_nao_muda_o_corpo():
    corpo = {"loja_id": A, "motivo": "amostra", "versao": 4, "extra": [1, {"a": 2}]}
    antes = copy.deepcopy(corpo)
    adicao(corpo)
    assert corpo == antes


@pytest.mark.parametrize("corpo", [None, [], "x", 1])
def test_adicao_so_aceita_um_dicionario(corpo):
    with pytest.raises(TypeError):
        adicao(corpo)


# --- so_versao --------------------------------------------------------------


def test_so_versao_com_a_versao():
    dados, erros = so_versao({"versao": 3})
    assert pares(dados) == [("versao", 3)] and erros == {}


@pytest.mark.parametrize("corpo", [{}, {"versao": None}, *({"versao": v} for v in VERSOES_INVALIDAS)])
def test_so_versao_exige_um_inteiro_positivo(corpo):
    assert so_versao(corpo) == ({}, {"versao": VERSAO_OBRIGATORIA})


def test_so_versao_ignora_as_outras_chaves():
    assert so_versao({"versao": 2, "ordem": [A], "estado": "x"}) == ({"versao": 2}, {})


@pytest.mark.parametrize("corpo", [None, [], "x"])
def test_so_versao_so_aceita_um_dicionario(corpo):
    with pytest.raises(TypeError):
        so_versao(corpo)


# --- coerencia_horas --------------------------------------------------------


@pytest.mark.parametrize(
    "saida, regresso",
    [("08:00", "08:00"), ("19:00", "08:00"), ("23:59", "00:00"), ("08:01", "08:00")],
)
def test_o_regresso_tem_de_ser_depois_da_saida(saida, regresso):
    assert coerencia_horas(saida, regresso) == {"hora_regresso_limite": COERENCIA}


@pytest.mark.parametrize("saida, regresso", [("08:00", "08:01"), ("08:00", "19:00"), ("00:00", "23:59"), ("09:59", "10:00")])
def test_o_regresso_depois_da_saida_passa(saida, regresso):
    assert coerencia_horas(saida, regresso) == {}


@pytest.mark.parametrize(
    "saida, regresso",
    [("8:00", "09:00"), ("08:00", "9:00"), (None, "09:00"), ("08:00", None), ("", "09:00"), ("08:00", 900), ("24:00", "25:00")],
)
def test_a_coerencia_so_compara_horas_ja_validadas(saida, regresso):
    # Erro de programação: a rota valida cada hora (alteracao) antes de as juntar.
    with pytest.raises(ValueError):
        coerencia_horas(saida, regresso)


def test_a_coerencia_devolve_erros_novos():
    primeiro = coerencia_horas("08:00", "08:00")
    primeiro.clear()
    assert coerencia_horas("08:00", "08:00") == {"hora_regresso_limite": COERENCIA}


# --- alteracao: versão e chaves ---------------------------------------------


def test_um_patch_so_com_a_versao():
    dados, erros = alteracao({"versao": 1})
    assert pares(dados) == [("versao", 1)] and erros == {}


@pytest.mark.parametrize("corpo", [{}, {"versao": None}, *({"versao": v} for v in VERSOES_INVALIDAS)])
def test_a_versao_e_obrigatoria_no_patch(corpo):
    dados, erros = alteracao(corpo)
    assert erros == {"versao": VERSAO_OBRIGATORIA}
    assert "versao" not in dados


def test_sem_versao_os_outros_campos_validam_se_na_mesma():
    dados, erros = alteracao({"hora_saida": "07:30", "estado": "rascunho"})
    assert pares(erros) == [("versao", VERSAO_OBRIGATORIA), ("estado", ESTADO)]
    assert pares(dados) == [("hora_saida", "07:30")]


def test_a_alteracao_ignora_as_chaves_desconhecidas():
    corpo = {
        "versao": 2, "id": B, "data": "2026-10-12", "calculo": {"x": 1}, "paragens_novas": [A], "criado_por": "x",
        "atualizado_em": "agora", "$set": {"estado": "feita"},
    }
    assert alteracao(corpo) == ({"versao": 2}, {})


@pytest.mark.parametrize("corpo", [None, [], "x", 1])
def test_a_alteracao_so_aceita_um_dicionario(corpo):
    with pytest.raises(TypeError):
        alteracao(corpo)


# --- alteracao: horas -------------------------------------------------------


@pytest.mark.parametrize("campo", ["hora_saida", "hora_regresso_limite"])
@pytest.mark.parametrize("hora", ["07:30", "00:00", "23:59"])
def test_as_horas_do_dia(campo, hora):
    assert alteracao({"versao": 1, campo: hora}) == ({"versao": 1, campo: hora}, {})


@pytest.mark.parametrize("campo", ["hora_saida", "hora_regresso_limite"])
@pytest.mark.parametrize("hora", ["", None])
def test_a_hora_vazia(campo, hora):
    assert alteracao({"versao": 1, campo: hora}) == ({"versao": 1}, {campo: HORA_VAZIA})


@pytest.mark.parametrize("campo", ["hora_saida", "hora_regresso_limite"])
@pytest.mark.parametrize("hora", ["7:30", "24:00", " 07:30", "07:30\n", "07:30:00", "٠٧:٣٠", 730, True, ["07:30"]])
def test_a_hora_mal_escrita(campo, hora):
    assert alteracao({"versao": 1, campo: hora}) == ({"versao": 1}, {campo: HORA_FORMATO})


def test_a_alteracao_nao_compara_as_horas_entre_si():
    # A coerência é sobre os valores juntos com os guardados: a rota chama a
    # `coerencia_horas` depois de ler a rota (422 "contra a rota", T3.20).
    corpo = {"versao": 1, "hora_saida": "19:00", "hora_regresso_limite": "08:00"}
    assert alteracao(corpo) == (corpo, {})


# --- alteracao: início e fim ------------------------------------------------


@pytest.mark.parametrize("campo", ["inicio", "fim"])
def test_o_ponto_nulo_e_a_fabrica(campo):
    dados, erros = alteracao({"versao": 1, campo: None})
    assert pares(dados) == [("versao", 1), (campo, None)] and erros == {}


@pytest.mark.parametrize("campo", ["inicio", "fim"])
def test_o_ponto_arredonda_as_6_casas_meio_para_longe_do_zero(campo):
    # O round() do Python daria 38.722344 e -9.1393 (o binário fica abaixo do meio).
    dados, erros = alteracao({"versao": 1, campo: {"lat": 38.7223445, "lng": -9.1393005}})
    assert erros == {}
    assert pares(dados[campo]) == [("lat", 38.722345), ("lng", -9.139301)]


def test_o_ponto_ve_portugal_so_depois_de_arredondar():
    # 42,2000004 e −9,6000004 estão fora da caixa antes de arredondar e no limite depois.
    dados, erros = alteracao({"versao": 1, "inicio": {"lat": 42.2000004, "lng": -9.6000004}})
    assert erros == {}
    assert dados["inicio"] == {"lat": 42.2, "lng": -9.6}


def test_o_ponto_com_inteiros_fica_em_decimais():
    dados, _ = alteracao({"versao": 1, "fim": {"lat": 39, "lng": -8}})
    assert all(type(valor) is float for valor in dados["fim"].values())
    assert dados["fim"] == {"lat": 39.0, "lng": -8.0}


def test_as_chaves_a_mais_no_ponto_ignoram_se():
    corpo = {"versao": 1, "inicio": {"nome": "Casa do João", "lng": -9.1, "lat": 38.7, "fabrica": True}}
    dados, erros = alteracao(corpo)
    assert erros == {}
    assert pares(dados["inicio"]) == [("lat", 38.7), ("lng", -9.1)]


@pytest.mark.parametrize("campo", ["inicio", "fim"])
@pytest.mark.parametrize("ponto", [[38.7, -9.1], "fabrica", "", 0, True, False, 38.7])
def test_o_ponto_tem_de_ser_nulo_ou_um_objeto(campo, ponto):
    assert alteracao({"versao": 1, campo: ponto}) == ({"versao": 1}, {campo: PONTO})


@pytest.mark.parametrize(
    "ponto, erro",
    [
        ({"lat": True, "lng": -9.1}, LATITUDE),
        ({"lat": "38.7", "lng": -9.1}, LATITUDE),
        ({"lat": None, "lng": -9.1}, LATITUDE),
        ({"lng": -9.1}, LATITUDE),
        ({}, LATITUDE),
        ({"lat": math.nan, "lng": -9.1}, LATITUDE),
        ({"lat": math.inf, "lng": -9.1}, LATITUDE),
        ({"lat": 38.7, "lng": False}, LONGITUDE),
        ({"lat": 38.7, "lng": "-9.1"}, LONGITUDE),
        ({"lat": 38.7}, LONGITUDE),
        ({"lat": "x", "lng": "y"}, LATITUDE),  # a latitude primeiro
        ({"lat": 40.4168, "lng": -3.7038}, PORTUGAL),  # Madrid
        ({"lat": 32.65, "lng": -16.91}, PORTUGAL),  # Funchal: a carrinha não serve as ilhas
        ({"lat": -9.1, "lng": 38.7}, PORTUGAL),  # trocados
        ({"lat": 42.2000005, "lng": -9.1}, PORTUGAL),  # arredonda para 42.200001
    ],
)
def test_os_erros_do_ponto(ponto, erro):
    assert alteracao({"versao": 1, "inicio": ponto}) == ({"versao": 1}, {"inicio": erro})


def test_o_inicio_e_o_fim_validam_se_cada_um():
    _, erros = alteracao({"versao": 1, "fim": "x", "inicio": {"lat": 40.4, "lng": -3.7}})
    assert pares(erros) == [("inicio", PORTUGAL), ("fim", PONTO)]


# --- alteracao: evitar portagens e estado -----------------------------------


@pytest.mark.parametrize("valor", [True, False])
def test_evitar_portagens(valor):
    dados, erros = alteracao({"versao": 1, "evitar_portagens": valor})
    assert dados["evitar_portagens"] is valor and erros == {}


@pytest.mark.parametrize("valor", ["true", "false", 1, 0, None, "", [True]])
def test_evitar_portagens_e_sim_ou_nao(valor):
    assert alteracao({"versao": 1, "evitar_portagens": valor}) == ({"versao": 1}, {"evitar_portagens": SIM_OU_NAO})


def test_marcar_a_rota_como_planeada():
    assert alteracao({"versao": 1, "estado": "planeada"}) == ({"versao": 1, "estado": "planeada"}, {})


@pytest.mark.parametrize("estado", ["rascunho", "em_curso", "concluida", "Planeada", " planeada", "", None, True, ["planeada"]])
def test_so_se_pode_marcar_a_rota_como_planeada(estado):
    assert alteracao({"versao": 1, "estado": estado}) == ({"versao": 1}, {"estado": ESTADO})


# --- alteracao: ordem e retirar ---------------------------------------------


@pytest.mark.parametrize("campo, mensagem", [("ordem", ORDEM), ("retirar", RETIRAR)])
def test_uma_lista_de_uuid4_sem_repetidos(campo, mensagem):
    dados, erros = alteracao({"versao": 1, campo: [C, A, B]})
    assert dados[campo] == [C, A, B] and erros == {}


@pytest.mark.parametrize("campo", ["ordem", "retirar"])
def test_a_lista_vazia_e_valida(campo):
    assert alteracao({"versao": 1, campo: []}) == ({"versao": 1, campo: []}, {})


@pytest.mark.parametrize("campo, mensagem", [("ordem", ORDEM), ("retirar", RETIRAR)])
@pytest.mark.parametrize(
    "lista",
    [
        [A, B, A],
        [A, A],
        [C.upper()],
        [A, "abc"],
        [A, 1],
        [A, None],
        [A, True],
        [A + "\n"],
        [[A]],  # não se pode pôr num conjunto: nunca TypeError
        [{"$gt": ""}],
        A,
        {A: 0},
        None,
        "",
        0,
    ],
)
def test_a_lista_de_paragens_mal_feita(campo, mensagem, lista):
    assert alteracao({"versao": 1, campo: lista}) == ({"versao": 1}, {campo: mensagem})


def test_o_retirar_ganha_a_ordem_no_mesmo_patch():
    # Correção "T3.4 / T3.20": os ids de `retirar` saem da `ordem` antes do
    # `nova_ordem` (o browser junta as alterações em fila, `juntarAlteracoes`).
    dados, erros = alteracao({"versao": 1, "ordem": [A, B, C], "retirar": [B]})
    assert erros == {}
    assert dados["ordem"] == [A, C]
    assert dados["retirar"] == [B]


def test_o_retirar_pode_esvaziar_a_ordem():
    dados, erros = alteracao({"versao": 1, "retirar": [A, B], "ordem": [B, A]})
    assert (dados["ordem"], dados["retirar"], erros) == ([], [A, B], {})


def test_com_o_retirar_mal_feito_a_ordem_fica_como_veio():
    dados, erros = alteracao({"versao": 1, "ordem": [A, B], "retirar": [B, B]})
    assert erros == {"retirar": RETIRAR}
    assert dados["ordem"] == [A, B]


# --- alteracao: paragens ----------------------------------------------------


def test_as_alteracoes_de_cada_paragem():
    corpo = {
        "versao": 1,
        "paragens": {
            A: {"motivo": "entrega", "tempo_servico_min": 10, "manter_fechada": True, "nao_cabe": False},
            B: {"manter_fechada": False},
        },
    }
    dados, erros = alteracao(corpo)
    assert erros == {}
    assert list(dados["paragens"]) == [A, B]
    assert pares(dados["paragens"][A]) == [
        ("motivo", "entrega"), ("tempo_servico_min", 10), ("manter_fechada", True), ("nao_cabe", False),
    ]
    assert pares(dados["paragens"][B]) == [("manter_fechada", False)]


def test_os_campos_de_uma_paragem_vem_por_uma_ordem_fixa():
    corpo = {"versao": 1, "paragens": {A: {"nao_cabe": False, "manter_fechada": True, "tempo_servico_min": 5, "motivo": "amostra"}}}
    dados, _ = alteracao(corpo)
    assert list(dados["paragens"][A]) == ["motivo", "tempo_servico_min", "manter_fechada", "nao_cabe"]


def test_uma_paragem_sem_alteracoes_fica_vazia():
    assert alteracao({"versao": 1, "paragens": {A: {}}}) == ({"versao": 1, "paragens": {A: {}}}, {})


def test_as_paragens_vazias():
    assert alteracao({"versao": 1, "paragens": {}}) == ({"versao": 1, "paragens": {}}, {})


def test_os_campos_do_terreno_e_os_desconhecidos_de_uma_paragem_ignoram_se():
    # O escritório nunca escreve o que o motorista regista (desenho §4.3).
    alteracoes = {
        "estado": "feita", "resultado": "interessado", "concluida_em": "x", "ordem": 3, "id": B, "loja_id": B,
        "chegada_prevista": "09:00", "removida_em": None, "motivo": "amostra",
    }
    dados, erros = alteracao({"versao": 1, "paragens": {A: alteracoes}})
    assert erros == {}
    assert dados["paragens"] == {A: {"motivo": "amostra"}}


@pytest.mark.parametrize("motivo", MOTIVOS)
def test_o_motivo_de_uma_paragem(motivo):
    dados, _ = alteracao({"versao": 1, "paragens": {A: {"motivo": motivo}}})
    assert dados["paragens"][A] == {"motivo": motivo}


@pytest.mark.parametrize("motivo", [None, "", "Amostra", "visita", 2, True])
def test_o_motivo_de_uma_paragem_mal_escolhido(motivo):
    _, erros = alteracao({"versao": 1, "paragens": {A: {"motivo": motivo}}})
    assert erros == {f"paragens.{A}.motivo": MOTIVO}


@pytest.mark.parametrize("minutos", [1, 15, 240])
def test_o_tempo_de_servico_de_1_a_240(minutos):
    dados, erros = alteracao({"versao": 1, "paragens": {A: {"tempo_servico_min": minutos}}})
    assert erros == {}
    assert mesmo_valor(dados["paragens"][A]["tempo_servico_min"], minutos)


@pytest.mark.parametrize("minutos", [0, 241, -5, 10.0, 10.5, True, False, "10", None, 2**63, math.inf])
def test_o_tempo_de_servico_fora_das_regras(minutos):
    _, erros = alteracao({"versao": 1, "paragens": {A: {"tempo_servico_min": minutos}}})
    assert erros == {f"paragens.{A}.tempo_servico_min": TEMPO}


@pytest.mark.parametrize("valor", ["true", 1, 0, None, ""])
def test_manter_fechada_e_sim_ou_nao(valor):
    _, erros = alteracao({"versao": 1, "paragens": {A: {"manter_fechada": valor}}})
    assert erros == {f"paragens.{A}.manter_fechada": SIM_OU_NAO}


@pytest.mark.parametrize("valor", [True, None, 0, "false", ""])
def test_nao_cabe_so_se_pode_limpar(valor):
    # "Pôr na rota" limpa o sinal; só o otimizador o liga (plano §1 "Não cabem").
    _, erros = alteracao({"versao": 1, "paragens": {A: {"nao_cabe": valor}}})
    assert erros == {f"paragens.{A}.nao_cabe": NAO_CABE}


def test_os_erros_de_uma_paragem_pela_ordem_dos_campos():
    alteracoes = {"nao_cabe": True, "manter_fechada": "x", "tempo_servico_min": 0, "motivo": "x"}
    _, erros = alteracao({"versao": 1, "paragens": {A: alteracoes}})
    assert list(erros) == [f"paragens.{A}.{campo}" for campo in ("motivo", "tempo_servico_min", "manter_fechada", "nao_cabe")]


@pytest.mark.parametrize("paragens", [[A], "x", None, 1, True])
def test_as_paragens_tem_de_ser_um_objeto(paragens):
    assert alteracao({"versao": 1, "paragens": paragens}) == ({"versao": 1}, {"paragens": PARAGENS})


@pytest.mark.parametrize("chave", ["abc", C.upper(), "$set", "0", "", A + "\n"])
def test_as_paragens_so_por_uuid4(chave):
    # Uma chave que não é um uuid4 recusa as alterações todas (sem a repetir no erro).
    assert alteracao({"versao": 1, "paragens": {B: {}, chave: {"motivo": "amostra"}}}) == (
        {"versao": 1},
        {"paragens": PARAGENS},
    )


@pytest.mark.parametrize("alteracoes", ["amostra", None, [], 1, True])
def test_as_alteracoes_de_uma_paragem_sao_um_objeto(alteracoes):
    dados, erros = alteracao({"versao": 1, "paragens": {A: alteracoes, B: {"motivo": "entrega"}}})
    assert erros == {f"paragens.{A}": PARAGENS}
    assert dados["paragens"] == {B: {"motivo": "entrega"}}


def test_uma_paragem_que_vai_ser_retirada_nao_se_altera():
    dados, erros = alteracao({"versao": 1, "paragens": {A: {"motivo": "x"}, B: {"motivo": "amostra"}}, "retirar": [A]})
    assert erros == {f"paragens.{A}": VAI_SER_RETIRADA}
    assert dados["paragens"] == {B: {"motivo": "amostra"}}
    assert dados["retirar"] == [A]


def test_a_retirada_ve_se_mesmo_com_o_retirar_mal_feito():
    _, erros = alteracao({"versao": 1, "paragens": {A: {}}, "retirar": [A, A, "x"]})
    assert pares(erros) == [(f"paragens.{A}", VAI_SER_RETIRADA), ("retirar", RETIRAR)]


def test_os_erros_das_paragens_pela_ordem_do_corpo():
    corpo = {"versao": 1, "paragens": {C: {"motivo": "x"}, A: {"tempo_servico_min": 0}, B: 3}}
    _, erros = alteracao(corpo)
    assert list(erros) == [f"paragens.{C}.motivo", f"paragens.{A}.tempo_servico_min", f"paragens.{B}"]


# --- alteracao: ordem dos erros e dos dados, estruturas novas --------------


def _corpo_todo_errado():
    return {
        "estado": "rascunho",
        "retirar": "x",
        "paragens": {B: {"motivo": "x", "nao_cabe": True}, A: {"tempo_servico_min": 0}, C: {}},
        "ordem": [A, A],
        "evitar_portagens": "sim",
        "fim": [1, 2],
        "inicio": {"lat": "x", "lng": 1},
        "hora_regresso_limite": "25:00",
        "hora_saida": "",
        "versao": True,
        "desconhecida": "x",
    }


def test_os_erros_do_patch_vem_por_uma_ordem_fixa():
    dados, erros = alteracao(_corpo_todo_errado())
    assert pares(erros) == [
        ("versao", VERSAO_OBRIGATORIA),
        ("hora_saida", HORA_VAZIA),
        ("hora_regresso_limite", HORA_FORMATO),
        ("inicio", LATITUDE),
        ("fim", PONTO),
        ("evitar_portagens", SIM_OU_NAO),
        ("ordem", ORDEM),
        (f"paragens.{B}.motivo", MOTIVO),
        (f"paragens.{B}.nao_cabe", NAO_CABE),
        (f"paragens.{A}.tempo_servico_min", TEMPO),
        ("retirar", RETIRAR),
        ("estado", ESTADO),
    ]


def test_os_erros_seguem_a_ordem_do_plano_seja_qual_for_a_ordem_do_corpo():
    corpo = _corpo_todo_errado()
    corpo["paragens"] = 1
    erros = alteracao(corpo)[1]
    assert tuple(erros) == ORDEM_DA_ALTERACAO
    erros_ao_contrario = alteracao(dict(reversed(list(corpo.items()))))[1]
    assert pares(erros_ao_contrario) == pares(erros)


def _corpo_todo_certo():
    return {
        "estado": "planeada",
        "retirar": [D],
        "paragens": {B: {"motivo": "amostra"}, A: {"tempo_servico_min": 20}},
        "ordem": [C, A, B],
        "evitar_portagens": True,
        "fim": None,
        "inicio": {"lat": 38.7, "lng": -9.1},
        "hora_regresso_limite": "18:00",
        "hora_saida": "07:00",
        "versao": 5,
        "desconhecida": "x",
    }


def test_os_dados_do_patch_vem_pela_mesma_ordem():
    dados, erros = alteracao(_corpo_todo_certo())
    assert erros == {}
    assert pares(dados) == [
        ("versao", 5),
        ("hora_saida", "07:00"),
        ("hora_regresso_limite", "18:00"),
        ("inicio", {"lat": 38.7, "lng": -9.1}),
        ("fim", None),
        ("evitar_portagens", True),
        ("ordem", [C, A, B]),
        ("paragens", {B: {"motivo": "amostra"}, A: {"tempo_servico_min": 20}}),
        ("retirar", [D]),
        ("estado", "planeada"),
    ]
    assert list(dados["paragens"]) == [B, A]


def test_a_alteracao_nao_muda_o_corpo_e_devolve_estruturas_novas():
    corpo = _corpo_todo_certo()
    antes = copy.deepcopy(corpo)
    dados, _ = alteracao(corpo)
    assert corpo == antes
    assert dados["inicio"] is not corpo["inicio"]
    assert dados["ordem"] is not corpo["ordem"]
    assert dados["retirar"] is not corpo["retirar"]
    assert dados["paragens"] is not corpo["paragens"]
    assert all(dados["paragens"][id_] is not corpo["paragens"][id_] for id_ in dados["paragens"])

    outra_vez, _ = alteracao(corpo)
    assert outra_vez == dados
    assert outra_vez is not dados
    assert outra_vez["ordem"] is not dados["ordem"]
    assert outra_vez["paragens"][A] is not dados["paragens"][A]


def test_a_ordem_sem_as_retiradas_e_uma_lista_nova():
    corpo = {"versao": 1, "ordem": [A, B], "retirar": []}
    dados, _ = alteracao(corpo)
    assert dados["ordem"] == [A, B] and dados["ordem"] is not corpo["ordem"]


def test_os_erros_da_alteracao_sao_novos_em_cada_chamada():
    _, primeiro = alteracao({})
    primeiro["versao"] = "estragado"
    assert alteracao({}) == ({}, {"versao": VERSAO_OBRIGATORIA})


def test_um_corpo_lido_do_json_valida_se_igual():
    texto = json.dumps(_corpo_todo_certo())
    assert alteracao(json.loads(texto)) == alteracao(_corpo_todo_certo())


# --- nunca rebenta -----------------------------------------------------------


def _valor_ao_acaso(sorte, fundo=0):
    escolhas = [
        None, True, False, 0, 1, -1, 241, 2**63, 1.5, 38.7, -9.1, "", "x", "08:00", "planeada", "amostra", A, B,
        C.upper(), "2026-10-12",
    ]
    if fundo < 2:
        tipo = sorte.random()
        if tipo < 0.15:
            return [_valor_ao_acaso(sorte, fundo + 1) for _ in range(sorte.randint(0, 3))]
        if tipo < 0.30:
            chaves = ["lat", "lng", "motivo", "tempo_servico_min", "manter_fechada", "nao_cabe", A, B, "x"]
            return {sorte.choice(chaves): _valor_ao_acaso(sorte, fundo + 1) for _ in range(sorte.randint(0, 3))}
    return sorte.choice(escolhas)


def test_corpos_ao_acaso_dao_erros_e_nunca_excecoes():
    sorte = random.Random(20261012)
    chaves = [*ORDEM_DA_ALTERACAO, "loja_id", "motivo", "x"]
    mensagens = {
        VERSAO_OBRIGATORIA, VERSAO_INVALIDA, HORA_VAZIA, HORA_FORMATO, PONTO, LATITUDE, LONGITUDE, PORTUGAL,
        SIM_OU_NAO, ORDEM, PARAGENS, VAI_SER_RETIRADA, MOTIVO, TEMPO, NAO_CABE, RETIRAR, ESTADO, LOJA,
    }
    for _ in range(3000):
        corpo = {sorte.choice(chaves): _valor_ao_acaso(sorte) for _ in range(sorte.randint(0, 6))}
        antes = copy.deepcopy(corpo)
        for funcao in (alteracao, adicao, so_versao):
            dados, erros = funcao(corpo)
            assert isinstance(dados, dict) and isinstance(erros, dict)
            assert set(erros.values()) <= mensagens
        assert corpo == antes


# --- o código ----------------------------------------------------------------


def test_o_validador_nunca_usa_o_round_do_python():
    # O `round()` do Python arredonda para o par (plano §10): só `numeros.arredondar`.
    arvore = ast.parse(Path(validador_rota.__file__).read_text(encoding="utf-8"))
    chamadas = [no.func.id for no in ast.walk(arvore) if isinstance(no, ast.Call) and isinstance(no.func, ast.Name)]
    assert "round" not in chamadas


def test_a_mensagem_da_paragem_que_nao_esta_na_rota_fica_para_a_rota():
    # A T3.20 compara os ids com a rota lida (422 "contra a rota") com esta mensagem.
    assert validador_rota.MENSAGEM_NAO_ESTA_NA_ROTA == NAO_ESTA
