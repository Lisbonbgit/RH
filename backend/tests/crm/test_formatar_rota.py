"""A rota e a paragem entre a base (`crm_rotas`) e a API: `crm/formatar_rota.py` (F3, T3.16).

Plano F3 §3 (o documento) e §4 ("Rota (API)"), no molde do `test_formatar.py`
da F2: as formas esperadas escrevem-se aqui à mão, chave a chave e pela ordem,
e não se calculam com o código que se está a testar. A única exceção é a
assinatura do cálculo (`calculo.atual`): compara-se com a do domínio
(`horarios.entrada_calculo` + `assinatura`, provadas na T3.8), porque é isso
mesmo que o `rota_api` tem de fazer — e a parte que importa (quando fica
velha) prova-se mudando a loja de sítio, uma janela, a fábrica e a ordem.

Correções aplicadas: "T3.3 / T3.16" (uma paragem reposta pelo terreno, com
`ordem None`, lê-se com um `numero` coerente) e "T3.16 / T3.21 / T3.32" (as
horas só valem com `calculo.atual`: o aviso `fora_de_horario` apaga-se sem
ele).
"""
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest
from bson import ObjectId

from crm import formatar_rota
from crm.dominio import rotas
from crm.dominio.horarios import assinatura, entrada_calculo
from crm.formatar_rota import (
    PROJECAO_LOJA_ROTA,
    documento_paragem,
    documento_rota,
    resumo_rota_api,
    rota_api,
)

from .formatos import escritas_no_terreno, instantes_fora_do_formato

UTC = timezone.utc
AGORA = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-10T09:30:15Z"
AGORA_CARIMBO = "2026-10-10T09:30:15.987654Z"

HOJE = date(2026, 10, 12)  # uma segunda-feira
ONTEM = date(2026, 10, 11)
AMANHA = date(2026, 10, 13)  # uma terça-feira
TEXTO_AMANHA = "2026-10-13"

MEMBRO = "membro-1"
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
FABRICA = (38.7223, -9.1393)

# As definições em vigor (`definicoes.combinar`): as coordenadas e os minutos como números.
DEFINICOES = {
    "fabrica_morada": "Rua da Fábrica 1",
    "fabrica_lat": FABRICA[0],
    "fabrica_lng": FABRICA[1],
    "rota_hora_saida": "08:00",
    "rota_hora_regresso": "19:00",
    "servico_entrega_min": 10,
    "servico_amostra_min": 10,
    "servico_acompanhamento_min": 15,
    "servico_angariacao_min": 15,
}

# O documento de crm_rotas, pela ordem do plano F3 §3.
CHAVES_ROTA = (
    "id", "data", "estado", "versao", "hora_saida", "hora_regresso_limite", "inicio", "fim", "evitar_portagens",
    "paragens", "calculo", "criado_em", "criado_por", "atualizado_em", "atualizado_por",
)

# Uma paragem embutida, pela ordem do plano F3 §3.
CHAVES_PARAGEM = (
    "id", "loja_id", "ordem", "motivo", "tempo_servico_min", "manter_fechada", "nao_cabe", "chegada_prevista",
    "espera_min", "fora_de_horario", "adicionada_em", "adicionada_por", "removida_em", "estado", "resultado",
    "concluida_em",
)

# A rota da API, pela ordem do plano F3 §4.
CHAVES_ROTA_API = (
    "id", "data", "existe", "estado", "estado_efetivo", "editavel", "versao", "hoje",
    "hora_saida", "hora_regresso_limite", "evitar_portagens", "inicio", "fim",
    "limite_paragens", "calculo_disponivel", "calculo", "paragens", "blocos_google",
)
CHAVES_PARAGEM_API = (
    "id", "loja_id", "numero", "seccao", "ordem", "motivo", "tempo_servico_min", "manter_fechada", "nao_cabe",
    "chegada_prevista", "espera_min", "fora_de_horario", "aviso", "estado", "resultado", "links", "loja",
)
CHAVES_LOJA_API = (
    "nome", "fase", "lat", "lng", "telefone", "janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim",
    "dias_fechada",
)
CHAVES_CALCULO_API = (
    "atual", "distancia_m", "duracao_s", "regresso_previsto", "depois_do_limite", "geometria", "calculado_em",
)

GOOGLE = "https://www.google.com/maps/dir/?api=1"
WAZE = "https://waze.com/ul?"


# --- montagem ------------------------------------------------------------------------------------


def _loja(id_, nome, fase, ponto, janelas=(), dias_fechada=(), telefone="+351911111111", **extra):
    """Uma loja como a projeção `PROJECAO_LOJA_ROTA` a devolve."""
    return {
        "id": id_, "nome": nome, "fase": fase, "lat": ponto[0], "lng": ponto[1], "telefone": telefone,
        "janelas": [dict(j) for j in janelas], "dias_fechada": list(dias_fechada), **extra,
    }


JANELAS_A = ({"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"})


def _lojas():
    # A fecha à terça (o dia de AMANHA); a B e a C abrem todos os dias.
    return [
        _loja(LOJA_A, "Café A", "contactada", COMERCIO, JANELAS_A, ("ter",)),
        _loja(LOJA_B, "Pastelaria B", "potencial", MARQUES),
        _loja(LOJA_C, "Mercearia C", "cliente", BELEM, ({"inicio": "09:00", "fim": "12:00"},)),
    ]


def _paragem(nome, loja_id, ordem, **campos):
    return {
        "id": f"p-{nome}", "loja_id": loja_id, "ordem": ordem, "motivo": "angariacao", "tempo_servico_min": 15,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-10T09:00:00Z", "adicionada_por": MEMBRO,
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None, **campos,
    }


def _retirada(nome, loja_id, **campos):
    return _paragem(nome, loja_id, None, removida_em="2026-10-10T10:00:00Z", **campos)


def _rota(paragens=(), **campos):
    return {
        "id": "r-1", "data": TEXTO_AMANHA, "estado": "rascunho", "versao": 3, "hora_saida": "08:00",
        "hora_regresso_limite": "19:00", "inicio": None, "fim": None, "evitar_portagens": False,
        "paragens": list(paragens), "calculo": None, "criado_em": "2026-10-10T09:00:00Z", "criado_por": MEMBRO,
        "atualizado_em": "2026-10-10T09:00:00.000000Z", "atualizado_por": MEMBRO, **campos,
    }


def _calculo(assinatura_="sha256:" + "0" * 64, **campos):
    return {
        "assinatura": assinatura_, "distancia_m": 12345, "duracao_s": 2345, "regresso_previsto": "12:30",
        "depois_do_limite": False, "geometria": "_p~iF~ps|U_ulLnnqC_mqNvxq`@", "calculado_em": "2026-10-10T09:05:00Z",
        **campos,
    }


_OMITIDO = object()


def _api(rota, lojas=_OMITIDO, data=AMANHA, hoje=HOJE, definicoes=None, calculo_disponivel=True):
    return rota_api(
        rota,
        data=data,
        hoje=hoje,
        lojas=_lojas() if lojas is _OMITIDO else lojas,
        definicoes=DEFINICOES if definicoes is None else definicoes,
        calculo_disponivel=calculo_disponivel,
    )


def _assinatura(rota, pares, inicio=FABRICA, fim=FABRICA):
    """A assinatura que o cálculo gravou: a entrada do domínio (T3.8) só com as
    paragens da secção "rota", pela ordem, e os pontos já resolvidos."""
    return assinatura(entrada_calculo(rota, pares, inicio, fim))


def _tres_paragens():
    # Pela ordem: B (0), C (1) e A (2, fechada à terça).
    return [_paragem("a", LOJA_A, 2), _paragem("b", LOJA_B, 0), _paragem("c", LOJA_C, 1)]


def _com_calculo_atual(paragens=None, **campos):
    """Uma rota com um cálculo cuja assinatura é a de agora (B e C na secção "rota")."""
    paragens = _tres_paragens() if paragens is None else paragens
    rota = _rota(paragens, **campos)
    por_id = {loja["id"]: loja for loja in _lojas()}
    pares = [(p, por_id[p["loja_id"]]) for p in rotas.ativas(paragens) if p["loja_id"] != LOJA_A]
    rota["calculo"] = _calculo(_assinatura(rota, pares))
    return rota


def _por_id(resposta):
    return {p["id"]: p for p in resposta["paragens"]}


# --- documento_rota ------------------------------------------------------------------------------


def test_o_documento_da_rota_tem_as_chaves_do_modelo_pela_ordem():
    doc = documento_rota(AMANHA, MEMBRO, AGORA, DEFINICOES)
    assert tuple(doc) == CHAVES_ROTA


def test_o_documento_da_rota_nova():
    doc = documento_rota(AMANHA, MEMBRO, AGORA, DEFINICOES)
    assert UUID4.fullmatch(doc["id"])
    assert {chave: valor for chave, valor in doc.items() if chave != "id"} == {
        "data": "2026-10-13",
        "estado": "rascunho",
        "versao": 1,
        "hora_saida": "08:00",
        "hora_regresso_limite": "19:00",
        "inicio": None,
        "fim": None,
        "evitar_portagens": False,
        "paragens": [],
        "calculo": None,
        "criado_em": AGORA_INSTANTE,
        "criado_por": MEMBRO,
        "atualizado_em": AGORA_CARIMBO,
        "atualizado_por": MEMBRO,
    }


def test_a_versao_da_rota_nova_e_o_inteiro_1():
    doc = documento_rota(AMANHA, MEMBRO, AGORA, DEFINICOES)
    assert type(doc["versao"]) is int and doc["versao"] == 1
    assert type(doc["evitar_portagens"]) is bool


def test_as_horas_da_rota_nova_sao_as_das_definicoes_em_vigor():
    definicoes = {**DEFINICOES, "rota_hora_saida": "07:30", "rota_hora_regresso": "18:00"}
    doc = documento_rota(AMANHA, MEMBRO, AGORA, definicoes)
    assert (doc["hora_saida"], doc["hora_regresso_limite"]) == ("07:30", "18:00")


def test_a_data_da_rota_nova_tem_sempre_a_largura_toda():
    assert documento_rota(date(2026, 1, 5), MEMBRO, AGORA, DEFINICOES)["data"] == "2026-01-05"


def test_os_instantes_da_rota_nova_estao_no_formato_da_api():
    doc = documento_rota(AMANHA, MEMBRO, AGORA, DEFINICOES)
    assert instantes_fora_do_formato(doc) == []
    assert escritas_no_terreno(doc) == []


def test_o_instante_de_criacao_corta_os_microssegundos_e_o_carimbo_leva_os_seis():
    doc = documento_rota(AMANHA, MEMBRO, AGORA + timedelta(microseconds=12), DEFINICOES)
    assert doc["criado_em"] == "2026-10-10T09:30:15Z"
    assert doc["atualizado_em"] == "2026-10-10T09:30:15.987666Z"


def test_cada_rota_nova_tem_um_id_e_uma_lista_de_paragens_proprios():
    um = documento_rota(AMANHA, MEMBRO, AGORA, DEFINICOES)
    outro = documento_rota(AMANHA, MEMBRO, AGORA, DEFINICOES)
    assert um["id"] != outro["id"]
    assert um["paragens"] is not outro["paragens"]


def test_a_rota_nova_nao_leva_id_do_mongo():
    assert "_id" not in documento_rota(AMANHA, MEMBRO, AGORA, DEFINICOES)


@pytest.mark.parametrize("data", ["2026-10-13", datetime(2026, 10, 13, tzinfo=UTC), None, 20261013])
def test_o_dia_da_rota_nova_tem_de_ser_um_date(data):
    with pytest.raises(TypeError):
        documento_rota(data, MEMBRO, AGORA, DEFINICOES)


def test_um_agora_sem_fuso_e_recusado():
    with pytest.raises(ValueError):
        documento_rota(AMANHA, MEMBRO, AGORA.replace(tzinfo=None), DEFINICOES)


def test_a_rota_nova_nao_mexe_nas_definicoes():
    definicoes = deepcopy(DEFINICOES)
    documento_rota(AMANHA, MEMBRO, AGORA, definicoes)
    assert definicoes == DEFINICOES


# --- documento_paragem ---------------------------------------------------------------------------


def test_a_paragem_nova_tem_as_chaves_do_modelo_pela_ordem():
    paragem = documento_paragem(_lojas()[0], "amostra", 10, 0, MEMBRO, AGORA)
    assert tuple(paragem) == CHAVES_PARAGEM


def test_a_paragem_nova():
    paragem = documento_paragem(_lojas()[0], "amostra", 10, 2, MEMBRO, AGORA)
    assert UUID4.fullmatch(paragem["id"])
    assert {chave: valor for chave, valor in paragem.items() if chave != "id"} == {
        "loja_id": LOJA_A,
        "ordem": 2,
        "motivo": "amostra",
        "tempo_servico_min": 10,
        "manter_fechada": False,
        "nao_cabe": False,
        "chegada_prevista": None,
        "espera_min": None,
        "fora_de_horario": False,
        "adicionada_em": AGORA_INSTANTE,
        "adicionada_por": MEMBRO,
        "removida_em": None,
        "estado": "pendente",
        "resultado": None,
        "concluida_em": None,
    }


def test_a_paragem_nova_passa_no_varrimento_do_terreno_e_dos_instantes():
    paragem = documento_paragem(_lojas()[1], "entrega", 10, 0, MEMBRO, AGORA)
    assert escritas_no_terreno({"$push": {"paragens": paragem}}) == []
    assert instantes_fora_do_formato(paragem) == []


def test_a_paragem_nova_le_so_o_id_da_loja():
    paragem = documento_paragem({"id": LOJA_B}, "angariacao", 15, 0, MEMBRO, AGORA)
    assert paragem["loja_id"] == LOJA_B


@pytest.mark.parametrize("motivo", rotas.MOTIVOS)
def test_a_paragem_nova_aceita_os_quatro_motivos(motivo):
    assert documento_paragem({"id": LOJA_B}, motivo, 1, 0, MEMBRO, AGORA)["motivo"] == motivo


@pytest.mark.parametrize("motivo", ["visita", "Entrega", "", None, 1])
def test_um_motivo_desconhecido_e_erro_de_programacao(motivo):
    with pytest.raises(ValueError):
        documento_paragem({"id": LOJA_B}, motivo, 10, 0, MEMBRO, AGORA)


@pytest.mark.parametrize("servico", [0, 241, -1, 10.0, True, "10", None])
def test_um_tempo_de_servico_fora_de_1_a_240_e_erro_de_programacao(servico):
    with pytest.raises(ValueError):
        documento_paragem({"id": LOJA_B}, "amostra", servico, 0, MEMBRO, AGORA)


@pytest.mark.parametrize("servico", [1, 240])
def test_os_limites_do_tempo_de_servico_entram(servico):
    assert documento_paragem({"id": LOJA_B}, "amostra", servico, 0, MEMBRO, AGORA)["tempo_servico_min"] == servico


@pytest.mark.parametrize("ordem", [-1, 1.0, True, None, "0"])
def test_uma_ordem_que_nao_e_um_inteiro_a_partir_de_0_e_erro_de_programacao(ordem):
    with pytest.raises(ValueError):
        documento_paragem({"id": LOJA_B}, "amostra", 10, ordem, MEMBRO, AGORA)


@pytest.mark.parametrize("loja", [{"id": None}, {"id": 7}, {"id": ""}, {}])
def test_uma_loja_sem_id_de_texto_e_erro_de_programacao(loja):
    with pytest.raises((ValueError, KeyError)):
        documento_paragem(loja, "amostra", 10, 0, MEMBRO, AGORA)


def test_cada_paragem_nova_tem_o_seu_id():
    um = documento_paragem({"id": LOJA_B}, "amostra", 10, 0, MEMBRO, AGORA)
    outro = documento_paragem({"id": LOJA_B}, "amostra", 10, 0, MEMBRO, AGORA)
    assert um["id"] != outro["id"]
    assert "_id" not in um


def test_a_paragem_nova_nao_mexe_na_loja():
    loja = _lojas()[0]
    copia = deepcopy(loja)
    documento_paragem(loja, "amostra", 10, 0, MEMBRO, AGORA)
    assert loja == copia


# --- rota_api: a rota virtual --------------------------------------------------------------------


def test_a_rota_virtual_tem_as_chaves_da_api_pela_ordem():
    assert tuple(_api(None)) == CHAVES_ROTA_API


def test_a_rota_virtual_de_um_dia_futuro():
    assert _api(None) == {
        "id": None,
        "data": "2026-10-13",
        "existe": False,
        "estado": None,
        "estado_efetivo": None,
        "editavel": True,
        "versao": None,
        "hoje": "2026-10-12",
        "hora_saida": "08:00",
        "hora_regresso_limite": "19:00",
        "evitar_portagens": False,
        "inicio": {"lat": 38.7223, "lng": -9.1393, "fabrica": True},
        "fim": {"lat": 38.7223, "lng": -9.1393, "fabrica": True},
        "limite_paragens": 48,
        "calculo_disponivel": True,
        "calculo": None,
        "paragens": [],
        "blocos_google": [],
    }


def test_a_rota_virtual_de_hoje_e_editavel():
    resposta = _api(None, data=HOJE)
    assert (resposta["data"], resposta["estado_efetivo"], resposta["editavel"]) == ("2026-10-12", None, True)


def test_a_rota_virtual_de_um_dia_passado_le_se_concluida_e_nao_se_edita():
    resposta = _api(None, data=ONTEM)
    assert (resposta["existe"], resposta["estado"], resposta["estado_efetivo"], resposta["editavel"]) == (
        False, None, "concluida", False,
    )


def test_a_rota_virtual_leva_as_horas_e_a_fabrica_das_definicoes():
    definicoes = {**DEFINICOES, "rota_hora_saida": "07:30", "rota_hora_regresso": "18:00", "fabrica_lat": 39.0, "fabrica_lng": -8.5}
    resposta = _api(None, definicoes=definicoes)
    assert (resposta["hora_saida"], resposta["hora_regresso_limite"]) == ("07:30", "18:00")
    assert resposta["inicio"] == {"lat": 39.0, "lng": -8.5, "fabrica": True}
    assert resposta["fim"] == {"lat": 39.0, "lng": -8.5, "fabrica": True}


def test_o_limite_de_paragens_e_o_do_dominio():
    assert _api(None)["limite_paragens"] == rotas.LIMITE_PARAGENS == 48


@pytest.mark.parametrize("disponivel", [True, False])
def test_o_calculo_disponivel_e_o_que_a_rota_diz(disponivel):
    assert _api(None, calculo_disponivel=disponivel)["calculo_disponivel"] is disponivel


@pytest.mark.parametrize("disponivel", [1, 0, None, "sim"])
def test_o_calculo_disponivel_tem_de_ser_um_bool(disponivel):
    with pytest.raises(TypeError):
        _api(None, calculo_disponivel=disponivel)


def test_o_inicio_e_o_fim_da_rota_virtual_sao_dicionarios_separados():
    resposta = _api(None)
    assert resposta["inicio"] is not resposta["fim"]
    assert resposta["inicio"] == resposta["fim"]


@pytest.mark.parametrize("dia", ["2026-10-13", datetime(2026, 10, 13, tzinfo=UTC), None])
def test_a_data_da_api_tem_de_ser_um_date(dia):
    with pytest.raises(TypeError):
        _api(None, data=dia)


@pytest.mark.parametrize("dia", ["2026-10-12", datetime(2026, 10, 12, tzinfo=UTC), None])
def test_o_hoje_da_api_tem_de_ser_um_date(dia):
    with pytest.raises(TypeError):
        _api(None, hoje=dia)


@pytest.mark.parametrize("lojas", [None, "lojas", {LOJA_A: {}}])
def test_as_lojas_vem_numa_lista(lojas):
    with pytest.raises(TypeError):
        _api(None, lojas=lojas)


def test_a_rota_virtual_aceita_um_tuplo_de_lojas_e_ignora_as_que_nao_estao_na_rota():
    assert _api(None, lojas=tuple(_lojas()))["paragens"] == []


# --- rota_api: uma rota guardada -----------------------------------------------------------------


def test_a_rota_guardada_tem_as_chaves_da_api_pela_ordem():
    resposta = _api(_rota(_tres_paragens()))
    assert tuple(resposta) == CHAVES_ROTA_API
    assert all(tuple(p) == CHAVES_PARAGEM_API for p in resposta["paragens"])
    assert all(tuple(p["loja"]) == CHAVES_LOJA_API for p in resposta["paragens"])


def test_a_cabeca_da_rota_guardada():
    resposta = _api(_rota(_tres_paragens(), estado="planeada", versao=7, hora_saida="07:00", hora_regresso_limite="18:30", evitar_portagens=True))
    assert {chave: resposta[chave] for chave in CHAVES_ROTA_API[:11]} == {
        "id": "r-1",
        "data": "2026-10-13",
        "existe": True,
        "estado": "planeada",
        "estado_efetivo": "planeada",
        "editavel": True,
        "versao": 7,
        "hoje": "2026-10-12",
        "hora_saida": "07:00",
        "hora_regresso_limite": "18:30",
        "evitar_portagens": True,
    }


def test_uma_rota_de_um_dia_passado_le_se_concluida_e_nao_se_edita():
    resposta = _api(_rota(_tres_paragens(), data="2026-10-11"), data=ONTEM)
    assert (resposta["estado"], resposta["estado_efetivo"], resposta["editavel"]) == ("rascunho", "concluida", False)


def test_uma_rota_de_hoje_e_editavel():
    resposta = _api(_rota(_tres_paragens(), data="2026-10-12"), data=HOJE)
    assert (resposta["estado_efetivo"], resposta["editavel"]) == ("rascunho", True)


@pytest.mark.parametrize("estado", ["em_curso", "concluida"])
def test_uma_rota_fora_dos_estados_editaveis_so_se_ve(estado):
    resposta = _api(_rota(_tres_paragens(), estado=estado))
    assert (resposta["estado"], resposta["estado_efetivo"], resposta["editavel"]) == (estado, estado, False)


def test_a_rota_com_um_registo_do_motorista_numa_paragem_retirada_so_se_ve():
    paragens = [*_tres_paragens(), _retirada("d", LOJA_D, estado="nao_feita")]
    resposta = _api(_rota(paragens))
    assert resposta["editavel"] is False
    assert [p["id"] for p in resposta["paragens"]] == ["p-b", "p-c", "p-a"]


def test_a_data_pedida_tem_de_ser_a_da_rota():
    with pytest.raises(ValueError):
        _api(_rota(), data=HOJE)


def test_o_inicio_e_o_fim_da_rota_sao_a_fabrica_das_definicoes_quando_a_rota_nao_tem_ponto():
    resposta = _api(_rota(_tres_paragens()))
    assert resposta["inicio"] == {"lat": 38.7223, "lng": -9.1393, "fabrica": True}
    assert resposta["fim"] == {"lat": 38.7223, "lng": -9.1393, "fabrica": True}


def test_um_ponto_proprio_da_rota_sai_sem_a_fabrica():
    resposta = _api(_rota(_tres_paragens(), inicio={"lat": 38.71, "lng": -9.14}, fim={"lat": 38.69, "lng": -9.2}))
    assert resposta["inicio"] == {"lat": 38.71, "lng": -9.14, "fabrica": False}
    assert resposta["fim"] == {"lat": 38.69, "lng": -9.2, "fabrica": False}


def test_o_inicio_proprio_e_o_fim_na_fabrica_resolvem_se_cada_um_por_si():
    resposta = _api(_rota(_tres_paragens(), inicio={"lat": 38.71, "lng": -9.14}))
    assert resposta["inicio"] == {"lat": 38.71, "lng": -9.14, "fabrica": False}
    assert resposta["fim"] == {"lat": 38.7223, "lng": -9.1393, "fabrica": True}


def test_a_rota_guardada_nao_leva_o_id_do_mongo_nem_das_lojas():
    rota = _rota(_tres_paragens())
    rota["_id"] = ObjectId()
    lojas = [{**loja, "_id": ObjectId()} for loja in _lojas()]
    resposta = _api(rota, lojas=lojas)
    assert "_id" not in resposta
    assert all("_id" not in p and "_id" not in p["loja"] for p in resposta["paragens"])


def test_a_rota_api_nao_mexe_na_rota_nem_nas_lojas():
    rota = _com_calculo_atual(evitar_portagens=True)
    lojas = _lojas()
    copias = deepcopy((rota, lojas))
    _api(rota, lojas=lojas)
    assert (rota, lojas) == copias


# --- rota_api: as paragens -----------------------------------------------------------------------


def test_so_as_paragens_ativas_por_ordem():
    paragens = [_retirada("x", LOJA_D), *_tres_paragens()]
    resposta = _api(_rota(paragens))
    assert [p["id"] for p in resposta["paragens"]] == ["p-b", "p-c", "p-a"]
    assert [p["ordem"] for p in resposta["paragens"]] == [0, 1, 2]


def test_a_paragem_da_api_completa():
    paragem = _paragem("b", LOJA_B, 0, motivo="entrega", tempo_servico_min=20, chegada_prevista="09:10", espera_min=5)
    resposta = _api(_rota([paragem]))
    assert resposta["paragens"] == [
        {
            "id": "p-b",
            "loja_id": LOJA_B,
            "numero": 1,
            "seccao": "rota",
            "ordem": 0,
            "motivo": "entrega",
            "tempo_servico_min": 20,
            "manter_fechada": False,
            "nao_cabe": False,
            "chegada_prevista": "09:10",
            "espera_min": 5,
            "fora_de_horario": False,
            "aviso": "nenhum",
            "estado": "pendente",
            "resultado": None,
            "links": {
                "google": f"{GOOGLE}&destination=38.725300,-9.150000&travelmode=driving&dir_action=navigate",
                "waze": f"{WAZE}ll=38.725300,-9.150000&navigate=yes",
            },
            "loja": {
                "nome": "Pastelaria B",
                "fase": "potencial",
                "lat": 38.7253,
                "lng": -9.15,
                "telefone": "+351911111111",
                "janela1_inicio": None,
                "janela1_fim": None,
                "janela2_inicio": None,
                "janela2_fim": None,
                "dias_fechada": [],
            },
        }
    ]


def test_os_numeros_e_as_seccoes():
    resposta = _api(_rota(_tres_paragens()))
    assert [(p["id"], p["numero"], p["seccao"], p["aviso"]) for p in resposta["paragens"]] == [
        ("p-b", 1, "rota", "nenhum"),
        ("p-c", 2, "rota", "nenhum"),
        ("p-a", None, "fechada", "fechada_neste_dia"),
    ]


def test_a_loja_fechada_neste_dia_com_manter_entra_na_rota_com_numero():
    paragens = _tres_paragens()
    paragens[0]["manter_fechada"] = True
    resposta = _api(_rota(paragens))
    assert [(p["id"], p["numero"], p["seccao"], p["aviso"]) for p in resposta["paragens"]] == [
        ("p-b", 1, "rota", "nenhum"),
        ("p-c", 2, "rota", "nenhum"),
        ("p-a", 3, "rota", "nenhum"),
    ]


def test_a_loja_fechada_noutro_dia_entra_na_rota():
    resposta = _api(_rota(_tres_paragens(), data="2026-10-12"), data=HOJE)  # segunda: a A está aberta
    assert [(p["id"], p["numero"], p["seccao"]) for p in resposta["paragens"]] == [
        ("p-b", 1, "rota"), ("p-c", 2, "rota"), ("p-a", 3, "rota"),
    ]


def test_a_paragem_que_nao_cabe_fica_sem_numero_e_com_o_aviso():
    paragens = _tres_paragens()
    paragens[1]["nao_cabe"] = True  # a B, a primeira da ordem
    resposta = _api(_rota(paragens))
    assert [(p["id"], p["numero"], p["seccao"], p["aviso"], p["nao_cabe"]) for p in resposta["paragens"]] == [
        ("p-b", None, "nao_cabe", "nao_cabe", True),
        ("p-c", 1, "rota", "nenhum", False),
        ("p-a", None, "fechada", "fechada_neste_dia", False),
    ]


def test_a_loja_fechada_ganha_ao_nao_cabe():
    paragens = _tres_paragens()
    paragens[0]["nao_cabe"] = True  # a A, fechada à terça
    paragem = _por_id(_api(_rota(paragens)))["p-a"]
    assert (paragem["seccao"], paragem["aviso"], paragem["numero"]) == ("fechada", "fechada_neste_dia", None)


def test_uma_loja_apagada_fica_sem_loja_sem_links_e_sem_numero():
    paragens = [*_tres_paragens(), _paragem("d", LOJA_D, 3)]
    resposta = _api(_rota(paragens))
    paragem = _por_id(resposta)["p-d"]
    assert (paragem["numero"], paragem["seccao"], paragem["aviso"], paragem["links"], paragem["loja"]) == (
        None, "sem_loja", "nenhum", None, None,
    )
    assert [p["numero"] for p in resposta["paragens"]] == [1, 2, None, None]


def test_uma_paragem_reposta_pelo_terreno_com_ordem_nula_vai_para_o_fim_com_numero_coerente():
    """Correção "T3.3 / T3.16": a F4 repõe uma retirada só com `removida_em:
    null`, deixando `ordem` a `None` e um registo `feita`. Lê-se sem erro, no
    fim, com o número a seguir, e a rota fica só de leitura."""
    reposta = _paragem("d", LOJA_B, None, estado="feita", resultado="entregue", concluida_em="2026-10-13T10:00:00Z")
    paragens = [reposta, *_tres_paragens()]
    resposta = _api(_rota(paragens, estado="em_curso"))
    assert [(p["id"], p["ordem"], p["numero"], p["seccao"]) for p in resposta["paragens"]] == [
        ("p-b", 0, 1, "rota"),
        ("p-c", 1, 2, "rota"),
        ("p-a", 2, None, "fechada"),
        ("p-d", None, 3, "rota"),
    ]
    assert resposta["editavel"] is False
    assert (resposta["paragens"][-1]["estado"], resposta["paragens"][-1]["resultado"]) == ("feita", "entregue")


def test_duas_paragens_repostas_com_ordem_nula_ficam_pela_posicao_na_lista():
    paragens = [_paragem("a", LOJA_A, 0, manter_fechada=True), _paragem("d", LOJA_B, None), _paragem("e", LOJA_C, None)]
    resposta = _api(_rota(paragens))
    assert [(p["id"], p["numero"]) for p in resposta["paragens"]] == [("p-a", 1), ("p-d", 2), ("p-e", 3)]


def test_a_paragem_da_api_nao_leva_os_instantes_nem_quem_a_adicionou():
    chaves = set(_api(_rota(_tres_paragens()))["paragens"][0])
    assert not chaves & {"adicionada_em", "adicionada_por", "removida_em", "concluida_em"}


@pytest.mark.parametrize("evitar, google, waze", [
    (False, "&travelmode=driving&dir_action=navigate", "&navigate=yes"),
    (True, "&travelmode=driving&dir_action=navigate&avoid=tolls", "&navigate=yes&avoid_tolls=true"),
])
def test_os_links_de_cada_paragem_seguem_as_portagens_da_rota(evitar, google, waze):
    resposta = _api(_rota(_tres_paragens(), evitar_portagens=evitar))
    assert _por_id(resposta)["p-a"]["links"] == {
        "google": f"{GOOGLE}&destination=38.707500,-9.136400{google}",
        "waze": f"{WAZE}ll=38.707500,-9.136400{waze}",
    }


def test_as_paragens_fora_da_seccao_rota_tambem_tem_links():
    paragens = _tres_paragens()
    paragens[1]["nao_cabe"] = True
    por_id = _por_id(_api(_rota(paragens)))
    assert por_id["p-b"]["links"]["waze"] == f"{WAZE}ll=38.725300,-9.150000&navigate=yes"
    assert por_id["p-a"]["links"]["google"].startswith(f"{GOOGLE}&destination=38.707500,-9.136400")


def test_a_loja_da_paragem_com_as_janelas_planas_e_os_dias():
    assert _por_id(_api(_rota(_tres_paragens())))["p-a"]["loja"] == {
        "nome": "Café A",
        "fase": "contactada",
        "lat": 38.7075,
        "lng": -9.1364,
        "telefone": "+351911111111",
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
        "janela2_inicio": "15:00",
        "janela2_fim": "19:00",
        "dias_fechada": ["ter"],
    }


def test_a_loja_da_paragem_com_uma_so_janela():
    loja = _por_id(_api(_rota(_tres_paragens())))["p-c"]["loja"]
    assert (loja["janela1_inicio"], loja["janela1_fim"], loja["janela2_inicio"], loja["janela2_fim"]) == (
        "09:00", "12:00", None, None,
    )


def test_as_coordenadas_da_loja_saem_em_float_e_os_dias_pela_ordem_da_semana_sem_repetidos():
    lojas = [_loja(LOJA_B, "B", "potencial", (39, -9), dias_fechada=("dom", "seg", "dom"))]
    loja = _api(_rota([_paragem("b", LOJA_B, 0)]), lojas=lojas)["paragens"][0]["loja"]
    assert loja["lat"] == 39.0 and type(loja["lat"]) is float
    assert loja["lng"] == -9.0 and type(loja["lng"]) is float
    assert loja["dias_fechada"] == ["seg", "dom"]


def test_a_loja_da_paragem_leva_so_os_campos_da_projecao():
    """Mesmo que o documento traga mais (notas, pessoa de contacto, morada),
    nada disso vai na rota: a projeção é a `PROJECAO_LOJA_ROTA`."""
    lojas = [_loja(LOJA_B, "B", "potencial", MARQUES, notas="segredo", pessoa_contacto="Ana", morada="Rua X", regiao_id="r")]
    loja = _api(_rota([_paragem("b", LOJA_B, 0)]), lojas=lojas)["paragens"][0]["loja"]
    assert tuple(loja) == CHAVES_LOJA_API


def test_o_telefone_da_loja_pode_ser_nulo():
    lojas = [_loja(LOJA_B, "B", "potencial", MARQUES, telefone=None)]
    assert _api(_rota([_paragem("b", LOJA_B, 0)]), lojas=lojas)["paragens"][0]["loja"]["telefone"] is None


@pytest.mark.parametrize("estragada", [
    {"lat": "38.7"}, {"lat": True}, {"lng": float("nan")}, {"lat": 91.0},
    {"janelas": [{"inicio": "10:00"}]}, {"janelas": "10:00-13:00"}, {"dias_fechada": ["segunda"]}, {"dias_fechada": "seg"},
])
def test_uma_loja_estragada_na_base_e_erro_de_programacao(estragada):
    lojas = [{**_loja(LOJA_B, "B", "potencial", MARQUES), **estragada}]
    with pytest.raises(ValueError):
        _api(_rota([_paragem("b", LOJA_B, 0)]), lojas=lojas)


def test_as_lojas_que_nao_estao_na_rota_ignoram_se():
    resposta = _api(_rota([_paragem("b", LOJA_B, 0)]))
    assert [p["id"] for p in resposta["paragens"]] == ["p-b"]


def test_a_mesma_loja_em_duas_paragens_le_se_nas_duas():
    paragens = [_paragem("b", LOJA_B, 0), _paragem("b2", LOJA_B, 1)]
    resposta = _api(_rota(paragens))
    assert [(p["numero"], p["loja"]["nome"]) for p in resposta["paragens"]] == [(1, "Pastelaria B"), (2, "Pastelaria B")]


# --- rota_api: os blocos do Google Maps ----------------------------------------------------------


def test_os_blocos_google_levam_so_a_seccao_rota_pela_ordem():
    paragens = _tres_paragens()
    resposta = _api(_rota(paragens))
    assert resposta["blocos_google"] == [
        {
            "de": 1,
            "ate": 2,
            "quantas": 2,
            "rotulo": "Abrir paragens 1–2 no Google Maps (2 paragens)",
            "href": f"{GOOGLE}&destination=38.697900,-9.206500&waypoints=38.725300,-9.150000&travelmode=driving&dir_action=navigate",
        }
    ]


def test_os_blocos_google_seguem_as_portagens_da_rota():
    resposta = _api(_rota([_paragem("b", LOJA_B, 0)], evitar_portagens=True))
    assert resposta["blocos_google"] == [
        {
            "de": 1,
            "ate": 1,
            "quantas": 1,
            "rotulo": "Abrir paragem 1 no Google Maps (1 paragem)",
            "href": f"{GOOGLE}&destination=38.725300,-9.150000&travelmode=driving&dir_action=navigate&avoid=tolls",
        }
    ]


def test_sem_paragens_na_seccao_rota_nao_ha_blocos():
    paragens = [_paragem("a", LOJA_A, 0), _paragem("d", LOJA_D, 1), _paragem("b", LOJA_B, 2, nao_cabe=True)]
    assert _api(_rota(paragens))["blocos_google"] == []


def test_os_blocos_google_sao_de_nove_paragens():
    paragens = [_paragem(f"b{n}", LOJA_B, n) for n in range(10)]
    blocos = _api(_rota(paragens))["blocos_google"]
    assert [(b["de"], b["ate"], b["quantas"]) for b in blocos] == [(1, 9, 9), (10, 10, 1)]
    assert blocos[0]["href"].count("38.725300,-9.150000") == 9


# --- rota_api: o cálculo ---------------------------------------------------------------------------


def test_sem_calculo_na_base_o_calculo_da_api_e_nulo():
    assert _api(_rota(_tres_paragens()))["calculo"] is None


def test_o_calculo_da_api_pela_ordem_sem_a_assinatura():
    rota = _com_calculo_atual()
    calculo = _api(rota)["calculo"]
    assert tuple(calculo) == CHAVES_CALCULO_API
    assert calculo == {
        "atual": True,
        "distancia_m": 12345,
        "duracao_s": 2345,
        "regresso_previsto": "12:30",
        "depois_do_limite": False,
        "geometria": "_p~iF~ps|U_ulLnnqC_mqNvxq`@",
        "calculado_em": "2026-10-10T09:05:00Z",
    }


def test_o_calculo_e_atual_quando_a_assinatura_e_a_de_agora():
    assert _api(_com_calculo_atual())["calculo"]["atual"] is True


def test_a_assinatura_do_calculo_leva_so_as_paragens_da_seccao_rota():
    """A A (fechada à terça) não entra no cálculo: com as três no cálculo a
    assinatura seria outra."""
    rota = _com_calculo_atual()
    por_id = {loja["id"]: loja for loja in _lojas()}
    todas = [(p, por_id[p["loja_id"]]) for p in rotas.ativas(rota["paragens"])]
    assert rota["calculo"]["assinatura"] != _assinatura(rota, todas)
    assert _api(rota)["calculo"]["atual"] is True


def test_o_calculo_com_outra_assinatura_nao_e_atual():
    rota = _rota(_tres_paragens(), calculo=_calculo("sha256:" + "f" * 64))
    assert _api(rota)["calculo"]["atual"] is False


def test_o_calculo_fica_velho_quando_a_loja_muda_de_sitio():
    rota = _com_calculo_atual()
    lojas = _lojas()
    lojas[1]["lat"] += 0.001
    assert _api(rota, lojas=lojas)["calculo"]["atual"] is False


def test_o_calculo_fica_velho_quando_uma_janela_muda():
    rota = _com_calculo_atual()
    lojas = _lojas()
    lojas[2]["janelas"] = [{"inicio": "09:30", "fim": "12:00"}]
    assert _api(rota, lojas=lojas)["calculo"]["atual"] is False


def test_o_calculo_fica_velho_quando_a_fabrica_muda_e_a_rota_parte_dela():
    rota = _com_calculo_atual()
    definicoes = {**DEFINICOES, "fabrica_lat": 38.75}
    assert _api(rota, definicoes=definicoes)["calculo"]["atual"] is False


def test_o_calculo_nao_fica_velho_quando_a_fabrica_muda_e_a_rota_tem_os_seus_pontos():
    rota = _com_calculo_atual(inicio={"lat": 38.71, "lng": -9.14}, fim={"lat": 38.69, "lng": -9.2})
    por_id = {loja["id"]: loja for loja in _lojas()}
    pares = [(p, por_id[p["loja_id"]]) for p in rotas.ativas(rota["paragens"]) if p["loja_id"] != LOJA_A]
    rota["calculo"] = _calculo(_assinatura(rota, pares, (38.71, -9.14), (38.69, -9.2)))
    assert _api(rota)["calculo"]["atual"] is True
    assert _api(rota, definicoes={**DEFINICOES, "fabrica_lat": 38.75})["calculo"]["atual"] is True


def test_o_calculo_fica_velho_quando_a_ordem_muda():
    rota = _com_calculo_atual()
    por_id = {p["id"]: p for p in rota["paragens"]}
    por_id["p-b"]["ordem"], por_id["p-c"]["ordem"] = 1, 0
    assert _api(rota)["calculo"]["atual"] is False


@pytest.mark.parametrize("campo, valor", [
    ("hora_saida", "08:30"), ("hora_regresso_limite", "18:00"), ("evitar_portagens", True),
])
def test_o_calculo_fica_velho_quando_as_definicoes_do_dia_mudam(campo, valor):
    rota = _com_calculo_atual()
    rota[campo] = valor
    assert _api(rota)["calculo"]["atual"] is False


def test_o_calculo_fica_velho_quando_o_tempo_de_servico_muda():
    rota = _com_calculo_atual()
    rota["paragens"][1]["tempo_servico_min"] = 20
    assert _api(rota)["calculo"]["atual"] is False


def test_o_calculo_fica_velho_quando_entra_uma_paragem_na_rota():
    rota = _com_calculo_atual()
    rota["paragens"].append(_paragem("e", LOJA_C, 3))
    assert _api(rota)["calculo"]["atual"] is False


def test_o_calculo_fica_velho_quando_a_fechada_passa_a_manter():
    rota = _com_calculo_atual()
    rota["paragens"][0]["manter_fechada"] = True
    assert _api(rota)["calculo"]["atual"] is False


def test_o_calculo_fica_velho_quando_uma_paragem_e_retirada():
    rota = _com_calculo_atual()
    rota["paragens"][2]["removida_em"] = "2026-10-11T10:00:00Z"
    rota["paragens"][2]["ordem"] = None
    assert _api(rota)["calculo"]["atual"] is False


def test_o_calculo_nao_fica_velho_com_o_que_nao_entra_na_conta():
    """O nome, o telefone, o motivo com a mesma prioridade, a fase, a versão
    e o estado não mudam a assinatura."""
    rota = _com_calculo_atual()
    rota["versao"] = 9
    rota["estado"] = "planeada"
    rota["paragens"][1]["motivo"] = "amostra"  # era angariacao: as duas têm prioridade 1
    lojas = _lojas()
    lojas[1]["nome"] = "Outro nome"
    lojas[1]["telefone"] = None
    lojas[1]["fase"] = "cliente"
    assert _api(rota, lojas=lojas)["calculo"]["atual"] is True


def test_o_aviso_fora_de_horario_so_com_o_calculo_atual():
    """Correção "T3.16 / T3.21 / T3.32": as horas só valem com `calculo.atual`."""
    rota = _com_calculo_atual()
    rota["paragens"][1]["fora_de_horario"] = True
    assert _por_id(_api(rota))["p-b"]["aviso"] == "fora_de_horario"
    rota["calculo"]["assinatura"] = "sha256:" + "f" * 64
    assert _por_id(_api(rota))["p-b"]["aviso"] == "nenhum"
    rota["calculo"] = None
    assert _por_id(_api(rota))["p-b"]["aviso"] == "nenhum"


def test_as_horas_guardadas_saem_mesmo_com_o_calculo_velho():
    rota = _rota(_tres_paragens(), calculo=_calculo("sha256:" + "f" * 64))
    rota["paragens"][1]["chegada_prevista"] = "09:10"
    rota["paragens"][1]["espera_min"] = 0
    paragem = _por_id(_api(rota))["p-b"]
    assert (paragem["chegada_prevista"], paragem["espera_min"]) == ("09:10", 0)


def test_um_calculo_sem_assinatura_e_erro_de_programacao():
    calculo = _calculo()
    del calculo["assinatura"]
    with pytest.raises(KeyError):
        _api(_rota(_tres_paragens(), calculo=calculo))


def test_uma_rota_com_calculo_e_sem_paragens_na_seccao_rota_nao_rebenta():
    rota = _rota([_paragem("a", LOJA_A, 0)], calculo=_calculo())
    resposta = _api(rota)
    assert resposta["calculo"]["atual"] is False
    assert resposta["blocos_google"] == []


# --- resumo_rota_api -------------------------------------------------------------------------------


def test_o_resumo_da_rota_pela_ordem():
    paragens = [*_tres_paragens(), _retirada("x", LOJA_D)]
    assert resumo_rota_api(_rota(paragens), HOJE) == {
        "id": "r-1",
        "data": "2026-10-13",
        "estado": "rascunho",
        "estado_efetivo": "rascunho",
        "paragens": 3,
    }


def test_o_resumo_conta_as_ativas_mesmo_com_ordem_nula_e_sem_loja():
    paragens = [_paragem("d", LOJA_B, None), _paragem("x", LOJA_D, 0), _retirada("y", LOJA_C)]
    assert resumo_rota_api(_rota(paragens), HOJE)["paragens"] == 2


def test_o_resumo_de_uma_rota_passada_le_se_concluida():
    resumo = resumo_rota_api(_rota(_tres_paragens(), data="2026-10-11", estado="planeada"), HOJE)
    assert (resumo["estado"], resumo["estado_efetivo"]) == ("planeada", "concluida")


def test_o_resumo_de_hoje_tem_o_estado_gravado():
    assert resumo_rota_api(_rota(data="2026-10-12", estado="planeada"), HOJE)["estado_efetivo"] == "planeada"


def test_o_resumo_le_o_documento_sem_o_calculo_nem_o_id_do_mongo():
    """`rotas_entre` projeta `{"_id": 0, "calculo": 0}` (correção "T3.17 / T3.18")."""
    rota = _rota(_tres_paragens())
    del rota["calculo"]
    assert resumo_rota_api(rota, HOJE)["paragens"] == 3
    rota["_id"] = ObjectId()
    assert "_id" not in resumo_rota_api(rota, HOJE)


@pytest.mark.parametrize("data", ["2026-1-5", "", None, "2026-02-30"])
def test_um_resumo_com_a_data_estragada_na_base_e_erro_de_programacao(data):
    with pytest.raises(ValueError):
        resumo_rota_api(_rota(data=data), HOJE)


@pytest.mark.parametrize("hoje", ["2026-10-12", datetime(2026, 10, 12, tzinfo=UTC), None])
def test_o_hoje_do_resumo_tem_de_ser_um_date(hoje):
    with pytest.raises(TypeError):
        resumo_rota_api(_rota(), hoje)


def test_o_resumo_nao_mexe_na_rota():
    rota = _rota(_tres_paragens())
    copia = deepcopy(rota)
    resumo_rota_api(rota, HOJE)
    assert rota == copia


# --- PROJECAO_LOJA_ROTA ---------------------------------------------------------------------------


def test_a_projecao_das_lojas_da_rota():
    assert PROJECAO_LOJA_ROTA == {
        "_id": 0, "id": 1, "nome": 1, "fase": 1, "lat": 1, "lng": 1, "telefone": 1, "janelas": 1, "dias_fechada": 1,
    }


def test_a_rota_api_vive_so_com_os_campos_da_projecao():
    """Uma loja só com o que a projeção devolve chega para tudo: a secção, o
    aviso, os links, a loja da API e a assinatura do cálculo."""
    campos = [campo for campo, incluido in PROJECAO_LOJA_ROTA.items() if incluido]
    lojas = [{campo: loja[campo] for campo in campos} for loja in _lojas()]
    resposta = _api(_com_calculo_atual(), lojas=lojas)
    assert resposta["calculo"]["atual"] is True
    assert [p["numero"] for p in resposta["paragens"]] == [1, 2, None]


def test_o_modulo_nao_le_o_relogio_nem_o_ambiente():
    """Tudo o que muda com o tempo (`hoje`, `agora`) e com o ambiente
    (`calculo_disponivel`) entra por parâmetro: o módulo é puro."""
    import ast
    from pathlib import Path

    arvore = ast.parse(Path(formatar_rota.__file__).read_text(encoding="utf-8"))
    importados = {alias.name for n in ast.walk(arvore) if isinstance(n, (ast.Import, ast.ImportFrom)) for alias in n.names}
    assert "os" not in importados
    atributos = {
        (n.value.id, n.attr) for n in ast.walk(arvore) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }
    assert ("relogio", "agora") not in atributos and ("relogio", "hoje") not in atributos
    assert ("relogio", "instante") in atributos and ("relogio", "carimbo") in atributos
