"""Ensaio do comportamento real do MongoDB numa base local de teste (plano
T2.17; dossiê §3 e §12.7).

Os outros testes do CRM correm sobre o duplo (tests/crm/duplos.py), que não
modela índices parciais, compostos nem geográficos, nem a concorrência de um
servidor verdadeiro. Este ensaio repete, versionado, o que as conferências
locais da T2.8 à T2.13 mostraram à mão: o `criar_indices` verdadeiro, o
pré-filtro dos 50 m pelo índice `2dsphere`, a atualização condicional, os
índices únicos (também o parcial do `client_uuid`), os upserts das
definições (correções do plano, linha "T1.2 (test_indices) / T2.8"), as
corridas com o Motor nas rotas que dependem dos índices e, desde a T2.18, o
seed das lojas de demonstração (`seed_crm_local.aplicar_lojas`, com o
pymongo síncrono, na mesma base de teste): índices, rotas a ler o que gravou
e a reposição quando o Mongo recusa uma escrita. Desde a T3.25 (F3), as
rotas em `crm_rotas`: os índices (`data` única, `paragens.loja_id` multikey),
o `$push`/`$set` por índice com o filtro de guarda do escritório (a versão e
nenhum registo do motorista, pelo `$nin` através da lista), o erro 40 do
Mongo pela mesma operação que o código usa (`find_one_and_update` →
`OperationFailure`, correção "T3.25"), as datas em texto por `$gte`/`$lte`,
as corridas com o Motor dos `POST /paragens` (sem versão: as tentativas) e
dos `PATCH` (a mesma versão: um 200 e um 409) e o `DELETE /lojas/{id}` de
uma loja numa paragem.

Só corre com `CRM_MONGO_TESTE_URL` (variável de shell, nunca no
`.env.example`):

    cd "/Users/brucesilva/pasta sem título/RH/backend" && \\
      CRM_MONGO_TESTE_URL=mongodb://127.0.0.1:27017 \\
      .venv/bin/python -m pytest -q -p no:cacheprovider tests/crm/test_mongo_local.py

- Sem a variável, os testes do Mongo saltam com a razão escrita; os da guarda
  correm sempre (não ligam a nada).
- A guarda recusa (falha, sem ligar e sem mostrar a URI, que pode trazer uma
  palavra-passe) o que não passe `seed_crm_local.uri_e_local`, mais de uma
  máquina e uma base na URI que não seja `lisbonb_crm_teste`.
- Cada teste cria o seu `AsyncIOMotorClient` DENTRO da corrotina (o Motor
  prende-se ao ciclo de eventos), corre com `correr` (nunca o asyncio.run:
  correções do plano, linha "§10") e apaga a base `lisbonb_crm_teste` — só
  essa — no início e no fim.
- As rotas chamam-se diretamente (a função da rota com o membro que a guarda
  devolveria), com a base trocada pelo único ponto (`crm.db.obter_db`), como
  as corridas dos outros testes do CRM. Nas corridas, uma barreira segura as
  duas primeiras leituras da coleção até ambos os pedidos terem lido: sem
  ela, um pedido podia acabar antes de o outro começar e a corrida não se
  dava (o `PATCH` sem a versão no filtro passava).
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient, ReturnDocument, uri_parser
from pymongo.errors import DuplicateKeyError, OperationFailure, WriteError

import crm.db as bd
import seed_crm_local
from crm import relogio
from crm import rotas as rotas_http
from crm import rotas_bd
from crm.db import COLECOES, INDICES
from crm.definicoes import alterar_definicoes
from crm.dominio.datas import ler_data, somar_dias, texto_data
from crm.dominio.geo import distancia_metros, encontrar_duplicados, filtro_candidatos
from crm.formatar import documento_localizacao
from crm.formatar_rota import documento_paragem, documento_rota
from crm.dominio.texto import chave_comparacao
from crm.lojas import (
    MENSAGEM_CONFLITO,
    MENSAGEM_LOJA_EM_ROTA,
    MENSAGEM_LOJA_ESTEVE_EM_ROTA,
    MENSAGEM_NAO_ENCONTRADA,
    MUDANCA_FASE,
    alterar_loja,
    apagar_loja,
    criar_loja,
    ler_loja,
    listar_lojas,
)
from crm.membros import MENSAGEM_JA_MEMBRO, adicionar_membro
from crm.regioes import MENSAGEM_REPETIDA, alterar_regiao, criar_regiao, listar_regioes
from crm.rotas import MENSAGEM_ROTA_EM_CURSO

from .duplos import BaseFalsa, correr
from .formatos import escritas_no_terreno, instantes_fora_do_formato

VARIAVEL = "CRM_MONGO_TESTE_URL"
BASE_TESTE = "lisbonb_crm_teste"
RAZAO_SEM_VARIAVEL = (
    "ensaio no MongoDB local: só corre com CRM_MONGO_TESTE_URL=mongodb://127.0.0.1:27017 "
    "(base lisbonb_crm_teste, apagada no início e no fim)"
)
MENSAGEM_RECUSA = (
    "Recusado: o ensaio só corre num MongoDB local (mongodb:// com uma só máquina: "
    "127.0.0.1, localhost ou ::1) e na base lisbonb_crm_teste."
)
# Com o Mongo parado, falha em segundos em vez de ficar pendurado.
ESPERA_MS = 3000

ADMIN_LOCAL = "admin.local@example.com"
RUI_MEMBRO = {
    "user_id": "u-rui",
    "email": "rui@example.com",
    "role": "colaborador",
    "crm_perfil": "utilizador",
    "crm_admin_master": False,
}
ANA_MEMBRO = {
    "user_id": "u-ana",
    "email": "ana@example.com",
    "role": "contabilista",
    "crm_perfil": "admin",
    "crm_admin_master": False,
}
CONTA_DA_BEA = {"id": "u-bea", "email": "bea@example.com", "name": "Bea", "role": "colaborador"}

# Rua Augusta, em Lisboa; os outros pontos ficam para norte (no meridiano, a
# distância é R × Δlat em radianos: 1 m ≈ 0,000009°).
LAT = 38.710800
LNG = -9.136900
A_30_M = 38.711070  # 30,02 m: duplicado
A_55_M = 38.711295  # 55,04 m: dentro do círculo do Mongo (60 m), fora da regra dos 50 m
A_65_M = 38.711385  # 65,05 m: fora do círculo
A_80_M = 38.711520  # 80,06 m

PROJECAO_CANDIDATO = {"_id": 0, "id": 1, "nome": 1, "lat": 1, "lng": 1}

# Carimbos do bloqueio otimista (6 casas): o seguinte do V1 passa o segundo.
V1 = "2026-10-10T09:00:00.999999Z"
V2 = "2026-10-10T09:00:01.000000Z"


def uri_do_ensaio(ambiente):
    """A URI do ensaio, lida de `ambiente[CRM_MONGO_TESTE_URL]`. Não liga a
    nada: sem a variável (ou vazia), salta com a razão escrita; uma URI que
    não seja de um MongoDB local (`seed_crm_local.uri_e_local`, que nem
    interpreta um mongodb+srv://), com mais de uma máquina ou com outra base
    que não a `lisbonb_crm_teste` falha com a MENSAGEM_RECUSA, que nunca
    repete a URI."""
    uri = ambiente.get(VARIAVEL)
    if not uri:
        pytest.skip(RAZAO_SEM_VARIAVEL)
    if not seed_crm_local.uri_e_local(uri):
        pytest.fail(MENSAGEM_RECUSA, pytrace=False)
    partes = uri_parser.parse_uri(uri)
    if len(partes["nodelist"]) != 1 or partes["database"] not in (None, BASE_TESTE):
        pytest.fail(MENSAGEM_RECUSA, pytrace=False)
    return uri


def _id(n):
    """Um uuid4 em texto, fixo para os testes serem legíveis."""
    return f"00000000-0000-4000-8000-{n:012d}"


def _loja(n, lat, lng=LNG):
    return {"id": _id(n), "nome": f"Loja {n}", **documento_localizacao(lat, lng)}


def _corpo_loja(nome):
    """O corpo mínimo do `POST /lojas`, no ponto LAT/LNG."""
    return {"nome": nome, "fase": "potencial", "lat": LAT, "lng": LNG, "origem_coords": "pin_manual"}


def _cliente(uri):
    """Só a máquina da URI (`directConnection`: não segue para outras de um
    conjunto de réplicas) e esperas curtas."""
    return AsyncIOMotorClient(
        uri,
        directConnection=True,
        serverSelectionTimeoutMS=ESPERA_MS,
        connectTimeoutMS=ESPERA_MS,
        socketTimeoutMS=10 * ESPERA_MS,
    )


async def _numa_base_limpa(uri, ensaio, indices=True):
    """Corre `ensaio(base)` na `lisbonb_crm_teste` acabada de apagar (com os
    índices do `criar_indices` verdadeiro, se `indices`) e apaga-a no fim,
    também quando o ensaio falha. O cliente nasce aqui, dentro da corrotina."""
    cliente = _cliente(uri)
    try:
        await cliente.drop_database(BASE_TESTE)
        base = cliente[BASE_TESTE]
        if indices:
            await bd.criar_indices(base)
        return await ensaio(base)
    finally:
        try:
            await cliente.drop_database(BASE_TESTE)
        finally:
            cliente.close()


@pytest.fixture
def no_mongo(monkeypatch):
    """`no_mongo(ensaio, indices=True)` corre a corrotina `ensaio(base)` numa
    base limpa, com `crm.db.obter_db` a devolver essa base e o ADMIN_EMAIL
    local. Sem a variável, salta; com uma URI recusada, falha sem ligar."""
    uri = uri_do_ensaio(os.environ)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)

    def _correr(ensaio, indices=True):
        async def _com_a_base(base):
            monkeypatch.setattr(bd, "obter_db", lambda: base)
            return await ensaio(base)

        return correr(_numa_base_limpa(uri, _com_a_base, indices))

    _correr.uri = uri
    return _correr


def _separar(respostas):
    """As respostas de um `gather(..., return_exceptions=True)`: (as que
    gravaram, as HTTPException). Outra exceção qualquer rebenta o teste."""
    for resposta in respostas:
        if isinstance(resposta, BaseException) and not isinstance(resposta, HTTPException):
            raise resposta
    return (
        [r for r in respostas if not isinstance(r, HTTPException)],
        [r for r in respostas if isinstance(r, HTTPException)],
    )


class _Barreira:
    """Segura as primeiras `quantas` leituras até todas terem lido: os pedidos
    da corrida leem todos o estado antigo antes de qualquer um escrever (sem
    isto, um pedido podia acabar antes de o outro começar e a corrida não se
    dava). Uma leitura que não chega a tempo rebenta em vez de pendurar."""

    def __init__(self, quantas=2):
        self.quantas = quantas
        self.chegadas = 0
        self.todas = asyncio.Event()

    async def esperar(self):
        if self.chegadas >= self.quantas:
            return
        self.chegadas += 1
        if self.chegadas == self.quantas:
            self.todas.set()
        await asyncio.wait_for(self.todas.wait(), 5)


class _ColeccaoComBarreira:
    """A coleção verdadeira; só o `find_one` espera pela barreira DEPOIS de ler."""

    def __init__(self, real, barreira):
        self._real = real
        self._barreira = barreira

    async def find_one(self, *args, **kwargs):
        documento = await self._real.find_one(*args, **kwargs)
        await self._barreira.esperar()
        return documento

    def __getattr__(self, nome):
        return getattr(self._real, nome)


class _BaseComBarreira:
    """A base verdadeira, com a coleção `nome` atrás da barreira."""

    def __init__(self, real, nome, barreira):
        self._real = real
        self._nome = nome
        self._barreira = barreira

    def __getitem__(self, nome):
        coleccao = self._real[nome]
        return _ColeccaoComBarreira(coleccao, self._barreira) if nome == self._nome else coleccao

    def __getattr__(self, nome):
        return getattr(self._real, nome)


def _em_corrida(monkeypatch, base, coleccao):
    """Daqui em diante, as rotas veem `base` com as duas primeiras leituras de
    `coleccao` seguras pela barreira."""
    com_barreira = _BaseComBarreira(base, COLECOES[coleccao], _Barreira())
    monkeypatch.setattr(bd, "obter_db", lambda: com_barreira)


def _erro(codigo, mensagem):
    return {"codigo": codigo, "mensagem": mensagem}


def _plano(explicacao):
    return str(explicacao["queryPlanner"])


# --- A guarda (corre sempre, não liga a nada) -------------------------------------------------------


def test_sem_a_variavel_salta_com_a_razao_escrita():
    with pytest.raises(pytest.skip.Exception) as salto:
        uri_do_ensaio({})
    assert salto.value.msg == RAZAO_SEM_VARIAVEL


def test_com_a_variavel_vazia_tambem_salta():
    with pytest.raises(pytest.skip.Exception) as salto:
        uri_do_ensaio({VARIAVEL: ""})
    assert salto.value.msg == RAZAO_SEM_VARIAVEL


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://127.0.0.1:27017",
        "mongodb://127.0.0.1:27017/",
        "mongodb://localhost",
        "mongodb://[::1]:27017",
        "mongodb://127.0.0.1:27017/lisbonb_crm_teste",
        "mongodb://127.0.0.1:27017/?directConnection=true",
    ],
)
def test_aceita_um_mongo_local_e_a_base_de_teste(uri):
    assert uri_do_ensaio({VARIAVEL: uri}) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://exemplo.invalid/lisbonb_crm_teste",
        "mongodb://utilizador:segredo-falso@10.0.0.7:27017",
        "mongodb://127.0.0.1:27017,10.0.0.7:27017",
        "mongodb://127.0.0.1:27017,localhost:27018",
        "mongodb://127.0.0.1:27017/lisbonb_crm_local",
        "mongodb://127.0.0.1:27017/lisbonb?authSource=admin",
        "http://127.0.0.1:27017",
        "mongodb://",
    ],
    ids=[
        "atlas",
        "outra-maquina",
        "uma-local-e-outra-nao",
        "duas-maquinas-locais",
        "a-base-de-pre-visualizacao",
        "a-base-do-portal",
        "nao-e-mongodb",
        "sem-maquina",
    ],
)
def test_recusa_sem_ligar_e_sem_mostrar_a_uri(uri):
    with pytest.raises(pytest.fail.Exception) as falha:
        uri_do_ensaio({VARIAVEL: uri})
    assert str(falha.value) == MENSAGEM_RECUSA
    assert "segredo-falso" not in str(falha.value)


# --- A base de teste ---------------------------------------------------------------------------------


def test_apaga_so_a_base_de_teste_no_inicio_e_no_fim(no_mongo):
    """O que lá estava antes não chega ao ensaio, e no fim a base já não
    existe; as outras bases do servidor ficam como estavam."""

    async def _ve_e_escreve(base):
        # Escreve, para a base existir no fim se ninguém a apagar.
        vistas = await base.list_collection_names()
        await base["deste_ensaio"].insert_one({"id": "y"})
        return vistas

    async def _antes_e_depois():
        cliente = _cliente(no_mongo.uri)
        try:
            await cliente[BASE_TESTE]["restos_de_outro_ensaio"].insert_one({"id": "x"})
            antes = set(await cliente.list_database_names())
            vistas = await _numa_base_limpa(no_mongo.uri, _ve_e_escreve, indices=False)
            depois = set(await cliente.list_database_names())
            return antes, vistas, depois
        finally:
            cliente.close()

    antes, vistas, depois = no_mongo(lambda base: _antes_e_depois(), indices=False)

    assert BASE_TESTE in antes
    assert vistas == []
    assert depois == antes - {BASE_TESTE}


# --- Os índices --------------------------------------------------------------------------------------


def _sem_son(valor):
    """O SON do PyMongo (as opções lidas do servidor) em dicionários simples."""
    if isinstance(valor, dict):
        return {chave: _sem_son(dentro) for chave, dentro in valor.items()}
    return valor


def _indices_reais(informacao):
    """(chaves, opções) de cada índice do servidor, sem o `_id_`, na forma do
    `crm.db.INDICES`. As opções que contam: único, esparso, parcial."""
    reais = []
    for nome, indice in informacao.items():
        if nome == "_id_":
            continue
        chaves = [(campo, direcao if isinstance(direcao, str) else int(direcao)) for campo, direcao in indice["key"]]
        opcoes = {}
        if indice.get("unique"):
            opcoes["unique"] = True
        if indice.get("sparse"):
            opcoes["sparse"] = True
        if "partialFilterExpression" in indice:
            opcoes["partialFilterExpression"] = _sem_son(indice["partialFilterExpression"])
        reais.append((chaves, opcoes))
    return sorted(reais, key=repr)


def _declarados(coleccao):
    return sorted(((list(chaves), dict(opcoes)) for (c, chaves, opcoes) in INDICES if c == coleccao), key=repr)


def test_criar_indices_verdadeiro_sem_erros_e_exatamente_os_declarados(no_mongo, caplog):
    """Corrido duas vezes (o arranque seguinte), não regista erro nenhum e
    deixa em cada coleção exatamente os índices declarados."""

    async def ensaio(base):
        with caplog.at_level(logging.ERROR, logger="crm"):
            await bd.criar_indices(base)
            await bd.criar_indices(base)
        coleccoes = sorted(await base.list_collection_names())
        reais = {nome: _indices_reais(await base[nome].index_information()) for nome in COLECOES.values()}
        nomes_definicoes = sorted(await base[COLECOES["definicoes"]].index_information())
        return coleccoes, reais, nomes_definicoes

    coleccoes, reais, nomes_definicoes = no_mongo(ensaio, indices=False)

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert coleccoes == sorted(COLECOES.values())
    assert reais == {nome: _declarados(nome) for nome in COLECOES.values()}
    assert nomes_definicoes == ["_id_", "chave_1"], "crm_definicoes: só `chave` único, nunca índice em `id`."


# --- Duplicados a 50 m: o pré-filtro pelo índice 2dsphere ----------------------------------------------


def test_as_distancias_do_ensaio_sao_as_dos_nomes():
    medidas = [round(distancia_metros(LAT, LNG, lat, LNG), 2) for lat in (A_30_M, A_55_M, A_65_M, A_80_M)]
    assert medidas == [30.02, 55.04, 65.05, 80.06]


def test_o_filtro_dos_candidatos_encontra_a_loja_a_30_m_e_nao_a_de_80_m(no_mongo):
    """O círculo do Mongo (60 m) traz a de 30 m e a de 55 m; a regra exata
    (T2.3) deixa só a de 30 m. As de 65 m e 80 m nem são lidas."""

    async def ensaio(base):
        lojas = base[COLECOES["lojas"]]
        for n, lat in ((30, A_30_M), (55, A_55_M), (65, A_65_M), (80, A_80_M)):
            await lojas.insert_one(_loja(n, lat))
        return await lojas.find(filtro_candidatos(LAT, LNG), PROJECAO_CANDIDATO).to_list(100)

    candidatos = no_mongo(ensaio)

    assert sorted(c["id"] for c in candidatos) == [_id(30), _id(55)]
    assert encontrar_duplicados(candidatos, LAT, LNG) == [{"id": _id(30), "nome": "Loja 30", "distancia_m": 30}]


def test_na_edicao_o_filtro_dos_candidatos_deixa_de_fora_a_propria_loja(no_mongo):
    """Só a própria, nos dois sentidos (um `$gt`/`$lt` no lugar do `$ne`
    deixava passar um deles)."""

    async def ensaio(base):
        lojas = base[COLECOES["lojas"]]
        for n, lat in ((30, A_30_M), (55, A_55_M)):
            await lojas.insert_one(_loja(n, lat))
        achadas = []
        for n in (30, 55):
            filtro = filtro_candidatos(LAT, LNG, excluir_id=_id(n))
            achadas.append([c["id"] for c in await lojas.find(filtro, PROJECAO_CANDIDATO).to_list(100)])
        return achadas

    assert no_mongo(ensaio) == [[_id(55)], [_id(30)]]


def test_o_filtro_dos_candidatos_usa_o_indice_2dsphere(no_mongo):
    async def ensaio(base):
        lojas = base[COLECOES["lojas"]]
        await lojas.insert_one(_loja(30, A_30_M))
        sem_excluir = await lojas.find(filtro_candidatos(LAT, LNG)).explain()
        a_excluir = await lojas.find(filtro_candidatos(LAT, LNG, excluir_id=_id(30))).explain()
        return _plano(sem_excluir), _plano(a_excluir)

    sem_excluir, a_excluir = no_mongo(ensaio)

    assert "loc_2dsphere" in sem_excluir
    assert "loc_2dsphere" in a_excluir


def test_um_loc_fora_do_mundo_e_recusado_pelo_indice_2dsphere(no_mongo):
    """O `loc` tem de ser sempre um Point válido: o Mongo recusa gravar outro
    (por isso `lat`/`lng`/`loc` escrevem-se sempre juntos e validados)."""

    async def ensaio(base):
        lojas = base[COLECOES["lojas"]]
        with pytest.raises(WriteError) as recusa:
            await lojas.insert_one({"id": _id(1), "loc": {"type": "Point", "coordinates": [200, 100]}})
        return recusa.value, await lojas.count_documents({})

    recusa, guardadas = no_mongo(ensaio)

    assert not isinstance(recusa, DuplicateKeyError)
    assert guardadas == 0


# --- O bloqueio otimista -----------------------------------------------------------------------------


def test_a_atualizacao_condicional_com_o_atualizado_em_antigo_nao_apanha_nada(no_mongo):
    """Com a versão certa grava (matched 1); com a versão que já passou,
    `matched_count 0` e nada muda. O carimbo seguinte é maior também como
    texto (`$gt`), e o filtro vai pelo índice `id_1`."""
    # Com o relógio atrasado (08:00), o seguinte é o anterior + 1 µs.
    seguinte = relogio.proximo_carimbo(datetime(2026, 10, 10, 8, tzinfo=timezone.utc), V1)
    assert seguinte == V2

    async def ensaio(base):
        lojas = base[COLECOES["lojas"]]
        await lojas.insert_one({**_loja(1, LAT), "telefone": "", "atualizado_em": V1})
        certa = await lojas.update_one(
            {"id": _id(1), "atualizado_em": V1}, {"$set": {"telefone": "213 456 789", "atualizado_em": V2}}
        )
        velha = await lojas.update_one(
            {"id": _id(1), "atualizado_em": V1}, {"$set": {"telefone": "912 345 678", "atualizado_em": V2}}
        )
        guardada = await lojas.find_one({"id": _id(1)}, {"_id": 0, "telefone": 1, "atualizado_em": 1})
        maiores = await lojas.count_documents({"atualizado_em": {"$gt": V1}})
        plano = _plano(await lojas.find({"id": _id(1), "atualizado_em": V2}).explain())
        return certa, velha, guardada, maiores, plano

    certa, velha, guardada, maiores, plano = no_mongo(ensaio)

    assert (certa.matched_count, certa.modified_count) == (1, 1)
    assert (velha.matched_count, velha.modified_count) == (0, 0)
    assert guardada == {"telefone": "213 456 789", "atualizado_em": V2}
    assert maiores == 1
    assert "id_1" in plano


def test_duas_alteracoes_da_mesma_loja_ao_mesmo_tempo_so_uma_grava(no_mongo, monkeypatch):
    """A corrida a sério com o Motor: as duas leem a mesma versão (a barreira
    garante que ambas leem antes de qualquer uma escrever); o `update_one`
    condicional deixa gravar só uma (200), a outra dá 409 `conflito`, e só a
    que gravou fica no histórico."""

    async def ensaio(base):
        loja = await criar_loja(RUI_MEMBRO, _corpo_loja("Café Central"))
        _em_corrida(monkeypatch, base, "lojas")
        respostas = await asyncio.gather(
            alterar_loja(loja["id"], RUI_MEMBRO, {"fase": "cliente", "atualizado_em": loja["atualizado_em"]}),
            alterar_loja(loja["id"], ANA_MEMBRO, {"fase": "perdida", "atualizado_em": loja["atualizado_em"]}),
            return_exceptions=True,
        )
        guardada = await base[COLECOES["lojas"]].find_one({"id": loja["id"]}, {"_id": 0})
        historico = await base[COLECOES["interacoes"]].find({"loja_id": loja["id"]}, {"_id": 0}).to_list(10)
        return loja, respostas, guardada, historico

    loja, respostas, guardada, historico = no_mongo(ensaio)

    gravaram, recusadas = _separar(respostas)
    assert len(gravaram) == 1 and len(recusadas) == 1
    assert (recusadas[0].status_code, recusadas[0].detail) == (409, _erro("conflito", MENSAGEM_CONFLITO))
    venceu = gravaram[0]
    assert (guardada["fase"], guardada["atualizado_em"]) == (venceu["fase"], venceu["atualizado_em"])
    assert guardada["atualizado_em"] > loja["atualizado_em"]
    assert [i["resultado"] for i in historico] == [f"potencial→{venceu['fase']}"]
    assert instantes_fora_do_formato(guardada) == []
    assert instantes_fora_do_formato(historico) == []


# --- Índices únicos ----------------------------------------------------------------------------------


def test_nome_chave_repetido_da_duplicate_key_error(no_mongo):
    async def ensaio(base):
        regioes = base[COLECOES["regioes"]]
        await regioes.insert_one({"id": _id(1), "nome": "Setúbal", "nome_chave": "setubal", "ordem": 0})
        with pytest.raises(DuplicateKeyError):
            await regioes.insert_one({"id": _id(2), "nome": "setubal", "nome_chave": "setubal", "ordem": 1})
        return await regioes.count_documents({})

    assert no_mongo(ensaio) == 1


def test_user_id_repetido_da_duplicate_key_error(no_mongo):
    async def ensaio(base):
        membros = base[COLECOES["membros"]]
        await membros.insert_one({"id": _id(1), "user_id": "u-bea", "perfil": "utilizador"})
        with pytest.raises(DuplicateKeyError):
            await membros.insert_one({"id": _id(2), "user_id": "u-bea", "perfil": "motorista"})
        return await membros.count_documents({})

    assert no_mongo(ensaio) == 1


# Os outros campos únicos de cada coleção, diferentes nos dois documentos
# (em falta contavam como null e colidiam por eles, não pelo `id`).
_OUTROS_UNICOS = {"membros": "user_id", "regioes": "nome_chave", "lojas": None, "interacoes": None}


@pytest.mark.parametrize("coleccao", sorted(_OUTROS_UNICOS))
def test_id_repetido_da_duplicate_key_error(no_mongo, coleccao):
    outro = _OUTROS_UNICOS[coleccao]

    def _documento(n):
        return {"id": _id(1), **({outro: f"valor-{n}"} if outro else {})}

    async def ensaio(base):
        documentos = base[COLECOES[coleccao]]
        await documentos.insert_one(_documento(1))
        with pytest.raises(DuplicateKeyError):
            await documentos.insert_one(_documento(2))
        return await documentos.count_documents({})

    assert no_mongo(ensaio) == 1


def test_duas_interacoes_sem_client_uuid_nao_colidem_no_indice_parcial(no_mongo):
    """Todas as interações da F2 vêm sem `client_uuid`: o índice único é
    parcial (só quando é texto), por isso nem a falta nem o null colidem."""

    async def ensaio(base):
        interacoes = base[COLECOES["interacoes"]]
        sem_campo = {"loja_id": _id(9), "tipo": MUDANCA_FASE}
        com_null = {"loja_id": _id(9), "tipo": "nota", "client_uuid": None}
        for n, forma in ((1, sem_campo), (2, sem_campo), (3, com_null), (4, com_null)):
            await interacoes.insert_one({"id": _id(n), **forma, "ocorrida_em": f"2026-10-10T{8 + n:02d}:00:00Z"})
        return await interacoes.count_documents({})

    assert no_mongo(ensaio) == 4


def test_o_mesmo_client_uuid_de_texto_da_duplicate_key_error(no_mongo):
    """O outro lado do índice parcial: com texto é mesmo único (o registo sem
    rede da F4 repetido é o mesmo registo)."""

    async def ensaio(base):
        interacoes = base[COLECOES["interacoes"]]
        await interacoes.insert_one({"id": _id(1), "loja_id": _id(9), "tipo": "visita", "client_uuid": "c-1"})
        with pytest.raises(DuplicateKeyError):
            await interacoes.insert_one({"id": _id(2), "loja_id": _id(9), "tipo": "visita", "client_uuid": "c-1"})
        return await interacoes.count_documents({})

    assert no_mongo(ensaio) == 1


def test_a_linha_do_tempo_e_o_historico_usam_o_indice_loja_id_ocorrida_em(no_mongo):
    """A procura do histórico do DELETE (`tipo` `$ne` `mudanca_fase`) e a linha
    do tempo por `ocorrida_em` (texto de largura fixa, que ordena como o
    tempo) vão pelo `loja_id_1_ocorrida_em_1`."""

    async def ensaio(base):
        interacoes = base[COLECOES["interacoes"]]
        for n, hora in ((1, "09"), (2, "11"), (3, "10")):
            await interacoes.insert_one(
                {"id": _id(n), "loja_id": _id(9), "tipo": MUDANCA_FASE, "ocorrida_em": f"2026-10-10T{hora}:00:00Z"}
            )
        historico = _plano(await interacoes.find({"loja_id": _id(9), "tipo": {"$ne": MUDANCA_FASE}}).explain())
        linha = interacoes.find({"loja_id": _id(9)}, {"_id": 0, "id": 1}).sort("ocorrida_em", 1)
        ordem = [i["id"] for i in await linha.to_list(10)]
        plano_linha = _plano(await interacoes.find({"loja_id": _id(9)}).sort("ocorrida_em", 1).explain())
        return historico, ordem, plano_linha

    historico, ordem, plano_linha = no_mongo(ensaio)

    assert "loja_id_1_ocorrida_em_1" in historico
    assert ordem == [_id(1), _id(3), _id(2)]
    assert "loja_id_1_ocorrida_em_1" in plano_linha


# --- Corridas com o Motor nas rotas que dependem dos índices ---------------------------------------


def test_duas_regioes_com_o_mesmo_nome_ao_mesmo_tempo_so_uma_fica(no_mongo, monkeypatch):
    """"Setúbal" e "setubal" ao mesmo tempo, as duas verificações feitas antes
    de qualquer gravação: só o índice único `nome_chave` trava a segunda,
    que dá 409 `regiao_repetida`."""

    async def ensaio(base):
        _em_corrida(monkeypatch, base, "regioes")
        respostas = await asyncio.gather(
            criar_regiao(ANA_MEMBRO, {"nome": "Setúbal"}),
            criar_regiao(ANA_MEMBRO, {"nome": "setubal"}),
            return_exceptions=True,
        )
        return respostas, await base[COLECOES["regioes"]].find({}, {"_id": 0}).to_list(10)

    respostas, guardadas = no_mongo(ensaio)

    criadas, recusadas = _separar(respostas)
    assert len(criadas) == 1 and len(recusadas) == 1
    assert (recusadas[0].status_code, recusadas[0].detail) == (409, _erro("regiao_repetida", MENSAGEM_REPETIDA))
    assert [(g["id"], g["nome_chave"]) for g in guardadas] == [(criadas[0]["id"], "setubal")]


def test_dois_patch_a_campos_diferentes_da_mesma_regiao_respondem_com_o_que_ficou_gravado(no_mongo, monkeypatch):
    """Revisão da F2: os dois pedidos leem a região antes de qualquer escrita
    (a barreira); um muda a ordem e o outro o nome. Ficam as duas mudanças, e
    o último a gravar responde com a região igual ao `GET` seguinte (antes,
    cada um respondia com o que leu mais o que pediu, e nenhum a trazia)."""
    porto = _id(2)

    async def ensaio(base):
        await base[COLECOES["regioes"]].insert_one({"id": porto, "nome": "Porto", "nome_chave": "porto", "ordem": 2})
        _em_corrida(monkeypatch, base, "regioes")
        respostas = await asyncio.gather(
            alterar_regiao(porto, ANA_MEMBRO, {"ordem": 0}),
            alterar_regiao(porto, ANA_MEMBRO, {"nome": "Norte"}),
            return_exceptions=True,
        )
        monkeypatch.setattr(bd, "obter_db", lambda: base)
        return respostas, await listar_regioes(RUI_MEMBRO), await base[COLECOES["regioes"]].find({}, {"_id": 0}).to_list(10)

    respostas, lista, guardadas = no_mongo(ensaio)

    gravadas, recusadas = _separar(respostas)
    assert recusadas == []
    assert guardadas == [{"id": porto, "nome": "Norte", "nome_chave": "norte", "ordem": 0}]
    assert lista == [{"id": porto, "nome": "Norte", "ordem": 0}]
    da_ordem, do_nome = gravadas
    assert da_ordem["ordem"] == 0 and do_nome["nome"] == "Norte", "cada uma traz a sua mudança"
    assert lista[0] in (da_ordem, do_nome), "a do último a gravar é igual ao GET seguinte"


def test_a_mesma_conta_adicionada_duas_vezes_ao_mesmo_tempo_fica_uma_vez(no_mongo, monkeypatch):
    """As duas verificações feitas antes de qualquer gravação: só o índice
    único `user_id` trava a segunda, que dá 409 `ja_membro`."""

    async def ensaio(base):
        await base.users.insert_one(dict(CONTA_DA_BEA))
        _em_corrida(monkeypatch, base, "membros")
        respostas = await asyncio.gather(
            adicionar_membro(ANA_MEMBRO, {"user_id": "u-bea", "perfil": "utilizador"}),
            adicionar_membro(ANA_MEMBRO, {"user_id": "u-bea", "perfil": "motorista"}),
            return_exceptions=True,
        )
        return respostas, await base[COLECOES["membros"]].find({}, {"_id": 0}).to_list(10)

    respostas, guardados = no_mongo(ensaio)

    adicionados, recusados = _separar(respostas)
    assert len(adicionados) == 1 and len(recusados) == 1
    assert (recusados[0].status_code, recusados[0].detail) == (409, _erro("ja_membro", MENSAGEM_JA_MEMBRO))
    assert [(g["id"], g["user_id"]) for g in guardados] == [(adicionados[0]["id"], "u-bea")]
    assert instantes_fora_do_formato(guardados) == []


def test_dois_apagamentos_da_mesma_loja_ao_mesmo_tempo(no_mongo, monkeypatch):
    """Os dois encontram a loja antes de qualquer um apagar; um apaga (200)
    e o outro dá 404 (`deleted_count 0`); não fica nada da loja, nem as mudanças
    de fase dela."""

    async def ensaio(base):
        loja = await criar_loja(RUI_MEMBRO, _corpo_loja("Quiosque"))
        await alterar_loja(loja["id"], RUI_MEMBRO, {"fase": "contactada", "atualizado_em": loja["atualizado_em"]})
        _em_corrida(monkeypatch, base, "lojas")
        respostas = await asyncio.gather(
            apagar_loja(loja["id"], RUI_MEMBRO), apagar_loja(loja["id"], ANA_MEMBRO), return_exceptions=True
        )
        lojas = await base[COLECOES["lojas"]].count_documents({})
        interacoes = await base[COLECOES["interacoes"]].count_documents({})
        return respostas, lojas, interacoes

    respostas, lojas, interacoes = no_mongo(ensaio)

    apagadas, recusadas = _separar(respostas)
    assert apagadas == [{"apagada": True}]
    assert (recusadas[0].status_code, recusadas[0].detail) == (404, _erro("nao_encontrado", MENSAGEM_NAO_ENCONTRADA))
    assert (lojas, interacoes) == (0, 0)


# --- Definições: upserts pela chave ----------------------------------------------------------------


def test_dois_upserts_seguidos_das_definicoes_nao_dao_duplicate_key_error(no_mongo):
    """Correções do plano, linha "T1.2 (test_indices) / T2.8": a latitude e a
    longitude gravam-se uma a seguir à outra, e os documentos não têm `id`.
    Com um índice único em `id`, o segundo upsert dava E11000 (os dois `id`
    em falta contam como null)."""

    async def ensaio(base):
        definicoes = base[COLECOES["definicoes"]]
        for chave, valor in (("fabrica_lat", "41.149600"), ("fabrica_lng", "-8.611000")):
            await definicoes.update_one(
                {"chave": chave},
                {"$set": {"valor": valor, "atualizado_em": V1, "atualizado_por": "u-ana"}},
                upsert=True,
            )
        return await definicoes.find({}, {"_id": 0}).sort("chave", 1).to_list(10)

    assert no_mongo(ensaio) == [
        {"chave": "fabrica_lat", "valor": "41.149600", "atualizado_em": V1, "atualizado_por": "u-ana"},
        {"chave": "fabrica_lng", "valor": "-8.611000", "atualizado_em": V1, "atualizado_por": "u-ana"},
    ]


def test_o_patch_das_definicoes_grava_uma_linha_por_chave_e_o_seguinte_substitui(no_mongo):
    async def ensaio(base):
        primeira = await alterar_definicoes(
            ANA_MEMBRO, {"fabrica_morada": "Rua das Flores 1, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}
        )
        segunda = await alterar_definicoes(ANA_MEMBRO, {"fabrica_lat": 37.16, "fabrica_lng": -8.12})
        guardadas = await base[COLECOES["definicoes"]].find({}, {"_id": 0}).sort("chave", 1).to_list(10)
        return primeira, segunda, guardadas

    primeira, segunda, guardadas = no_mongo(ensaio)

    # As 6 chaves das rotas (F3, T3.5) vêm sempre, com os padrões e os minutos como inteiros.
    rotas = {
        "rota_hora_saida": "08:00", "rota_hora_regresso": "19:00", "servico_entrega_min": 10,
        "servico_amostra_min": 10, "servico_acompanhamento_min": 15, "servico_angariacao_min": 15,
    }
    assert primeira == {
        "fabrica_morada": "Rua das Flores 1, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611, **rotas,
    }
    assert segunda == {"fabrica_morada": "Rua das Flores 1, Porto", "fabrica_lat": 37.16, "fabrica_lng": -8.12, **rotas}
    assert [(g["chave"], g["valor"]) for g in guardadas] == [
        ("fabrica_lat", "37.160000"),
        ("fabrica_lng", "-8.120000"),
        ("fabrica_morada", "Rua das Flores 1, Porto"),
    ]
    assert all("id" not in g and g["atualizado_por"] == "u-ana" for g in guardadas)
    assert instantes_fora_do_formato(guardadas) == []


def test_muitos_patch_das_definicoes_ao_mesmo_tempo_deixam_uma_linha_por_chave(no_mongo):
    """20 pedidos ao mesmo tempo com a coleção vazia: o Mongo refaz o upsert
    que perde a corrida pelo `chave_1` em vez de dar DuplicateKeyError, e
    cada coordenada fica com o valor de um dos pedidos."""
    pedidos = [{"fabrica_lat": round(37.0 + n / 100, 2), "fabrica_lng": round(-8.0 - n / 100, 2)} for n in range(20)]

    async def ensaio(base):
        respostas = await asyncio.gather(
            *(alterar_definicoes(ANA_MEMBRO, pedido) for pedido in pedidos), return_exceptions=True
        )
        guardadas = await base[COLECOES["definicoes"]].find({}, {"_id": 0, "chave": 1, "valor": 1}).to_list(100)
        return respostas, guardadas

    respostas, guardadas = no_mongo(ensaio)

    assert [r for r in respostas if isinstance(r, BaseException)] == []
    assert sorted(g["chave"] for g in guardadas) == ["fabrica_lat", "fabrica_lng"]
    valores = {g["chave"]: float(g["valor"]) for g in guardadas}
    assert valores["fabrica_lat"] in {p["fabrica_lat"] for p in pedidos}
    assert valores["fabrica_lng"] in {p["fabrica_lng"] for p in pedidos}


# --- O seed das regiões e lojas de demonstração (T2.18) ---------------------------------------------

AGORA_DO_SEED = datetime(2026, 10, 10, 9, 0, 0, 123456, tzinfo=timezone.utc)
CRIADAS = "Criadas: 4 regiões e 24 lojas de demonstração."
SEED_NADA_MUDOU = (
    "Erro: os dados de demonstração não foram criados (nada mudou): BulkWriteError: Document failed validation"
)
# Um validador do Mongo que só recusa as lojas de demonstração (faz o papel do
# gatilho "falha simulada" do SeedDemoTest do autónomo): a loja verdadeira, ao
# ser reposta, passa.
SO_RECUSA_AS_DE_DEMONSTRACAO = {"nome": {"$not": {"$regex": r" \(demo\)$"}}}


def _seed_na_base(uri):
    """O seed usa o pymongo (síncrono): um cliente à parte, na mesma base de teste."""
    return MongoClient(
        uri, directConnection=True, serverSelectionTimeoutMS=ESPERA_MS, connectTimeoutMS=ESPERA_MS
    )


async def _tudo(base, *coleccoes):
    """Tudo o que está nas coleções, com o `_id`, por ordem de gravação."""
    return {c: await base[c].find({}).sort("_id", 1).to_list(1000) for c in coleccoes}


def test_o_seed_grava_as_lojas_de_demonstracao_e_as_rotas_leem_nas(no_mongo):
    """Na base verdadeira, com os índices do `criar_indices`: as 24 lojas passam
    o `2dsphere` (nenhuma a menos de 210 m de outra pelo pré-filtro), as 4
    regiões têm `nome_chave` (o índice único trava "lisboa"), as rotas leem
    tudo; a segunda vez sem --repor recusa, e com --repor não colide."""
    lojas_c, regioes_c = COLECOES["lojas"], COLECOES["regioes"]

    async def ensaio(base):
        cliente = _seed_na_base(no_mongo.uri)
        try:
            sincrona = cliente[BASE_TESTE]
            linhas = seed_crm_local.aplicar_lojas(sincrona, AGORA_DO_SEED)
            with pytest.raises(SystemExit) as recusa:
                seed_crm_local.aplicar_lojas(sincrona, AGORA_DO_SEED)
            resumos = await listar_lojas(RUI_MEMBRO)
            completas = [await ler_loja(resumo["id"], RUI_MEMBRO) for resumo in resumos]
            regioes = await listar_regioes(RUI_MEMBRO)
            vizinhas = [
                await base[lojas_c]
                .find(filtro_candidatos(r["lat"], r["lng"], r["id"], raio=200), PROJECAO_CANDIDATO)
                .to_list(30)
                for r in resumos
            ]
            with pytest.raises(HTTPException) as repetida:
                await criar_regiao(ANA_MEMBRO, {"nome": "lisboa"})
            linhas_repor = seed_crm_local.aplicar_lojas(sincrona, AGORA_DO_SEED, repor=True)
            contagens = (await base[lojas_c].count_documents({}), await base[regioes_c].count_documents({}))
        finally:
            cliente.close()
        return linhas, recusa.value.code, resumos, completas, regioes, vizinhas, repetida.value, linhas_repor, contagens

    linhas, recusa, resumos, completas, regioes, vizinhas, repetida, linhas_repor, contagens = no_mongo(ensaio)

    assert linhas == [CRIADAS]
    assert recusa.startswith("Recusado: a base de dados já tem 24 lojas e 4 regiões.")
    assert len(resumos) == 24
    assert [r["nome"] for r in resumos] == sorted((r["nome"] for r in resumos), key=chave_comparacao)
    assert all(r["nome"].endswith(" (demo)") for r in resumos)
    assert [(r["nome"], r["ordem"]) for r in regioes] == [("Lisboa", 1), ("Porto", 2), ("Setúbal", 3), ("Algarve", 4)]
    assert sum(1 for c in completas if c["regiao_id"] is None) == 2
    assert {c["regiao_id"] for c in completas} - {None} == {r["id"] for r in regioes}
    assert all(c["criado_por"] == "seed-local" and c["criado_em"] == c["fase_desde"] for c in completas)
    assert len({c["fase_desde"] for c in completas}) > 5
    assert instantes_fora_do_formato(completas) == []
    assert vizinhas == [[]] * 24
    assert (repetida.status_code, repetida.detail) == (409, _erro("regiao_repetida", MENSAGEM_REPETIDA))
    assert linhas_repor == ["Apagadas: 24 lojas e 4 regiões.", CRIADAS]
    assert contagens == (24, 4)


def test_se_o_mongo_recusar_uma_loja_do_seed_nada_muda(no_mongo):
    async def ensaio(base):
        await base.command("collMod", COLECOES["lojas"], validator=SO_RECUSA_AS_DE_DEMONSTRACAO)
        cliente = _seed_na_base(no_mongo.uri)
        try:
            with pytest.raises(SystemExit) as erro:
                seed_crm_local.aplicar_lojas(cliente[BASE_TESTE], AGORA_DO_SEED)
        finally:
            cliente.close()
        return erro.value.code, await _tudo(base, COLECOES["lojas"], COLECOES["regioes"])

    erro, depois = no_mongo(ensaio)

    assert erro == SEED_NADA_MUDOU
    assert depois == {COLECOES["lojas"]: [], COLECOES["regioes"]: []}, "As regiões também voltam atrás."


def test_se_o_repor_do_seed_falhar_no_mongo_fica_tudo_como_estava(no_mongo):
    """Com uma loja, uma região e uma interação verdadeiras: o --repor apaga-as,
    grava as regiões, o Mongo recusa a primeira loja de demonstração e o seed
    repõe tudo como estava (os mesmos documentos, com o mesmo `_id`)."""
    coleccoes = (COLECOES["lojas"], COLECOES["regioes"], COLECOES["interacoes"])

    async def ensaio(base):
        await base[COLECOES["regioes"]].insert_one({"id": _id(9), "nome": "Minho", "nome_chave": "minho", "ordem": 0})
        await base[COLECOES["lojas"]].insert_one({**_loja(1, LAT), "regiao_id": _id(9)})
        await base[COLECOES["interacoes"]].insert_one(
            {"id": _id(2), "loja_id": _id(1), "tipo": MUDANCA_FASE, "ocorrida_em": "2026-10-10T09:00:00Z"}
        )
        antes = await _tudo(base, *coleccoes)
        await base.command("collMod", COLECOES["lojas"], validator=SO_RECUSA_AS_DE_DEMONSTRACAO)
        cliente = _seed_na_base(no_mongo.uri)
        try:
            with pytest.raises(SystemExit) as erro:
                seed_crm_local.aplicar_lojas(cliente[BASE_TESTE], AGORA_DO_SEED, repor=True)
        finally:
            cliente.close()
        return erro.value.code, antes, await _tudo(base, *coleccoes)

    erro, antes, depois = no_mongo(ensaio)

    assert erro == SEED_NADA_MUDOU
    assert [len(antes[c]) for c in coleccoes] == [1, 1, 1]
    assert depois == antes


# --- F3: as rotas em crm_rotas (T3.25) ----------------------------------------------------------------
#
# As escritas do escritório (`rotas_bd`, T3.17) e as rotas HTTP (T3.19/T3.20)
# estão provadas sobre o duplo; aqui repete-se no Mongo verdadeiro o que o
# duplo só modela: os índices, o `$nin` através da lista no filtro de guarda,
# o erro 40 dos caminhos em conflito, a ordem das datas em texto e as
# corridas com o Motor. As rotas gravadas à mão seguem a forma do
# `documento_rota`/`documento_paragem`; as das corridas nascem pelas rotas
# HTTP, com o relógio verdadeiro (o dia é sempre amanhã em Lisboa).

INDICES_DAS_ROTAS = ["_id_", "data_1", "id_1", "paragens.loja_id_1"]
GUARDA_DO_TERRENO = {"paragens.estado": {"$nin": ["feita", "nao_feita"]}}
DEFINICOES_DAS_ROTAS = {"rota_hora_saida": "08:00", "rota_hora_regresso": "19:00"}
AGORA_DAS_ROTAS = datetime(2026, 10, 10, 9, 0, 0, 123456, tzinfo=timezone.utc)
AGORA_DEPOIS = datetime(2026, 10, 10, 9, 30, 0, 0, tzinfo=timezone.utc)
RETIRADA_EM = "2026-10-10T10:00:00Z"
# O registo do motorista (F4) numa paragem: só os campos do terreno.
REGISTO_FEITA = {"estado": "feita", "resultado": "interessado", "concluida_em": "2026-10-11T10:00:00Z"}
CALCULO_GRAVADO = {
    "assinatura": "sha256:" + "0" * 64, "distancia_m": 1234, "duracao_s": 567, "regresso_previsto": "09:30",
    "depois_do_limite": False, "geometria": "_p~iF~ps|U", "calculado_em": "2026-10-11T10:00:00Z",
}


def _dia(n=1):
    """Hoje em Lisboa mais `n` dias, em texto: as rotas HTTP leem o relógio verdadeiro."""
    return texto_data(somar_dias(relogio.hoje(), n))


def _loja_para_a_rota(n, lat, fase="potencial"):
    """Uma loja gravada à mão, com o que a `PROJECAO_LOJA_ROTA` lê (pela rota
    HTTP, as lojas de um mesmo ensaio ficavam a menos de 50 m umas das outras)."""
    return {**_loja(n, lat), "fase": fase, "telefone": "", "janelas": [], "dias_fechada": []}


def _rota_na_base(data, *lojas_ids, id_, versao=1):
    """Uma rota como o `documento_rota` a grava, com uma paragem ativa por loja
    (ordens 0..n−1), pronta para o `insert_one`."""
    rota = documento_rota(ler_data(data), RUI_MEMBRO["user_id"], AGORA_DAS_ROTAS, DEFINICOES_DAS_ROTAS)
    rota["id"] = id_
    rota["versao"] = versao
    rota["paragens"] = [
        documento_paragem({"id": loja_id}, "angariacao", 15, ordem, RUI_MEMBRO["user_id"], AGORA_DAS_ROTAS)
        for ordem, loja_id in enumerate(lojas_ids)
    ]
    return rota


def _retirar(paragem):
    paragem.update({"removida_em": RETIRADA_EM, "ordem": None})


def test_crm_rotas_fica_com_exatamente_os_quatro_indices(no_mongo):
    """O `criar_indices` verdadeiro: `_id_`, `id_1` e `data_1` únicos e
    `paragens.loja_id_1` sem ser único (uma entrada por paragem)."""

    async def ensaio(base):
        informacao = await base[COLECOES["rotas"]].index_information()
        return sorted(informacao), {nome: bool(indice.get("unique")) for nome, indice in informacao.items()}

    nomes, unicos = no_mongo(ensaio)

    assert nomes == INDICES_DAS_ROTAS
    assert unicos == {"_id_": False, "id_1": True, "data_1": True, "paragens.loja_id_1": False}


def test_a_mesma_data_duas_vezes_da_duplicate_key_error(no_mongo):
    """Uma rota por dia: a segunda `insert_one` com a mesma `data` é
    `DuplicateKeyError` pelo `data_1` (`rotas_bd.criar` → False, nada
    gravado); outro dia grava, mesmo com a mesma loja numa paragem (o
    `paragens.loja_id` não é único)."""

    async def ensaio(base):
        rotas = base[COLECOES["rotas"]]
        await rotas.insert_one(_rota_na_base("2026-10-12", _id(1), id_=_id(21)))
        with pytest.raises(DuplicateKeyError) as repetida:
            await rotas.insert_one(_rota_na_base("2026-10-12", _id(2), id_=_id(22)))
        criada = await rotas_bd.criar(base, _rota_na_base("2026-10-12", _id(3), id_=_id(23)))
        outro_dia = await rotas_bd.criar(base, _rota_na_base("2026-10-13", _id(1), id_=_id(24)))
        gravadas = await rotas.find({}, {"_id": 0, "id": 1, "data": 1}).sort("data", 1).to_list(10)
        return repetida.value, criada, outro_dia, gravadas

    repetida, criada, outro_dia, gravadas = no_mongo(ensaio)

    assert repetida.details["keyPattern"] == {"data": 1}
    assert (criada, outro_dia) == (False, True)
    assert gravadas == [{"id": _id(21), "data": "2026-10-12"}, {"id": _id(24), "data": "2026-10-13"}]


def test_esta_loja_esta_numa_rota_vai_pelo_indice_paragens_loja_id(no_mongo):
    """`rotas_com_loja` (o `DELETE /lojas/{id}`): o filtro `{"paragens.loja_id"}`
    usa o índice multikey, encontra a loja em qualquer posição da lista
    (também retirada) e vem por `data`, sem o `calculo` nem o `_id`."""

    async def ensaio(base):
        rotas = base[COLECOES["rotas"]]
        primeira = _rota_na_base("2026-10-12", _id(1), _id(2), id_=_id(21))  # a 2 em segundo
        sem_a_loja = _rota_na_base("2026-10-13", _id(3), id_=_id(22))
        depois = _rota_na_base("2026-10-14", _id(2), _id(3), id_=_id(23))  # a 2 em primeiro, retirada
        _retirar(depois["paragens"][0])
        depois["calculo"] = dict(CALCULO_GRAVADO)
        await rotas.insert_many([primeira, sem_a_loja, depois])
        plano = _plano(await rotas.find({"paragens.loja_id": _id(2)}).explain())
        com_a_loja = await rotas_bd.rotas_com_loja(base, _id(2))
        return plano, com_a_loja

    plano, com_a_loja = no_mongo(ensaio)

    assert "paragens.loja_id_1" in plano
    assert "'isMultiKey': True" in plano
    assert [r["id"] for r in com_a_loja] == [_id(21), _id(23)]
    assert all("calculo" not in r and "_id" not in r for r in com_a_loja)


def test_push_e_inc_condicionais_na_rota_verdadeira(no_mongo):
    """`acrescentar_paragem`: `$push` + `$inc` + `$set` de topo numa só
    `find_one_and_update`. Com a versão lida grava (versão 2, a paragem no
    fim, o autor e o carimbo novos); com a versão que já passou não casa e
    nada muda (`porque_falhou` → conflito)."""

    async def ensaio(base):
        rotas = base[COLECOES["rotas"]]
        lida = _rota_na_base("2026-10-12", _id(1), id_=_id(21))
        await rotas.insert_one(dict(lida))
        nova = documento_paragem({"id": _id(2)}, "amostra", 10, 1, "u-ana", AGORA_DEPOIS)
        outra = documento_paragem({"id": _id(3)}, "entrega", 10, 1, "u-ana", AGORA_DEPOIS)
        depois = await rotas_bd.acrescentar_paragem(base, lida, nova, membro_id="u-ana", agora=AGORA_DEPOIS)
        velha = await rotas_bd.acrescentar_paragem(base, lida, outra, membro_id="u-ana", agora=AGORA_DEPOIS)
        motivo = await rotas_bd.porque_falhou(base, lida["id"], lida["versao"])
        gravada = await rotas.find_one({"id": lida["id"]}, {"_id": 0})
        return lida, depois, velha, motivo, gravada

    lida, depois, velha, motivo, gravada = no_mongo(ensaio)

    assert (velha, motivo) == (None, "conflito")
    assert gravada == depois
    assert depois["versao"] == 2
    assert [(p["loja_id"], p["ordem"], p["motivo"]) for p in depois["paragens"]] == [
        (_id(1), 0, "angariacao"), (_id(2), 1, "amostra"),
    ]
    assert depois["atualizado_em"] > lida["atualizado_em"]
    assert depois["atualizado_por"] == "u-ana"
    assert instantes_fora_do_formato(gravada) == []
    assert escritas_no_terreno(gravada) == []


def test_o_set_por_indice_com_a_guarda_casa_antes_e_nao_depois_do_registo_do_motorista(no_mongo):
    """`alterar`: `$set paragens.N.ordem` + `$inc` com o filtro de guarda.
    Antes casa (a ordem trocada, versão 2); depois de o motorista pôr
    `paragens.1.estado: "feita"` (só os campos do terreno, a versão igual), o
    `$nin` através da lista deixa de casar — nada se escreve, `porque_falhou`
    diz `em_curso`, a rota lê-se só de leitura e o `PATCH` dá 409
    `rota_em_curso` (o molde do `test_rotas_terreno.py`)."""

    async def ensaio(base):
        rotas = base[COLECOES["rotas"]]
        amanha = _dia(1)
        await base[COLECOES["lojas"]].insert_many([_loja_para_a_rota(1, LAT), _loja_para_a_rota(2, A_80_M)])
        lida = _rota_na_base(amanha, _id(1), _id(2), id_=_id(21))
        await rotas.insert_one(dict(lida))
        guarda = {"id": lida["id"], "versao": 1, "estado": {"$in": ["rascunho", "planeada"]}, **GUARDA_DO_TERRENO}
        casa_antes = await rotas.count_documents(guarda)
        trocada = await rotas_bd.alterar(
            base, lida, {"paragens.0.ordem": 1, "paragens.1.ordem": 0}, membro_id="u-ana", agora=AGORA_DEPOIS
        )
        registo = await rotas.update_one(
            {"id": lida["id"]}, {"$set": {f"paragens.1.{campo}": valor for campo, valor in REGISTO_FEITA.items()}}
        )
        casa_depois = await rotas.count_documents({**guarda, "versao": 2})
        recusada = await rotas_bd.alterar(
            base, trocada, {"paragens.0.ordem": 0, "paragens.1.ordem": 1}, membro_id="u-ana", agora=AGORA_DEPOIS
        )
        motivo = await rotas_bd.porque_falhou(base, lida["id"], trocada["versao"])
        leitura = await rotas_http.ver_rota(amanha, membro=RUI_MEMBRO)
        with pytest.raises(HTTPException) as em_curso:
            await rotas_http.alterar_rota(amanha, membro=RUI_MEMBRO, corpo={"versao": 2, "evitar_portagens": True})
        gravada = await rotas.find_one({"id": lida["id"]}, {"_id": 0})
        return casa_antes, trocada, registo.modified_count, casa_depois, recusada, motivo, leitura, em_curso.value, gravada

    casa_antes, trocada, registo, casa_depois, recusada, motivo, leitura, em_curso, gravada = no_mongo(ensaio)

    assert casa_antes == 1
    assert trocada["versao"] == 2
    assert [(p["loja_id"], p["ordem"]) for p in trocada["paragens"]] == [(_id(1), 1), (_id(2), 0)]
    assert registo == 1
    assert casa_depois == 0
    assert (recusada, motivo) == (None, "em_curso")
    assert (leitura["editavel"], leitura["versao"]) == (False, 2)
    assert (em_curso.status_code, em_curso.detail) == (409, _erro("rota_em_curso", MENSAGEM_ROTA_EM_CURSO))
    assert gravada["versao"] == 2 and gravada["evitar_portagens"] is False
    assert [(p["ordem"], p["estado"]) for p in gravada["paragens"]] == [(1, "pendente"), (0, "feita")]
    assert {campo: gravada["paragens"][1][campo] for campo in REGISTO_FEITA} == REGISTO_FEITA
    assert instantes_fora_do_formato(gravada) == []


def test_o_calculo_lido_no_filtro_de_guarda_casa_antes_e_nao_depois_de_um_recalculo(no_mongo):
    """Correção "F3-INT-1", no Mongo verdadeiro: `calculo: None` no filtro
    casa com o `calculo` nulo gravado; um recálculo sem subir a versão
    (`alterar(..., subir_versao=False)`) faz falhar as escritas lidas antes —
    a que sobe a versão e o `$push` — sem escrever, `porque_falhou` diz
    `conflito`, e a rota relida (com `calculo.assinatura` e
    `calculo.calculado_em` no filtro) grava."""

    async def ensaio(base):
        rotas = base[COLECOES["rotas"]]
        lida = _rota_na_base("2026-10-12", _id(1), _id(2), id_=_id(21))
        await rotas.insert_one(dict(lida))
        recalculo = {"paragens.0.chegada_prevista": "08:10", "paragens.0.espera_min": 0, "calculo": dict(CALCULO_GRAVADO)}
        recalculada = await rotas_bd.alterar(
            base, lida, recalculo, subir_versao=False, membro_id="u-ana", agora=AGORA_DEPOIS
        )
        velha = await rotas_bd.alterar(base, lida, {"evitar_portagens": True}, membro_id="u-ana", agora=AGORA_DEPOIS)
        nova = documento_paragem({"id": _id(3)}, "entrega", 10, 2, "u-ana", AGORA_DEPOIS)
        velho_push = await rotas_bd.acrescentar_paragem(base, lida, nova, membro_id="u-ana", agora=AGORA_DEPOIS)
        intacta = await rotas.find_one({"id": lida["id"]}, {"_id": 0})
        motivo = await rotas_bd.porque_falhou(base, lida["id"], lida["versao"])
        relida = await rotas_bd.alterar(
            base, recalculada, {"evitar_portagens": True}, membro_id="u-ana", agora=AGORA_DEPOIS
        )
        gravada = await rotas.find_one({"id": lida["id"]}, {"_id": 0})
        return recalculada, velha, velho_push, intacta, motivo, relida, gravada

    recalculada, velha, velho_push, intacta, motivo, relida, gravada = no_mongo(ensaio)

    assert (recalculada["versao"], recalculada["calculo"]) == (1, CALCULO_GRAVADO)
    assert recalculada["paragens"][0]["chegada_prevista"] == "08:10"
    assert (velha, velho_push, motivo) == (None, None, "conflito")
    assert intacta == recalculada
    assert (relida["versao"], relida["evitar_portagens"], relida["calculo"]) == (2, True, CALCULO_GRAVADO)
    assert gravada == relida
    assert instantes_fora_do_formato(gravada) == []


def test_push_de_paragens_com_set_por_indice_e_o_erro_40_do_mongo_e_do_duplo(no_mongo):
    """Pela mesma operação que o código usa (`find_one_and_update`), o Mongo
    recusa `$push paragens` + `$set paragens.0.x` com `OperationFailure`
    código 40 — não `WriteError` (correção "T3.25"); o duplo levanta o mesmo
    código com a mesma mensagem, e nada fica escrito."""
    atualizacao = {
        "$push": {"paragens": documento_paragem({"id": _id(2)}, "amostra", 10, 1, "u-ana", AGORA_DEPOIS)},
        "$set": {"paragens.0.ordem": 1},
    }

    async def ensaio(base):
        rotas = base[COLECOES["rotas"]]
        rota = _rota_na_base("2026-10-12", _id(1), id_=_id(21))
        await rotas.insert_one(dict(rota))
        with pytest.raises(OperationFailure) as real:
            await rotas.find_one_and_update(
                {"id": rota["id"]}, atualizacao, projection={"_id": 0}, return_document=ReturnDocument.AFTER
            )
        duplo = BaseFalsa({COLECOES["rotas"]: [rota]})
        with pytest.raises(OperationFailure) as falso:
            await duplo[COLECOES["rotas"]].find_one_and_update(
                {"id": rota["id"]}, atualizacao, projection={"_id": 0}, return_document=ReturnDocument.AFTER
            )
        return real.value, falso.value, await rotas.find_one({"id": rota["id"]}, {"_id": 0}), rota, duplo

    real, falso, gravada, rota, duplo = no_mongo(ensaio)

    assert (real.code, real.details["codeName"], isinstance(real, WriteError)) == (40, "ConflictingUpdateOperators", False)
    assert real.details["errmsg"] == "Updating the path 'paragens.0.ordem' would create a conflict at 'paragens'"
    assert (falso.code, str(falso)) == (real.code, real.details["errmsg"])
    assert gravada == rota
    assert duplo[COLECOES["rotas"]].sem_id() == [rota]


def test_as_datas_em_texto_filtram_e_ordenam_como_o_tempo(no_mongo):
    """`rotas_entre`: `$gte`/`$lte` sobre o texto `AAAA-MM-DD` (largura fixa) é
    o intervalo fechado de dias, também na virada do mês e do ano; um só dia
    é um só dia; a procura e a ordem vão pelo `data_1`."""
    dias = ["2027-01-01", "2026-09-30", "2026-10-09", "2026-12-31", "2026-10-10", "2026-10-01"]

    async def ensaio(base):
        rotas = base[COLECOES["rotas"]]
        await rotas.insert_many([_rota_na_base(dia, _id(n), id_=_id(20 + n)) for n, dia in enumerate(dias, 1)])
        entre = await rotas_bd.rotas_entre(base, "2026-10-01", "2026-12-31")
        um_dia = await rotas_bd.rotas_entre(base, "2026-10-10", "2026-10-10")
        procura = rotas.find({"data": {"$gte": "2026-10-01", "$lte": "2026-12-31"}}, {"_id": 0, "calculo": 0})
        plano = _plano(await procura.sort("data", 1).explain())
        return [r["data"] for r in entre], [r["data"] for r in um_dia], plano

    entre, um_dia, plano = no_mongo(ensaio)

    assert entre == ["2026-10-01", "2026-10-09", "2026-10-10", "2026-12-31"]
    assert um_dia == ["2026-10-10"]
    assert "data_1" in plano


def test_dois_post_de_paragens_sem_versao_ao_mesmo_tempo_ficam_as_duas_com_a_versao_3(no_mongo, monkeypatch):
    """A corrida a sério com o Motor e a barreira: os dois leem a rota na
    versão 1; a primeira `find_one_and_update` casa (versão 2) e a segunda
    não — sem versão no corpo, relê e acrescenta (versão 3). Ficam as três
    paragens, com as ordens 0, 1 e 2, cada uma com o seu autor, o seu motivo
    e o tempo das definições; a resposta do último é igual ao GET."""

    async def ensaio(base):
        amanha = _dia(1)
        await base[COLECOES["lojas"]].insert_many(
            [_loja_para_a_rota(1, LAT), _loja_para_a_rota(2, A_80_M, "contactada"), _loja_para_a_rota(3, A_65_M, "cliente")]
        )
        primeira = await rotas_http.adicionar_paragem(amanha, membro=RUI_MEMBRO, corpo={"loja_id": _id(1)})
        _em_corrida(monkeypatch, base, "rotas")
        respostas = await asyncio.gather(
            rotas_http.adicionar_paragem(amanha, membro=RUI_MEMBRO, corpo={"loja_id": _id(2)}),
            rotas_http.adicionar_paragem(amanha, membro=ANA_MEMBRO, corpo={"loja_id": _id(3), "motivo": "entrega"}),
            return_exceptions=True,
        )
        monkeypatch.setattr(bd, "obter_db", lambda: base)
        leitura = await rotas_http.ver_rota(amanha, membro=RUI_MEMBRO)
        rotas = base[COLECOES["rotas"]]
        return primeira, respostas, leitura, await rotas.find_one({"data": amanha}, {"_id": 0}), await rotas.count_documents({})

    primeira, respostas, leitura, gravada, quantas = no_mongo(ensaio)

    gravaram, recusadas = _separar(respostas)
    assert (len(gravaram), recusadas, quantas) == (2, [], 1)
    assert (primeira["versao"], gravada["versao"]) == (1, 3)
    assert sorted(r["versao"] for r in gravaram) == [2, 3]
    assert [r for r in gravaram if r["versao"] == 3] == [leitura]
    assert [p["ordem"] for p in gravada["paragens"]] == [0, 1, 2]
    assert {p["loja_id"]: (p["adicionada_por"], p["motivo"], p["tempo_servico_min"]) for p in gravada["paragens"]} == {
        _id(1): ("u-rui", "angariacao", 15), _id(2): ("u-rui", "amostra", 10), _id(3): ("u-ana", "entrega", 10),
    }
    assert all(p["estado"] == "pendente" and p["removida_em"] is None for p in gravada["paragens"])
    assert instantes_fora_do_formato(gravada) == []
    assert escritas_no_terreno(gravada) == []


def test_duas_pessoas_a_criar_a_rota_do_mesmo_dia_no_mongo_ficam_as_duas(no_mongo, monkeypatch):
    """Sem rota: os dois leem "sem rota" (a barreira) e inserem; a segunda
    `insert_one` falha pelo `data_1` verdadeiro (`criar` → False), relê e
    acrescenta. Uma rota só, com as duas paragens e a versão 2."""

    async def ensaio(base):
        amanha = _dia(1)
        await base[COLECOES["lojas"]].insert_many([_loja_para_a_rota(1, LAT), _loja_para_a_rota(2, A_80_M)])
        _em_corrida(monkeypatch, base, "rotas")
        respostas = await asyncio.gather(
            rotas_http.adicionar_paragem(amanha, membro=RUI_MEMBRO, corpo={"loja_id": _id(1)}),
            rotas_http.adicionar_paragem(amanha, membro=ANA_MEMBRO, corpo={"loja_id": _id(2)}),
            return_exceptions=True,
        )
        rotas = base[COLECOES["rotas"]]
        return respostas, await rotas.find({}, {"_id": 0}).to_list(10)

    respostas, gravadas = no_mongo(ensaio)

    gravaram, recusadas = _separar(respostas)
    assert (len(gravaram), recusadas, len(gravadas)) == (2, [], 1)
    rota = gravadas[0]
    assert rota["versao"] == 2
    assert sorted(r["versao"] for r in gravaram) == [1, 2]
    assert sorted((p["loja_id"], p["ordem"]) for p in rota["paragens"]) == [(_id(1), 0), (_id(2), 1)] or sorted(
        (p["loja_id"], p["ordem"]) for p in rota["paragens"]
    ) == [(_id(1), 1), (_id(2), 0)]
    assert {p["loja_id"]: p["adicionada_por"] for p in rota["paragens"]} == {_id(1): "u-rui", _id(2): "u-ana"}
    assert rota["criado_por"] == rota["paragens"][0]["adicionada_por"]
    assert instantes_fora_do_formato(rota) == []


def test_dois_patch_com_a_mesma_versao_um_200_e_um_409(no_mongo, monkeypatch):
    """Os dois leem a versão 1 (a barreira); a `find_one_and_update` com a
    versão no filtro deixa gravar só um (200, a versão 2 e a sua mudança), e
    o outro dá 409 `conflito` sem nada gravado; a resposta do que gravou é
    igual ao GET seguinte."""

    async def ensaio(base):
        amanha = _dia(1)
        await base[COLECOES["lojas"]].insert_one(_loja_para_a_rota(1, LAT))
        criada = await rotas_http.adicionar_paragem(amanha, membro=RUI_MEMBRO, corpo={"loja_id": _id(1)})
        _em_corrida(monkeypatch, base, "rotas")
        respostas = await asyncio.gather(
            rotas_http.alterar_rota(amanha, membro=RUI_MEMBRO, corpo={"versao": 1, "hora_saida": "07:30"}),
            rotas_http.alterar_rota(amanha, membro=ANA_MEMBRO, corpo={"versao": 1, "evitar_portagens": True}),
            return_exceptions=True,
        )
        monkeypatch.setattr(bd, "obter_db", lambda: base)
        leitura = await rotas_http.ver_rota(amanha, membro=RUI_MEMBRO)
        return criada, respostas, leitura, await base[COLECOES["rotas"]].find_one({"data": amanha}, {"_id": 0})

    criada, respostas, leitura, gravada = no_mongo(ensaio)

    gravaram, recusadas = _separar(respostas)
    assert (len(gravaram), len(recusadas)) == (1, 1)
    assert (recusadas[0].status_code, recusadas[0].detail) == (409, _erro("conflito", MENSAGEM_CONFLITO))
    venceu = gravaram[0]
    assert venceu == leitura
    assert (criada["versao"], venceu["versao"], gravada["versao"]) == (1, 2, 2)
    mudanca = (gravada["hora_saida"], gravada["evitar_portagens"])
    assert mudanca in (("07:30", False), ("08:00", True))
    assert (venceu["hora_saida"], venceu["evitar_portagens"]) == mudanca
    assert gravada["atualizado_por"] == ("u-rui" if mudanca == ("07:30", False) else "u-ana")
    assert instantes_fora_do_formato(gravada) == []
    assert escritas_no_terreno(gravada) == []


def test_apagar_uma_loja_numa_paragem_da_409_loja_em_rota(no_mongo):
    """`DELETE /lojas/{id}` pelo `paragens.loja_id` verdadeiro: a loja numa
    paragem ativa da rota de amanhã → 409 "está numa rota"; a que só esteve
    numa rota passada → 409 "esteve numa rota"; a que só está retirada e
    pendente apaga-se; as rotas ficam tal e qual."""

    async def ensaio(base):
        lojas, rotas = base[COLECOES["lojas"]], base[COLECOES["rotas"]]
        await lojas.insert_many([_loja_para_a_rota(1, LAT), _loja_para_a_rota(2, A_80_M), _loja_para_a_rota(3, A_65_M)])
        futura = _rota_na_base(_dia(1), _id(1), _id(3), id_=_id(21))
        _retirar(futura["paragens"][1])
        passada = _rota_na_base(_dia(-1), _id(2), id_=_id(22))
        await rotas.insert_many([futura, passada])
        antes = await rotas.find({}, {"_id": 0}).sort("data", 1).to_list(10)
        recusas = []
        for loja_id in (_id(1), _id(2)):
            with pytest.raises(HTTPException) as recusa:
                await apagar_loja(loja_id, RUI_MEMBRO)
            recusas.append((recusa.value.status_code, recusa.value.detail))
        apagada = await apagar_loja(_id(3), RUI_MEMBRO)
        depois = await rotas.find({}, {"_id": 0}).sort("data", 1).to_list(10)
        restantes = sorted(loja["id"] for loja in await lojas.find({}, {"_id": 0, "id": 1}).to_list(10))
        return recusas, apagada, antes, depois, restantes

    recusas, apagada, antes, depois, restantes = no_mongo(ensaio)

    assert recusas == [
        (409, _erro("loja_em_rota", MENSAGEM_LOJA_EM_ROTA)),
        (409, _erro("loja_em_rota", MENSAGEM_LOJA_ESTEVE_EM_ROTA)),
    ]
    assert apagada == {"apagada": True}
    assert depois == antes
    assert restantes == [_id(1), _id(2)]
