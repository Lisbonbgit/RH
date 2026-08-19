"""Utilizadores do POS: nome, PIN, perfil, lojas onde entram.

Os testes de modelo (Pydantic) não tocam a base de dados. Os testes de
endpoint usam um duplo de base de dados que imita o Motor — o mesmo padrão de
test_lojas.py e test_pagamentos_endpoints.py — incluindo um duplo de find()
que FILTRA de facto pelos campos do filtro (não ignora o filtro), porque a
Regra 2 (unicidade do PIN) depende de o servidor só comparar contra
utilizadores ACTIVOS: se o duplo devolvesse sempre todos, os testes que
provam que um PIN de alguém inactivo pode ser reutilizado não seriam capazes
de falhar por engano.
"""
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import utilizadores as utilizadores_mod
from faturacao.pins import hash_pin
from faturacao.utilizadores import (
    PERFIS_POS,
    MudarEstado,
    MudarPin,
    UtilizadorEdicao,
    UtilizadorEntrada,
    criar,
    editar,
    listar,
    mudar_estado,
    mudar_pin,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados --------------------------------------------------


def _corresponde(item, filtro):
    """Réplica minimalista do casamento de filtro do Mongo: igualdade exacta
    em cada campo pedido. Suficiente para os filtros usados neste módulo
    ({"ativo": True}, {"id": ...}, {})."""
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find`/`find_one` reais descodificam BSON de fresco a cada chamada: o
    resultado NUNCA está ligado ao que está no Mongo. Um duplo que devolvesse
    o próprio objecto guardado deixa um teste passar por ALIASING — o código
    de produção muta o que "leu", o Mongo falso muda sozinho, e a asserção
    fica verde sem que nenhuma escrita tenha acontecido. Já apanhou um caso
    real neste módulo (`cancelar_venda`, em faturacao/venda.py).

    Cópia FUNDA, não `dict(d)`: o utilizador traz `lojas`, e é justamente essa
    lista que `mudar_pin` lê do documento e passa a `_pin_em_uso` para decidir
    a Regra 2 — uma cópia rasa deixava-a partilhada com o documento guardado.
    """
    return deepcopy(documento)


class CursorFalso:
    """Duplo do cursor devolvido por .find() do Motor: só sort()/to_list()."""

    def __init__(self, itens):
        self._itens = itens

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, n=None):
        return self._itens


class ResultadoUpdate:
    """Duplo do resultado de update_one do Motor — só o campo usado."""

    def __init__(self, matched_count):
        self.matched_count = matched_count


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo com utilizadores a sério dentro, para que
    find({"ativo": True}) filtre de verdade."""

    def __init__(self, registo, utilizadores=None, update_one_matched=1):
        self.registo = registo
        self._utilizadores = utilizadores if utilizadores is not None else []
        self._update_one_matched = update_one_matched

    def find(self, filtro=None):
        self.registo.append(("find", filtro))
        return CursorFalso(
            [_como_o_motor(u) for u in self._utilizadores if _corresponde(u, filtro)]
        )

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [u for u in self._utilizadores if _corresponde(u, filtro)]
        return _como_o_motor(encontrados[0]) if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._utilizadores.append(deepcopy(doc))
        return None

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        alvos = [u for u in self._utilizadores if _corresponde(u, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return ResultadoUpdate(self._update_one_matched if alvos else 0)


class DbFalsa:
    def __init__(self, coleccao):
        self._coleccao = coleccao

    def __getitem__(self, nome):
        return self._coleccao


# --- Modelo (dados do brief, Step 1) -----------------------------------------


def test_perfis_sao_os_tres_decididos():
    """O dono decidiu NÃO ter 'Encarregada de Loja' (spec D16)."""
    assert PERFIS_POS == ["administrador", "operador_caixa", "contabilista"]


def test_utilizador_valido():
    u = UtilizadorEntrada(nome="Rafaela Prates", pin="1234", perfil="operador_caixa",
                          lojas=["loja-1"])
    assert u.pin == "1234"


def test_perfil_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        UtilizadorEntrada(nome="X", pin="1234", perfil="encarregada", lojas=[])


def test_pin_invalido_e_recusado():
    with pytest.raises(ValidationError):
        UtilizadorEntrada(nome="X", pin="12", perfil="operador_caixa", lojas=[])


def test_operador_tem_de_ter_pelo_menos_uma_loja():
    with pytest.raises(ValidationError):
        UtilizadorEntrada(nome="X", pin="1234", perfil="operador_caixa", lojas=[])


def test_administrador_pode_nao_ter_lojas():
    """O administrador entra em qualquer loja."""
    u = UtilizadorEntrada(nome="Matheus", pin="9999", perfil="administrador", lojas=[])
    assert u.lojas == []


def test_nao_existe_endpoint_de_apagar():
    """Quem sai fica inactivo. Apagar partiria o histórico de vendas."""
    from faturacao.utilizadores import router
    metodos = {(r.path, m) for r in router.routes for m in getattr(r, "methods", set())}
    assert not [p for (p, m) in metodos if m == "DELETE"]


def test_edicao_nao_tem_campo_de_pin():
    """Editar nome/perfil/lojas não pode mexer no PIN — isso é só em /pin,
    porque é o único outro sítio onde o servidor vê o PIN em claro."""
    assert "pin" not in UtilizadorEdicao.model_fields


# --- Nunca sai pin_hash numa resposta ----------------------------------------


def test_criar_nao_devolve_pin_hash(monkeypatch):
    registo = []
    db = DbFalsa(ColeccaoFalsa(registo))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    dados = UtilizadorEntrada(nome="Rafaela", pin="1234", perfil="operador_caixa",
                              lojas=["loja-1"])
    resultado = _corre(criar(dados, _={}))
    assert "pin_hash" not in resultado
    assert resultado["nome"] == "Rafaela"


def test_listar_nao_devolve_pin_hash(monkeypatch):
    registo = []
    existente = {"id": "u1", "nome": "Ana", "perfil": "operador_caixa", "lojas": ["loja-1"],
                 "ativo": True, "pin_hash": hash_pin("1234")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[existente]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    resultado = _corre(listar(_={}))
    assert all("pin_hash" not in u for u in resultado)


def test_editar_nao_devolve_pin_hash(monkeypatch):
    registo = []
    existente = {"id": "u1", "nome": "Ana", "perfil": "operador_caixa", "lojas": ["loja-1"],
                 "ativo": True, "pin_hash": hash_pin("1234")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[existente]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    dados = UtilizadorEdicao(nome="Ana Prates", perfil="operador_caixa", lojas=["loja-1"])
    resultado = _corre(editar("u1", dados, _={}))
    assert "pin_hash" not in resultado
    assert resultado["nome"] == "Ana Prates"


# --- Editar / mudar estado: 404 e caminho feliz ------------------------------


def test_editar_utilizador_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa(ColeccaoFalsa(registo))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    dados = UtilizadorEdicao(nome="X", perfil="operador_caixa", lojas=["loja-1"])
    with pytest.raises(HTTPException) as excinfo:
        _corre(editar("nao-existe", dados, _={}))
    assert excinfo.value.status_code == 404


def test_mudar_estado_utilizador_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa(ColeccaoFalsa(registo))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(mudar_estado("nao-existe", MudarEstado(ativo=False), _={}))
    assert excinfo.value.status_code == 404


def test_mudar_estado_existente_devolve_o_novo_estado(monkeypatch):
    registo = []
    existente = {"id": "u1", "nome": "Ana", "perfil": "operador_caixa", "lojas": ["loja-1"],
                 "ativo": True, "pin_hash": hash_pin("1234")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[existente]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    resultado = _corre(mudar_estado("u1", MudarEstado(ativo=False), _={}))
    assert resultado == {"ativo": False}
    assert existente["ativo"] is False


# --- Regra 2: unicidade do PIN entre activos, verificada no servidor --------


def test_criar_com_pin_repetido_na_mesma_loja_e_recusado(monkeypatch):
    registo = []
    existente = {"id": "u1", "nome": "Ana", "perfil": "operador_caixa", "lojas": ["loja-1"],
                 "ativo": True, "pin_hash": hash_pin("1234")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[existente]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    dados = UtilizadorEntrada(nome="Bia", pin="1234", perfil="operador_caixa",
                              lojas=["loja-1"])
    with pytest.raises(HTTPException) as excinfo:
        _corre(criar(dados, _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_criar_com_mesmo_pin_noutra_loja_e_aceite(monkeypatch):
    registo = []
    existente = {"id": "u1", "nome": "Ana", "perfil": "operador_caixa", "lojas": ["loja-1"],
                 "ativo": True, "pin_hash": hash_pin("1234")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[existente]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    dados = UtilizadorEntrada(nome="Bia", pin="1234", perfil="operador_caixa",
                              lojas=["loja-2"])
    resultado = _corre(criar(dados, _={}))
    assert resultado["nome"] == "Bia"
    assert any(chamada[0] == "insert_one" for chamada in registo)


def test_criar_com_pin_de_utilizador_inactivo_e_aceite(monkeypatch):
    """O PIN de quem já saiu (inactivo) pode ser dado a outra pessoa."""
    registo = []
    saiu = {"id": "u1", "nome": "Ana (saiu)", "perfil": "operador_caixa", "lojas": ["loja-1"],
            "ativo": False, "pin_hash": hash_pin("1234")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[saiu]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    dados = UtilizadorEntrada(nome="Bia", pin="1234", perfil="operador_caixa",
                              lojas=["loja-1"])
    resultado = _corre(criar(dados, _={}))
    assert resultado["nome"] == "Bia"


def test_criar_operador_colide_com_administrador_existente(monkeypatch):
    """O administrador entra em qualquer loja (lojas=[]) — o âmbito dele
    sobrepõe-se ao de toda a gente, por isso o PIN dele tem de ser único em
    relação a qualquer operador, mesmo de uma loja que nunca mencionou."""
    registo = []
    admin = {"id": "u0", "nome": "Matheus", "perfil": "administrador", "lojas": [],
             "ativo": True, "pin_hash": hash_pin("9999")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[admin]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    dados = UtilizadorEntrada(nome="Bia", pin="9999", perfil="operador_caixa",
                              lojas=["loja-7"])
    with pytest.raises(HTTPException) as excinfo:
        _corre(criar(dados, _={}))
    assert excinfo.value.status_code == 409


def test_mudar_pin_para_o_mesmo_pin_que_ja_tinha_nao_e_recusado(monkeypatch):
    """Editar o próprio utilizador: comparar o PIN novo contra os próprios
    utilizadores activos incluiria sempre a própria pessoa (o PIN novo bate
    certo com o hash antigo dela, se não estiver mesmo a mudar). Por isso o
    próprio utilizador tem de ficar de fora da comparação."""
    registo = []
    existente = {"id": "u1", "nome": "Ana", "perfil": "operador_caixa", "lojas": ["loja-1"],
                 "ativo": True, "pin_hash": hash_pin("1234")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[existente]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    resultado = _corre(mudar_pin("u1", MudarPin(pin="1234"), _={}))
    assert resultado == {"atualizado": True}


def test_mudar_pin_repetido_na_mesma_loja_e_recusado(monkeypatch):
    registo = []
    ana = {"id": "u1", "nome": "Ana", "perfil": "operador_caixa", "lojas": ["loja-1"],
           "ativo": True, "pin_hash": hash_pin("1234")}
    bia = {"id": "u2", "nome": "Bia", "perfil": "operador_caixa", "lojas": ["loja-1"],
           "ativo": True, "pin_hash": hash_pin("5678")}
    db = DbFalsa(ColeccaoFalsa(registo, utilizadores=[ana, bia]))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(mudar_pin("u2", MudarPin(pin="1234"), _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "update_one" for chamada in registo)


def test_mudar_pin_utilizador_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa(ColeccaoFalsa(registo))
    monkeypatch.setattr(utilizadores_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(mudar_pin("nao-existe", MudarPin(pin="1234"), _={}))
    assert excinfo.value.status_code == 404
