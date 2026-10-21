"""O repositório das rotas, `crm/rotas_bd.py` (F3, T3.17): a leitura e a
escrita de `crm_rotas` com o duplo do Motor (`tests/crm/duplos.py`),
verificando o filtro, a atualização e a projeção EXATOS no registo de cada
chamada.

Plano F3 §1 ("O terreno ganha", "versao", "Adicionar sem versão") e §3. As
formas esperadas escrevem-se aqui à mão, chave a chave, e nunca com o código
que se está a testar. Correções aplicadas: "T3.17 (porque_falhou:
precedência)" — com a rota relida, `nao_existe` → `em_curso` → `conflito` —
e "T3.17 / T3.18 (GET /rotas sem a geometria)" — `rotas_entre` lê com a
projeção de exclusão `{"_id": 0, "calculo": 0}`, que o duplo suporta.
"""
import ast
import logging
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

from crm import rotas_bd
from crm.dominio.rotas import caminhos_paragem
from crm.formatar_rota import PROJECAO_LOJA_ROTA, documento_paragem, documento_rota
from crm.rotas_bd import (
    acrescentar_paragem,
    alterar,
    criar,
    ler,
    lojas_da_rota,
    porque_falhou,
    rotas_com_loja,
    rotas_entre,
)

from .duplos import BaseFalsa, ColeccaoFalsa, correr
from .formatos import escritas_no_terreno, instantes_fora_do_formato

UTC = timezone.utc
AGORA = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-10T09:30:15Z"
AGORA_CARIMBO = "2026-10-10T09:30:15.987654Z"
ANTES_CARIMBO = "2026-10-10T09:00:00.000000Z"

DIA = "2026-10-13"
MEMBRO = "membro-1"
OUTRO = "membro-2"

ROTAS = "crm_rotas"
LOJAS = "crm_lojas"

LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"

DEFINICOES = {
    "fabrica_morada": "Rua da Fábrica 1",
    "fabrica_lat": 38.7223,
    "fabrica_lng": -9.1393,
    "rota_hora_saida": "08:00",
    "rota_hora_regresso": "19:00",
    "servico_entrega_min": 10,
    "servico_amostra_min": 10,
    "servico_acompanhamento_min": 15,
    "servico_angariacao_min": 15,
}

# O filtro de guarda de TODAS as escritas do escritório (plano F3 §1), para a
# rota "r-1" lida com a versão 3 e sem cálculo (correção "F3-INT-1": o
# cálculo lido também entra no filtro).
FILTRO_DE_ESCRITA = {
    "id": "r-1",
    "versao": 3,
    "calculo": None,
    "estado": {"$in": ["rascunho", "planeada"]},
    "paragens.estado": {"$nin": ["feita", "nao_feita"]},
}
SEM_ID = {"_id": 0}
SEM_CALCULO = {"_id": 0, "calculo": 0}


# --- montagem ------------------------------------------------------------------------------------


def _paragem(nome, loja_id, ordem, **campos):
    return {
        "id": f"p-{nome}", "loja_id": loja_id, "ordem": ordem, "motivo": "angariacao", "tempo_servico_min": 15,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-10T09:00:00Z", "adicionada_por": MEMBRO,
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None, **campos,
    }


def _retirada(nome, loja_id, **campos):
    return _paragem(nome, loja_id, None, removida_em="2026-10-10T10:00:00Z", **campos)


def _feita(nome, loja_id, ordem, **campos):
    return _paragem(
        nome, loja_id, ordem, estado="feita", resultado="interessado", concluida_em="2026-10-13T10:00:00Z", **campos
    )


def _rota(paragens=(), **campos):
    return {
        "id": "r-1", "data": DIA, "estado": "rascunho", "versao": 3, "hora_saida": "08:00",
        "hora_regresso_limite": "19:00", "inicio": None, "fim": None, "evitar_portagens": False,
        "paragens": [deepcopy(p) for p in paragens], "calculo": None, "criado_em": "2026-10-10T09:00:00Z",
        "criado_por": MEMBRO, "atualizado_em": ANTES_CARIMBO, "atualizado_por": MEMBRO, **campos,
    }


def _calculo(**campos):
    return {
        "assinatura": "sha256:" + "0" * 64, "distancia_m": 12345, "duracao_s": 2345, "regresso_previsto": "12:30",
        "depois_do_limite": False, "geometria": "_p~iF~ps|U_ulLnnqC_mqNvxq`@", "calculado_em": "2026-10-10T09:05:00Z",
        **campos,
    }


def _loja(id_, nome, fase, ponto, **extra):
    """Uma loja da base, com mais campos do que a projeção da rota traz."""
    return {
        "id": id_, "nome": nome, "fase": fase, "lat": ponto[0], "lng": ponto[1], "telefone": "+351911111111",
        "janelas": [], "dias_fechada": [], "morada": "Rua X 1", "notas": "não sai na rota", "regiao_id": None, **extra,
    }


def _lojas_na_base():
    return [
        _loja(LOJA_A, "Café A", "contactada", (38.7075, -9.1364)),
        _loja(LOJA_B, "Pastelaria B", "potencial", (38.7253, -9.15)),
        _loja(LOJA_C, "Mercearia C", "cliente", (38.6979, -9.2065)),
        _loja(LOJA_D, "Quiosque D", "potencial", (38.71, -9.14)),
    ]


def _projetada(loja):
    return {campo: loja[campo] for campo in PROJECAO_LOJA_ROTA if campo != "_id"}


def _base(rotas=(), lojas=()):
    return BaseFalsa({ROTAS: list(rotas), LOJAS: list(lojas)})


def _rotas(base):
    return base[ROTAS]


def _alterar(base, rota, set_, **opcoes):
    opcoes.setdefault("membro_id", OUTRO)
    opcoes.setdefault("agora", AGORA)
    return correr(alterar(base, rota, set_, **opcoes))


def _acrescentar(base, rota, paragem, **opcoes):
    opcoes.setdefault("membro_id", OUTRO)
    opcoes.setdefault("agora", AGORA)
    return correr(acrescentar_paragem(base, rota, paragem, **opcoes))


def _nova_paragem(loja_id=LOJA_B, ordem=1):
    return documento_paragem({"id": loja_id}, "amostra", 10, ordem, OUTRO, AGORA)


# As rotas com um registo do motorista, ou fora dos estados editáveis: nenhuma
# escrita do escritório casa, e `porque_falhou` diz `em_curso`.
COM_REGISTO_DO_TERRENO = [
    _rota(estado="em_curso"),
    _rota(estado="concluida"),
    _rota([_feita("a", LOJA_A, 0)]),
    _rota([_paragem("a", LOJA_A, 0, estado="nao_feita")]),
    _rota([_retirada("a", LOJA_A, estado="feita")]),
    _rota([_paragem("a", LOJA_A, 0), _feita("b", LOJA_B, 1)]),
]
IDS_COM_REGISTO = [
    "estado-em-curso", "estado-concluida", "paragem-feita", "paragem-nao-feita", "retirada-feita",
    "segunda-paragem-feita",
]


# --- ler -----------------------------------------------------------------------------------------


def test_ler_procura_pela_data_e_sem_o_id_do_mongo():
    base = _base([_rota()])
    assert correr(ler(base, DIA)) == _rota()
    assert _rotas(base).registo == [("find_one", {"data": DIA}, SEM_ID)]


def test_ler_de_um_dia_sem_rota_e_none():
    base = _base([_rota()])
    assert correr(ler(base, "2026-10-14")) is None
    assert _rotas(base).registo == [("find_one", {"data": "2026-10-14"}, SEM_ID)]


def test_ler_devolve_uma_copia_da_base():
    base = _base([_rota()])
    lida = correr(ler(base, DIA))
    lida["estado"] = "planeada"
    lida["paragens"].append("x")
    assert _rotas(base).sem_id() == [_rota()]


@pytest.mark.parametrize("data", [date(2026, 10, 13), datetime(2026, 10, 13, tzinfo=UTC), None, 20261013])
def test_ler_exige_o_dia_em_texto(data):
    base = _base([_rota()])
    with pytest.raises(TypeError):
        correr(ler(base, data))
    assert _rotas(base).registo == []


@pytest.mark.parametrize("data", ["2026-1-1", "13/10/2026", "", "2026-02-30", "2026-10-13T00:00:00Z", " 2026-10-13"])
def test_ler_exige_um_dia_aaaa_mm_dd(data):
    base = _base([_rota()])
    with pytest.raises(ValueError):
        correr(ler(base, data))
    assert _rotas(base).registo == []


# --- criar ---------------------------------------------------------------------------------------


def test_criar_grava_a_rota_nova_e_devolve_true():
    base = _base()
    documento = documento_rota(date(2026, 10, 13), MEMBRO, AGORA, DEFINICOES)
    antes = deepcopy(documento)
    assert correr(criar(base, documento)) is True
    assert _rotas(base).sem_id() == [antes]
    assert _rotas(base).registo == [("insert_one", antes)]


def test_criar_deixa_o_documento_de_quem_chama_sem_o_id_do_mongo():
    documento = documento_rota(date(2026, 10, 13), MEMBRO, AGORA, DEFINICOES)
    antes = deepcopy(documento)
    correr(criar(_base(), documento))
    assert documento == antes


def test_criar_com_a_data_repetida_devolve_false_e_nao_grava():
    base = _base([_rota()])
    documento = documento_rota(date(2026, 10, 13), OUTRO, AGORA, DEFINICOES)
    assert correr(criar(base, documento)) is False
    assert _rotas(base).sem_id() == [_rota()]
    assert [chamada[0] for chamada in _rotas(base).registo] == ["insert_one"]


def test_criar_com_a_chave_repetida_injetada_devolve_false():
    falha = DuplicateKeyError("E11000 duplicate key error collection: crm_rotas index: data_1", 11000)
    base = BaseFalsa({ROTAS: ColeccaoFalsa(unicos=("id", "data"), falhar={"insert_one": falha})})
    assert correr(criar(base, documento_rota(date(2026, 10, 13), MEMBRO, AGORA, DEFINICOES))) is False


def test_criar_deixa_passar_as_outras_falhas_da_base():
    base = BaseFalsa({ROTAS: ColeccaoFalsa(unicos=("id", "data"), falhar={"insert_one": OperationFailure("fora")})})
    with pytest.raises(OperationFailure):
        correr(criar(base, documento_rota(date(2026, 10, 13), MEMBRO, AGORA, DEFINICOES)))


@pytest.mark.parametrize("documento", [None, [], "rota", 1])
def test_criar_exige_um_dicionario(documento):
    base = _base()
    with pytest.raises(TypeError):
        correr(criar(base, documento))
    assert _rotas(base).registo == []


# --- alterar -------------------------------------------------------------------------------------


def test_alterar_e_uma_so_escrita_condicional_com_o_filtro_e_a_atualizacao_exatos():
    base = _base([_rota()])
    _alterar(base, _rota(), {"hora_saida": "09:00"})
    assert _rotas(base).registo == [
        (
            "find_one_and_update",
            FILTRO_DE_ESCRITA,
            {
                "$set": {"hora_saida": "09:00", "atualizado_em": AGORA_CARIMBO, "atualizado_por": OUTRO},
                "$inc": {"versao": 1},
            },
            SEM_ID,
            False,
            ReturnDocument.AFTER,
        )
    ]


def test_alterar_devolve_a_rota_como_ficou_e_sobe_a_versao():
    base = _base([_rota()])
    depois = _alterar(base, _rota(), {"hora_saida": "09:00", "evitar_portagens": True})
    assert depois == _rota(
        hora_saida="09:00", evitar_portagens=True, versao=4, atualizado_em=AGORA_CARIMBO, atualizado_por=OUTRO
    )
    assert _rotas(base).sem_id() == [depois]


def test_alterar_com_o_relogio_atrasado_avanca_um_microssegundo():
    rota = _rota(atualizado_em=AGORA_CARIMBO)
    base = _base([rota])
    depois = _alterar(base, rota, {"estado": "planeada"})
    assert depois["atualizado_em"] == "2026-10-10T09:30:15.987655Z"
    assert depois["estado"] == "planeada"


def test_alterar_sem_subir_a_versao_so_escreve_o_set():
    rota = _rota([_paragem("b", LOJA_B, 0)])
    base = _base([rota])
    set_ = {**caminhos_paragem(0, {"chegada_prevista": "10:00", "espera_min": 0}), "calculo": _calculo()}
    depois = _alterar(base, rota, set_, subir_versao=False)
    assert _rotas(base).registo == [
        ("find_one_and_update", FILTRO_DE_ESCRITA, {"$set": set_}, SEM_ID, False, ReturnDocument.AFTER)
    ]
    assert depois == _rota([_paragem("b", LOJA_B, 0, chegada_prevista="10:00", espera_min=0)], calculo=_calculo())


def test_alterar_sem_subir_a_versao_nao_le_o_atualizado_em():
    rota = _rota(atualizado_em=None)
    base = _base([rota])
    assert _alterar(base, rota, {"calculo": None}, subir_versao=False) == rota


def test_alterar_escreve_nas_paragens_pelos_caminhos_por_indice_sem_tocar_no_terreno():
    paragens = [_paragem("a", LOJA_A, 0), _paragem("b", LOJA_B, 1)]
    base = _base([_rota(paragens)])
    set_ = {
        **caminhos_paragem(0, {"ordem": 1}),
        **caminhos_paragem(1, {"ordem": 0, "motivo": "entrega", "tempo_servico_min": 10}),
    }
    depois = _alterar(base, _rota(paragens), set_)
    assert depois["paragens"] == [
        _paragem("a", LOJA_A, 1),
        _paragem("b", LOJA_B, 0, motivo="entrega", tempo_servico_min=10),
    ]


def test_alterar_retira_uma_paragem_pelos_caminhos_do_escritorio():
    paragens = [_paragem("a", LOJA_A, 0), _paragem("b", LOJA_B, 1)]
    base = _base([_rota(paragens)])
    set_ = {**caminhos_paragem(0, {"removida_em": AGORA_INSTANTE, "ordem": None}), **caminhos_paragem(1, {"ordem": 0})}
    depois = _alterar(base, _rota(paragens), set_)
    assert depois["paragens"] == [_paragem("a", LOJA_A, None, removida_em=AGORA_INSTANTE), _paragem("b", LOJA_B, 0)]


def test_alterar_falha_sem_escrever_quando_a_versao_mudou():
    base = _base([_rota(versao=4)])
    assert _alterar(base, _rota(versao=3), {"hora_saida": "09:00"}) is None
    assert _rotas(base).sem_id() == [_rota(versao=4)]
    assert [chamada[0] for chamada in _rotas(base).registo] == ["find_one_and_update"]


@pytest.mark.parametrize("gravada", COM_REGISTO_DO_TERRENO, ids=IDS_COM_REGISTO)
def test_alterar_falha_sem_escrever_numa_rota_com_registo_do_terreno(gravada):
    base = _base([gravada])
    assert _alterar(base, deepcopy(gravada), {"hora_saida": "09:00"}) is None
    assert _rotas(base).sem_id() == [gravada]


def test_alterar_falha_quando_o_motorista_escreve_entre_a_leitura_e_a_escrita():
    paragens = [_paragem("a", LOJA_A, 0)]
    base = _base([_rota(paragens)])

    def motorista(docs):
        docs[0]["paragens"][0]["estado"] = "feita"

    _rotas(base).antes_de("find_one_and_update", motorista)
    assert _alterar(base, _rota(paragens), {"hora_saida": "09:00"}) is None
    assert _rotas(base).sem_id() == [_rota([_paragem("a", LOJA_A, 0, estado="feita")])]


def test_alterar_numa_rota_que_ja_nao_existe_e_none():
    base = _base()
    assert _alterar(base, _rota(), {"hora_saida": "09:00"}) is None


@pytest.mark.parametrize(
    "set_",
    [
        {"id": "r-2"},
        {"data": "2026-10-14"},
        {"versao": 9},
        {"criado_em": AGORA_INSTANTE},
        {"criado_por": OUTRO},
        {"atualizado_em": AGORA_CARIMBO},
        {"atualizado_por": OUTRO},
        {"paragens": []},
        {"paragens.0": _paragem("a", LOJA_A, 0)},
        {"paragens.0.estado": "feita"},
        {"paragens.0.resultado": "interessado"},
        {"paragens.0.concluida_em": None},
        {"paragens.0.id": "p-x"},
        {"paragens.0.loja_id": LOJA_B},
        {"paragens.$.ordem": 0},
        {"paragens.$[].ordem": 0},
        {"paragens.$[p].ordem": 0},
        {"paragens.x.ordem": 0},
        {"paragens.0.ordem.x": 0},
        {"paragens.-1.ordem": 0},
        {"paragens.0.cor": "azul"},
        {"$inc": {"versao": 1}},
        {},
        {"hora_saida": "09:00", "paragens.0.estado": "feita"},
    ],
    ids=[
        "id", "data", "versao", "criado_em", "criado_por", "atualizado_em", "atualizado_por", "lista-inteira",
        "paragem-inteira", "terreno-estado", "terreno-resultado", "terreno-concluida_em", "imutavel-id",
        "imutavel-loja_id", "posicional", "posicional-todos", "posicional-filtrado", "sem-indice",
        "abaixo-do-campo", "indice-negativo", "campo-desconhecido", "operador", "vazio", "misturado",
    ],
)
def test_alterar_recusa_sem_escrever_o_que_o_escritorio_nao_escreve(set_):
    rota = _rota([_paragem("a", LOJA_A, 0)])
    base = _base([rota])
    with pytest.raises(ValueError):
        _alterar(base, rota, set_)
    with pytest.raises(ValueError):
        _alterar(base, rota, set_, subir_versao=False)
    assert _rotas(base).registo == []


@pytest.mark.parametrize("set_", [None, [("hora_saida", "09:00")], "hora_saida"])
def test_alterar_exige_um_dicionario_de_campos(set_):
    base = _base([_rota()])
    with pytest.raises(TypeError):
        _alterar(base, _rota(), set_)
    assert _rotas(base).registo == []


@pytest.mark.parametrize("estragado", ["2026-10-10T09:00:00Z", None, 1760000000, ""])
def test_alterar_com_um_atualizado_em_estragado_na_base_e_erro_sem_escrever(estragado):
    rota = _rota(atualizado_em=estragado)
    base = _base([rota])
    with pytest.raises(ValueError):
        _alterar(base, rota, {"hora_saida": "09:00"})
    assert _rotas(base).registo == []


def test_alterar_com_um_agora_sem_fuso_e_erro_sem_escrever():
    base = _base([_rota()])
    with pytest.raises(ValueError):
        _alterar(base, _rota(), {"hora_saida": "09:00"}, agora=AGORA.replace(tzinfo=None))
    assert _rotas(base).registo == []


def test_alterar_tem_o_membro_e_o_agora_so_por_nome():
    base = _base([_rota()])
    with pytest.raises(TypeError):
        correr(alterar(base, _rota(), {"hora_saida": "09:00"}, True, OUTRO, AGORA))
    with pytest.raises(TypeError):
        correr(alterar(base, _rota(), {"hora_saida": "09:00"}, agora=AGORA))
    with pytest.raises(TypeError):
        correr(alterar(base, _rota(), {"hora_saida": "09:00"}, membro_id=OUTRO))
    assert _rotas(base).registo == []


def test_alterar_nao_mexe_na_rota_nem_no_set_recebidos():
    rota = _rota([_paragem("a", LOJA_A, 0)])
    set_ = {**caminhos_paragem(0, {"ordem": 0}), "hora_saida": "09:00"}
    antes = (deepcopy(rota), deepcopy(set_))
    _alterar(_base([rota]), rota, set_)
    assert (rota, set_) == antes


# --- acrescentar_paragem -------------------------------------------------------------------------


def test_acrescentar_paragem_faz_push_no_fim_com_a_versao_e_o_carimbo():
    rota = _rota([_paragem("a", LOJA_A, 0)])
    base = _base([rota])
    nova = _nova_paragem()
    depois = _acrescentar(base, rota, nova)
    assert _rotas(base).registo == [
        (
            "find_one_and_update",
            FILTRO_DE_ESCRITA,
            {
                "$push": {"paragens": nova},
                "$set": {"atualizado_em": AGORA_CARIMBO, "atualizado_por": OUTRO},
                "$inc": {"versao": 1},
            },
            SEM_ID,
            False,
            ReturnDocument.AFTER,
        )
    ]
    assert depois == _rota([_paragem("a", LOJA_A, 0), nova], versao=4, atualizado_em=AGORA_CARIMBO, atualizado_por=OUTRO)
    assert _rotas(base).sem_id() == [depois]


def test_acrescentar_paragem_numa_rota_sem_paragens():
    base = _base([_rota()])
    nova = _nova_paragem(LOJA_A, 0)
    depois = _acrescentar(base, _rota(), nova)
    assert depois["paragens"] == [nova] and depois["versao"] == 4


def test_acrescentar_paragem_falha_sem_escrever_quando_a_versao_mudou():
    base = _base([_rota(versao=4)])
    assert _acrescentar(base, _rota(versao=3), _nova_paragem()) is None
    assert _rotas(base).sem_id() == [_rota(versao=4)]
    assert [chamada[0] for chamada in _rotas(base).registo] == ["find_one_and_update"]


@pytest.mark.parametrize("gravada", COM_REGISTO_DO_TERRENO, ids=IDS_COM_REGISTO)
def test_acrescentar_paragem_falha_sem_escrever_numa_rota_com_registo_do_terreno(gravada):
    base = _base([gravada])
    assert _acrescentar(base, deepcopy(gravada), _nova_paragem(LOJA_C, 5)) is None
    assert _rotas(base).sem_id() == [gravada]


def test_acrescentar_paragem_falha_quando_o_motorista_escreve_entre_a_leitura_e_a_escrita():
    paragens = [_paragem("a", LOJA_A, 0)]
    base = _base([_rota(paragens)])

    def motorista(docs):
        docs[0]["paragens"][0]["estado"] = "nao_feita"

    _rotas(base).antes_de("find_one_and_update", motorista)
    assert _acrescentar(base, _rota(paragens), _nova_paragem()) is None
    assert _rotas(base).sem_id() == [_rota([_paragem("a", LOJA_A, 0, estado="nao_feita")])]


@pytest.mark.parametrize(
    "estragada",
    [
        {**_nova_paragem(), "estado": "feita"},
        {**_nova_paragem(), "estado": "nao_feita"},
        {**_nova_paragem(), "estado": None},
        {**_nova_paragem(), "resultado": "interessado"},
        {**_nova_paragem(), "concluida_em": AGORA_INSTANTE},
        {c: v for c, v in _nova_paragem().items() if c != "estado"},
        {c: v for c, v in _nova_paragem().items() if c != "resultado"},
        {c: v for c, v in _nova_paragem().items() if c != "concluida_em"},
    ],
    ids=["feita", "nao-feita", "estado-nulo", "com-resultado", "concluida", "sem-estado", "sem-resultado", "sem-concluida_em"],
)
def test_acrescentar_paragem_recusa_sem_escrever_uma_paragem_que_nao_nasce_pendente(estragada):
    base = _base([_rota()])
    with pytest.raises(ValueError):
        _acrescentar(base, _rota(), estragada)
    assert _rotas(base).registo == []


@pytest.mark.parametrize("paragem", [None, [], "paragem", 1])
def test_acrescentar_paragem_exige_um_dicionario(paragem):
    base = _base([_rota()])
    with pytest.raises(TypeError):
        _acrescentar(base, _rota(), paragem)
    assert _rotas(base).registo == []


def test_acrescentar_paragem_com_um_atualizado_em_estragado_na_base_e_erro_sem_escrever():
    rota = _rota(atualizado_em="2026-10-10T09:00:00Z")
    base = _base([rota])
    with pytest.raises(ValueError):
        _acrescentar(base, rota, _nova_paragem())
    assert _rotas(base).registo == []


def test_acrescentar_paragem_tem_o_membro_e_o_agora_so_por_nome():
    base = _base([_rota()])
    with pytest.raises(TypeError):
        correr(acrescentar_paragem(base, _rota(), _nova_paragem(), OUTRO, AGORA))
    assert _rotas(base).registo == []


def test_acrescentar_paragem_nao_mexe_na_rota_nem_na_paragem_recebidas():
    rota = _rota([_paragem("a", LOJA_A, 0)])
    nova = _nova_paragem()
    antes = (deepcopy(rota), deepcopy(nova))
    _acrescentar(_base([rota]), rota, nova)
    assert (rota, nova) == antes


# --- Correção "F3-INT-1": o cálculo lido também guarda a escrita ----------------------------------
#
# O recalcular grava as horas e o `calculo` sem subir a versão, e as outras
# escritas montam o `$set` por diferença contra a rota lida. Sem o cálculo no
# filtro, uma escrita lida antes de um recálculo casava e deixava as horas
# dele debaixo de outro cálculo.


def test_o_filtro_de_guarda_leva_a_identidade_do_calculo_lido():
    """Com cálculo: a assinatura e o `calculado_em` lidos (os caminhos com
    ponto, sem a geometria); sem cálculo, `calculo: None`. Nas duas escritas."""
    calculo = _calculo(assinatura="sha256:" + "1" * 64, calculado_em="2026-10-10T09:20:00Z")
    rota = _rota([_paragem("a", LOJA_A, 0)], calculo=calculo)
    base = _base([rota])
    _alterar(base, rota, {"hora_saida": "09:00"}, subir_versao=False)
    _acrescentar(base, rota, _nova_paragem())
    com_calculo = {
        "id": "r-1",
        "versao": 3,
        "calculo.assinatura": "sha256:" + "1" * 64,
        "calculo.calculado_em": "2026-10-10T09:20:00Z",
        "estado": {"$in": ["rascunho", "planeada"]},
        "paragens.estado": {"$nin": ["feita", "nao_feita"]},
    }
    assert [chamada[1] for chamada in _rotas(base).registo] == [com_calculo, com_calculo]
    sem = _base([_rota()])
    _alterar(sem, _rota(), {"hora_saida": "09:00"})
    _acrescentar(sem, _rota(), _nova_paragem())
    assert [chamada[1] for chamada in _rotas(sem).registo] == [FILTRO_DE_ESCRITA, FILTRO_DE_ESCRITA]


@pytest.mark.parametrize("calculo_lido", [None, _calculo()], ids=["sem-calculo", "com-calculo"])
def test_um_recalculo_gravado_depois_da_leitura_faz_falhar_as_escritas_lidas_antes(calculo_lido):
    """Outra pessoa recalcula entre a leitura e a escrita (as horas e um
    `calculo` novo, a versão igual): nenhuma das escritas lidas antes casa —
    nem as que sobem a versão nem as que não sobem — e fica o recálculo tal
    e qual; `porque_falhou` diz `conflito`."""
    lida = _rota([_paragem("a", LOJA_A, 0), _paragem("b", LOJA_B, 1)], calculo=deepcopy(calculo_lido))
    base = _base([deepcopy(lida)])
    recalculo = {
        **caminhos_paragem(0, {"chegada_prevista": "08:20", "espera_min": 0, "fora_de_horario": True}),
        "calculo": _calculo(assinatura="sha256:" + "2" * 64, calculado_em="2026-10-10T09:31:00Z"),
    }
    gravada = _alterar(base, deepcopy(lida), recalculo, subir_versao=False)
    assert gravada["versao"] == 3
    assert _alterar(base, lida, {"hora_saida": "09:00"}) is None
    assert _alterar(base, lida, {**caminhos_paragem(0, {"fora_de_horario": False}), "calculo": None}, subir_versao=False) is None
    assert _acrescentar(base, lida, _nova_paragem(LOJA_C, 2)) is None
    assert _rotas(base).sem_id() == [gravada]
    assert correr(porque_falhou(base, "r-1", 3)) == "conflito"


def test_relida_depois_do_recalculo_a_escrita_casa():
    """Quem relê a rota depois do recálculo leva o cálculo novo no filtro e grava."""
    base = _base([_rota([_paragem("a", LOJA_A, 0)])])
    novo = _calculo(calculado_em="2026-10-10T09:31:00Z")
    relida = _alterar(base, _rota([_paragem("a", LOJA_A, 0)]), {"calculo": novo}, subir_versao=False)
    depois = _alterar(base, relida, {"hora_saida": "09:00"})
    assert (depois["versao"], depois["hora_saida"], depois["calculo"]) == (4, "09:00", novo)
    assert _rotas(base).registo[1][1] == {
        "id": "r-1",
        "versao": 3,
        "calculo.assinatura": novo["assinatura"],
        "calculo.calculado_em": "2026-10-10T09:31:00Z",
        "estado": {"$in": ["rascunho", "planeada"]},
        "paragens.estado": {"$nin": ["feita", "nao_feita"]},
    }


# --- porque_falhou -------------------------------------------------------------------------------


def test_porque_falhou_rele_a_rota_pelo_id_sem_o_calculo():
    base = _base([_rota(versao=4)])
    assert correr(porque_falhou(base, "r-1", 3)) == "conflito"
    assert _rotas(base).registo == [("find_one", {"id": "r-1"}, SEM_CALCULO)]


def test_porque_falhou_sem_rota_e_nao_existe():
    base = _base([_rota()])
    assert correr(porque_falhou(base, "r-9", 3)) == "nao_existe"


@pytest.mark.parametrize("gravada", COM_REGISTO_DO_TERRENO, ids=IDS_COM_REGISTO)
def test_porque_falhou_com_registo_do_terreno_e_em_curso(gravada):
    base = _base([gravada])
    assert correr(porque_falhou(base, "r-1", 3)) == "em_curso"


@pytest.mark.parametrize("gravada", COM_REGISTO_DO_TERRENO, ids=IDS_COM_REGISTO)
def test_porque_falhou_com_a_versao_mudada_e_registo_do_terreno_e_em_curso(gravada):
    # Correção "T3.17 (porque_falhou: precedência)": as duas coisas ao mesmo
    # tempo dão `em_curso`, para o planeador passar a só leitura em vez de
    # recarregar e tentar outra vez.
    base = _base([{**gravada, "versao": 5}])
    assert correr(porque_falhou(base, "r-1", 3)) == "em_curso"


def test_porque_falhou_com_a_versao_mudada_numa_rota_editavel_e_conflito():
    base = _base([_rota([_paragem("a", LOJA_A, 0)], versao=4)])
    assert correr(porque_falhou(base, "r-1", 3)) == "conflito"


def test_porque_falhou_sem_motivo_visivel_e_conflito_e_fica_registado(caplog):
    base = _base([_rota(versao=3)])
    with caplog.at_level(logging.WARNING, logger="crm.rotas_bd"):
        assert correr(porque_falhou(base, "r-1", 3)) == "conflito"
    assert [registo.getMessage() for registo in caplog.records] == [
        "[crm] rota r-1: a escrita condicional falhou e a versão 3 continua gravada numa rota editável"
    ]


def test_porque_falhou_com_um_conflito_verdadeiro_nao_regista_nada(caplog):
    base = _base([_rota(versao=4)])
    with caplog.at_level(logging.DEBUG, logger="crm"):
        assert correr(porque_falhou(base, "r-1", 3)) == "conflito"
    assert caplog.records == []


def test_porque_falhou_so_le():
    base = _base([_rota([_feita("a", LOJA_A, 0)], versao=5)])
    correr(porque_falhou(base, "r-1", 3))
    assert [chamada[0] for chamada in _rotas(base).registo] == ["find_one"]
    assert _rotas(base).sem_id() == [_rota([_feita("a", LOJA_A, 0)], versao=5)]


def test_os_motivos_da_falha_sao_os_tres_do_plano():
    assert (rotas_bd.NAO_EXISTE, rotas_bd.EM_CURSO, rotas_bd.CONFLITO) == ("nao_existe", "em_curso", "conflito")


# --- lojas_da_rota -------------------------------------------------------------------------------


def test_lojas_da_rota_le_as_lojas_das_paragens_ativas_pela_projecao_da_rota():
    rota = _rota([_paragem("a", LOJA_A, 2), _paragem("b", LOJA_B, 0), _paragem("c", LOJA_C, 1), _retirada("d", LOJA_D)])
    base = _base([rota], _lojas_na_base())
    lojas = correr(lojas_da_rota(base, rota))
    assert base[LOJAS].registo == [("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA)]
    assert sorted(lojas, key=lambda loja: loja["id"]) == [_projetada(loja) for loja in _lojas_na_base()[:3]]


def test_lojas_da_rota_poe_uma_paragem_com_ordem_nula_no_fim():
    rota = _rota([_paragem("a", LOJA_A, None, estado="feita"), _paragem("b", LOJA_B, 0)])
    base = _base([rota], _lojas_na_base())
    correr(lojas_da_rota(base, rota))
    assert base[LOJAS].registo == [("find", {"id": {"$in": [LOJA_B, LOJA_A]}}, PROJECAO_LOJA_ROTA)]


def test_lojas_da_rota_sem_paragens_ativas_nao_vai_a_base():
    rota = _rota([_retirada("d", LOJA_D)])
    base = _base([rota], _lojas_na_base())
    assert correr(lojas_da_rota(base, rota)) == []
    assert base[LOJAS].registo == []


def test_lojas_da_rota_de_uma_rota_virtual_e_vazia():
    base = _base([], _lojas_na_base())
    assert correr(lojas_da_rota(base, None)) == []
    assert base[LOJAS].registo == []


def test_lojas_da_rota_devolve_uma_lista_nova_de_cada_vez():
    rota = _rota([_paragem("a", LOJA_A, 0)])
    base = _base([rota], _lojas_na_base())
    primeira = correr(lojas_da_rota(base, rota))
    primeira[0]["nome"] = "mudado"
    assert correr(lojas_da_rota(base, rota)) == [_projetada(_lojas_na_base()[0])]


# --- rotas_entre ---------------------------------------------------------------------------------


def _rotas_de_outubro():
    # Fora de ordem de propósito: a leitura ordena por `data`.
    return [
        _rota(id="r-31", data="2026-10-31"),
        _rota(id="r-01", data="2026-10-01"),
        _rota(id="r-11-01", data="2026-11-01"),
        _rota([_paragem("a", LOJA_A, 0)], id="r-15", data="2026-10-15", calculo=_calculo()),
        _rota(id="r-09-30", data="2026-09-30"),
    ]


def test_rotas_entre_le_o_intervalo_fechado_sem_o_calculo_e_por_data():
    base = _base(_rotas_de_outubro())
    lidas = correr(rotas_entre(base, "2026-10-01", "2026-10-31"))
    assert _rotas(base).registo == [("find", {"data": {"$gte": "2026-10-01", "$lte": "2026-10-31"}}, SEM_CALCULO)]
    assert [rota["id"] for rota in lidas] == ["r-01", "r-15", "r-31"]
    assert lidas[1] == {c: v for c, v in _rotas_de_outubro()[3].items() if c != "calculo"}
    assert all("_id" not in rota and "calculo" not in rota for rota in lidas)


def test_rotas_entre_de_um_so_dia():
    base = _base(_rotas_de_outubro())
    assert [rota["id"] for rota in correr(rotas_entre(base, "2026-10-15", "2026-10-15"))] == ["r-15"]


def test_rotas_entre_sem_rotas_no_intervalo_e_vazio():
    base = _base(_rotas_de_outubro())
    assert correr(rotas_entre(base, "2026-10-02", "2026-10-14")) == []
    assert correr(rotas_entre(base, "2026-10-31", "2026-10-01")) == []


@pytest.mark.parametrize(
    "de, ate", [(date(2026, 10, 1), "2026-10-31"), ("2026-10-01", date(2026, 10, 31)), (None, "2026-10-31")]
)
def test_rotas_entre_exige_os_dias_em_texto(de, ate):
    base = _base(_rotas_de_outubro())
    with pytest.raises(TypeError):
        correr(rotas_entre(base, de, ate))
    assert _rotas(base).registo == []


@pytest.mark.parametrize("de, ate", [("2026-1-1", "2026-10-31"), ("2026-10-01", "2026-13-01"), ("", "")])
def test_rotas_entre_exige_dias_aaaa_mm_dd(de, ate):
    base = _base(_rotas_de_outubro())
    with pytest.raises(ValueError):
        correr(rotas_entre(base, de, ate))
    assert _rotas(base).registo == []


# --- rotas_com_loja ------------------------------------------------------------------------------


def _rotas_com_a_loja_a():
    return [
        _rota([_paragem("a", LOJA_A, 0)], id="r-20", data="2026-10-20", calculo=_calculo()),
        _rota([_retirada("a", LOJA_A)], id="r-13", data="2026-10-13"),
        _rota([_paragem("b", LOJA_B, 0)], id="r-14", data="2026-10-14"),
        _rota(id="r-15", data="2026-10-15"),
    ]


def test_rotas_com_loja_le_pelas_paragens_sem_o_calculo_e_por_data():
    base = _base(_rotas_com_a_loja_a())
    lidas = correr(rotas_com_loja(base, LOJA_A))
    assert _rotas(base).registo == [("find", {"paragens.loja_id": LOJA_A}, SEM_CALCULO)]
    assert [rota["id"] for rota in lidas] == ["r-13", "r-20"]
    assert lidas[1] == {c: v for c, v in _rotas_com_a_loja_a()[0].items() if c != "calculo"}


def test_rotas_com_loja_sem_rotas_e_vazio():
    base = _base(_rotas_com_a_loja_a())
    assert correr(rotas_com_loja(base, LOJA_D)) == []


@pytest.mark.parametrize("loja_id", [None, 1, [LOJA_A], {"id": LOJA_A}])
def test_rotas_com_loja_exige_o_id_em_texto(loja_id):
    base = _base(_rotas_com_a_loja_a())
    with pytest.raises(TypeError):
        correr(rotas_com_loja(base, loja_id))
    assert _rotas(base).registo == []


# --- o varrimento de todas as escritas -----------------------------------------------------------


def test_todas_as_escritas_de_uma_sequencia_passam_nos_varrimentos_do_terreno_e_dos_instantes():
    base = _base(lojas=_lojas_na_base())
    assert correr(criar(base, documento_rota(date(2026, 10, 13), MEMBRO, AGORA, DEFINICOES))) is True
    rota = correr(ler(base, DIA))
    rota = _acrescentar(base, rota, documento_paragem({"id": LOJA_A}, "amostra", 10, 0, MEMBRO, AGORA))
    rota = _acrescentar(base, rota, documento_paragem({"id": LOJA_B}, "entrega", 10, 1, MEMBRO, AGORA))
    rota = _alterar(base, rota, {**caminhos_paragem(0, {"ordem": 1}), **caminhos_paragem(1, {"ordem": 0})})
    rota = _alterar(
        base, rota, {**caminhos_paragem(0, {"removida_em": AGORA_INSTANTE, "ordem": None}), **caminhos_paragem(1, {"ordem": 0})}
    )
    rota = _alterar(
        base,
        rota,
        {**caminhos_paragem(1, {"chegada_prevista": "09:30", "espera_min": 0, "fora_de_horario": False}), "calculo": _calculo()},
        subir_versao=False,
    )
    assert rota["versao"] == 5
    # Quatro escritas com versão a partir do mesmo relógio: cada carimbo avança um microssegundo.
    assert rota["atualizado_em"] == "2026-10-10T09:30:15.987658Z"
    escritas = [c[1] for c in _rotas(base).chamadas("insert_one")] + [
        c[2] for c in _rotas(base).chamadas("find_one_and_update")
    ]
    assert len(escritas) == 6
    for escrita in escritas:
        assert escritas_no_terreno(escrita) == []
        assert instantes_fora_do_formato(escrita) == []
    assert instantes_fora_do_formato(_rotas(base).sem_id()[0]) == []
    assert [p["estado"] for p in rota["paragens"]] == ["pendente", "pendente"]


# --- o módulo ------------------------------------------------------------------------------------


def test_o_modulo_nao_le_o_relogio_nem_o_ambiente_nem_abre_a_base_sozinho():
    """O `agora`, o membro e a base entram por parâmetro; o módulo só sabe o
    nome das coleções (`crm.db.COLECOES`)."""
    arvore = ast.parse(Path(rotas_bd.__file__).read_text(encoding="utf-8"))
    importados = {
        alias.name for n in ast.walk(arvore) if isinstance(n, (ast.Import, ast.ImportFrom)) for alias in n.names
    }
    assert "os" not in importados and "obter_db" not in importados
    atributos = {
        (n.value.id, n.attr) for n in ast.walk(arvore) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }
    assert ("relogio", "agora") not in atributos and ("relogio", "hoje") not in atributos
    assert ("bd", "obter_db") not in atributos
    assert ("relogio", "proximo_carimbo") in atributos
