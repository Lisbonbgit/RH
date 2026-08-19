"""Validação dos modelos de Loja e Caixa e dos endpoints de apagar (sem base de dados).

Os endpoints são chamados directamente (sem HTTP nem Mongo), com um duplo de base de
dados que regista as chamadas e devolve resultados à escolha do teste — o mesmo padrão
de test_indices.py.
"""
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import lojas as lojas_mod
from faturacao.lojas import CaixaEntrada, LojaEntrada, apagar_caixa, apagar_loja, listar_caixas


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find` real descodifica BSON de fresco a cada chamada: o resultado NUNCA
    está ligado ao que está no Mongo, e duas leituras nunca devolvem o MESMO
    objecto. Um duplo enlatado que devolve sempre o dicionário do teste deixa
    passar por ALIASING uma asserção sobre a fixture que o código de produção
    mutou sem ter escrito nada. Já apanhou um caso real neste módulo
    (`cancelar_venda`, em faturacao/venda.py).

    Cópia FUNDA por regra da casa: lojas e caixas são hoje planas, mas é a
    mesma função em todos os duplos do módulo — uma que fosse rasa "porque ali
    dá" era a que ficava errada quando a fixture crescesse.
    """
    return deepcopy(documento)


class ResultadoDelete:
    """Duplo do resultado de delete_one do Motor — só o campo que o código usa."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class CursorFalso:
    """Duplo de um cursor Mongo: imita find().sort().to_list() do Motor. Mesmo
    padrão de test_motivos_endpoints.py: só ordena os dados devolvidos se
    sort() tiver sido mesmo chamado, para o teste apanhar um sort() em falta
    e não só um sort() com o campo errado."""

    def __init__(self, dados):
        self._dados = dados
        self._ordem = None  # Tuplo (campo, direcção)

    def sort(self, campo, direcção=1):
        self._ordem = (campo, direcção)
        return self

    async def to_list(self, limite):
        dados = list(self._dados)
        if self._ordem:
            campo, direcção = self._ordem
            dados.sort(key=lambda d: d.get(campo, ""), reverse=(direcção == -1))
        return dados


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: regista as chamadas e devolve resultados à escolha do teste."""

    def __init__(self, registo, count_documents_devolve=0, delete_one_devolve=0, find_devolve=None):
        self.registo = registo
        self._count_documents_devolve = count_documents_devolve
        self._delete_one_devolve = delete_one_devolve
        self._find_devolve = find_devolve or []

    def find(self, filtro, projecao=None):
        self.registo.append(("find", filtro))
        return CursorFalso([_como_o_motor(d) for d in self._find_devolve])

    async def count_documents(self, filtro):
        self.registo.append(("count_documents", filtro))
        return self._count_documents_devolve

    async def delete_one(self, filtro):
        self.registo.append(("delete_one", filtro))
        return ResultadoDelete(self._delete_one_devolve)


class DbFalsa:
    def __init__(self, colecoes):
        self._colecoes = colecoes

    def __getitem__(self, nome):
        return self._colecoes[nome]


def test_loja_minima():
    lj = LojaEntrada(nome="L'Açaí Belém")
    assert lj.nome == "L'Açaí Belém"
    assert lj.cae is None


def test_loja_sem_nome_e_recusada():
    with pytest.raises(ValidationError):
        LojaEntrada(nome="")


def test_loja_completa():
    lj = LojaEntrada(
        nome="L'Açaí Algueirão",
        morada="Rua Ribeiro dos Reis 15B",
        codigo_postal="2725-175",
        localidade="Algueirão",
        email="geral@olacai.com",
        telefone="216086715",
        cae="56103",
    )
    assert lj.codigo_postal == "2725-175"


def test_codigo_postal_invalido_e_recusado():
    with pytest.raises(ValidationError):
        LojaEntrada(nome="X", codigo_postal="2725")


def test_caixa_exige_nome():
    with pytest.raises(ValidationError):
        CaixaEntrada(nome="")


def test_caixa_nao_tem_campo_de_register_vendus():
    """O register_id do Vendus é configuração do sistema, nunca da interface."""
    assert "register_id" not in CaixaEntrada.model_fields
    assert "vendus_register_id" not in CaixaEntrada.model_fields


def test_codigo_postal_vazio_e_tratado_como_none():
    """"" é falsy e passava despercebido pelo validador — tem de virar None,
    para não ficar um código postal vazio guardado a fingir que foi preenchido."""
    lj = LojaEntrada(nome="X", codigo_postal="")
    assert lj.codigo_postal is None


def test_codigo_postal_com_newline_final_e_recusado():
    """$ casa antes de um '\\n' final em Python — \\Z fecha essa fresta."""
    with pytest.raises(ValidationError):
        LojaEntrada(nome="X", codigo_postal="2725-175\n")


def test_apagar_loja_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa(
        {
            "fat_caixas": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_lojas": ColeccaoFalsa(registo, delete_one_devolve=0),
        }
    )
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_loja("id-que-nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_loja_com_caixas_continua_a_recusar_409(monkeypatch):
    """Regressão: a guarda existente (loja com caixas) tem de continuar a funcionar."""
    registo = []
    db = DbFalsa(
        {
            "fat_caixas": ColeccaoFalsa(registo, count_documents_devolve=2),
            "fat_lojas": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_loja("loja-com-caixas", _={}))
    assert excinfo.value.status_code == 409
    assert ("delete_one", {"id": "loja-com-caixas"}) not in registo


def test_apagar_loja_existente_sem_caixas_e_apagada(monkeypatch):
    """Regressão: o caminho feliz continua a devolver sucesso."""
    registo = []
    db = DbFalsa(
        {
            "fat_caixas": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_lojas": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_loja("loja-normal", _={}))
    assert resultado == {"apagada": True}


def test_apagar_caixa_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa({"fat_caixas": ColeccaoFalsa(registo, delete_one_devolve=0)})
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_caixa("id-que-nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_caixa_existente_e_apagada(monkeypatch):
    """Regressão: o caminho feliz continua a devolver sucesso."""
    registo = []
    db = DbFalsa({"fat_caixas": ColeccaoFalsa(registo, delete_one_devolve=1)})
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_caixa("caixa-normal", _={}))
    assert resultado == {"apagada": True}


def test_listar_caixas_ordena_por_nome(monkeypatch):
    """listar_caixas era o único listar do módulo sem ordenação — a lista das
    caixas de uma loja chegava à interface na ordem que o Mongo desse (não
    garantida). Ordena por nome, como listar_lojas já faz."""
    registo = []
    dados_desordenados = [
        {"id": "3", "nome": "Caixa C"},
        {"id": "1", "nome": "Caixa A"},
        {"id": "2", "nome": "Caixa B"},
    ]
    db = DbFalsa({"fat_caixas": ColeccaoFalsa(registo, find_devolve=dados_desordenados)})
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    resultado = _corre(listar_caixas("loja-1", _={}))
    assert [c["nome"] for c in resultado] == ["Caixa A", "Caixa B", "Caixa C"]
