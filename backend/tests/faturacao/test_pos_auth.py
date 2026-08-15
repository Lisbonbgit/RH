"""Autenticação do POS: dispositivo emparelhado + PIN do operador.

Duas peças, dois mecanismos (ver docstring de faturacao/pos_auth.py):
- Token de DISPOSITIVO — sai de /dispositivos-pos (gestor) + /pos/emparelhar
  (a troca do código pelo token). Guarda o `dispositivo_atual`.
- Token de OPERADOR — sai de /pos/entrar (PIN). Guarda o `operador_atual`.

Duplo de base de dados com utilizadores a sério dentro (mesmo padrão de
test_utilizadores.py): find() filtra de facto pelos campos do filtro, para
que "inactivo não entra" e "de outra loja não entra" provem comportamento
real, e não apenas confiem que o Mongo filtraria por nós.

Nenhum teste liga a uma base de dados nem à rede — tudo por duplos.
"""
import asyncio
import os

import jwt
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET", "segredo-de-teste")

from faturacao import pos_auth as pos_auth_mod
from faturacao.db import COLECOES
from faturacao.pins import hash_pin
from faturacao.pos_auth import (
    PedidoCodigo,
    PedidoEmparelhar,
    PedidoEntrar,
    dispositivo_atual,
    emparelhar,
    entrar,
    gerar_codigo_emparelhamento,
    operador_atual,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados --------------------------------------------------


def _corresponde(item, filtro):
    """Réplica minimalista do casamento de filtro do Mongo: igualdade exacta
    em cada campo pedido. Suficiente para os filtros usados neste módulo."""
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


class CursorFalso:
    def __init__(self, itens):
        self._itens = itens

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, n=None):
        return self._itens


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: find() filtra de facto (ver docstring)."""

    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None):
        self.registo.append(("find", filtro))
        return CursorFalso([d for d in self._documentos if _corresponde(d, filtro)])

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return encontrados[0] if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._documentos.append(doc)
        return None

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return None


class DbFalsa:
    """Duplo de db com várias colecções — dispositivos, utilizadores e lojas
    têm estados independentes na mesma chamada a obter_db()."""

    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoFalsa([]))


def _db(registo, dispositivos=None, utilizadores=None, lojas=None):
    return DbFalsa({
        COLECOES["dispositivos"]: ColeccaoFalsa(registo, dispositivos),
        COLECOES["utilizadores"]: ColeccaoFalsa(registo, utilizadores),
        COLECOES["lojas"]: ColeccaoFalsa(registo, lojas),
    })


def _operador(**over):
    o = {
        "id": "op-1", "nome": "Rafaela", "perfil": "operador_caixa",
        "lojas": ["loja-1"], "ativo": True, "pin_hash": hash_pin("1234"),
    }
    o.update(over)
    return o


# --- Emparelhamento do dispositivo -------------------------------------------


def test_gerar_codigo_recusa_loja_inexistente(monkeypatch):
    registo = []
    db = _db(registo, lojas=[])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(gerar_codigo_emparelhamento(PedidoCodigo(loja_id="nao-existe"), _={}))
    assert excinfo.value.status_code == 404


def test_gerar_codigo_e_emparelhar_devolve_token_de_dispositivo(monkeypatch):
    """O caminho feliz completo: o gestor gera o código, o PC da loja troca-o
    por um token de dispositivo."""
    registo = []
    db = _db(registo, lojas=[{"id": "loja-1", "nome": "Belém"}])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    resultado_codigo = _corre(gerar_codigo_emparelhamento(PedidoCodigo(loja_id="loja-1"), _={}))
    assert "codigo" in resultado_codigo

    resultado = _corre(emparelhar(PedidoEmparelhar(codigo=resultado_codigo["codigo"])))
    assert resultado["loja_id"] == "loja-1"
    assert resultado["device_token"]


def test_emparelhar_com_codigo_invalido_e_recusado_401(monkeypatch):
    registo = []
    db = _db(registo)
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(emparelhar(PedidoEmparelhar(codigo="LIXOLIXO")))
    assert excinfo.value.status_code == 401


def test_emparelhar_com_codigo_expirado_e_recusado_401(monkeypatch):
    registo = []
    db = _db(registo, lojas=[{"id": "loja-1", "nome": "Belém"}])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)
    resultado_codigo = _corre(gerar_codigo_emparelhamento(PedidoCodigo(loja_id="loja-1"), _={}))

    # Recua o relógio: o código já devia ter expirado.
    dispositivos = db[COLECOES["dispositivos"]]
    dispositivos._documentos[0]["expira_em"] = "2000-01-01T00:00:00+00:00"

    with pytest.raises(HTTPException) as excinfo:
        _corre(emparelhar(PedidoEmparelhar(codigo=resultado_codigo["codigo"])))
    assert excinfo.value.status_code == 401


def test_emparelhar_com_codigo_ja_usado_e_recusado_401(monkeypatch):
    """Uso único: o mesmo código não pode ser trocado duas vezes."""
    registo = []
    db = _db(registo, lojas=[{"id": "loja-1", "nome": "Belém"}])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)
    resultado_codigo = _corre(gerar_codigo_emparelhamento(PedidoCodigo(loja_id="loja-1"), _={}))
    _corre(emparelhar(PedidoEmparelhar(codigo=resultado_codigo["codigo"])))

    with pytest.raises(HTTPException) as excinfo:
        _corre(emparelhar(PedidoEmparelhar(codigo=resultado_codigo["codigo"])))
    assert excinfo.value.status_code == 401


def test_dispositivo_atual_com_token_valido_devolve_o_dispositivo(monkeypatch):
    registo = []
    db = _db(registo, lojas=[{"id": "loja-1", "nome": "Belém"}])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)
    resultado_codigo = _corre(gerar_codigo_emparelhamento(PedidoCodigo(loja_id="loja-1"), _={}))
    par = _corre(emparelhar(PedidoEmparelhar(codigo=resultado_codigo["codigo"])))

    disp = _corre(dispositivo_atual(x_device_token=par["device_token"]))
    assert disp["loja_id"] == "loja-1"


def test_dispositivo_atual_sem_token_e_recusado_401():
    with pytest.raises(HTTPException) as excinfo:
        _corre(dispositivo_atual(x_device_token=None))
    assert excinfo.value.status_code == 401


def test_dispositivo_atual_com_token_invalido_e_recusado_401(monkeypatch):
    registo = []
    db = _db(registo)
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(dispositivo_atual(x_device_token="isto-nao-existe"))
    assert excinfo.value.status_code == 401


def test_dispositivo_atual_nunca_aceita_jwt_de_gestao(monkeypatch):
    """Um JWT de gestão válido não é, nem por acidente, um token de
    dispositivo válido: os dois nunca partilham formato nem armazenamento."""
    registo = []
    db = _db(registo)
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)
    token_gestao = jwt.encode(
        {"user_id": "u1", "email": "a@b.pt", "role": "admin"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )

    with pytest.raises(HTTPException) as excinfo:
        _corre(dispositivo_atual(x_device_token=token_gestao))
    assert excinfo.value.status_code == 401


# --- Entrada por PIN ----------------------------------------------------------


def test_entrar_pin_certo_devolve_token_de_operador(monkeypatch):
    registo = []
    db = _db(registo, utilizadores=[_operador()])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    resultado = _corre(entrar(PedidoEntrar(pin="1234"), dispositivo={"loja_id": "loja-1"}))
    assert resultado["operador"]["id"] == "op-1"
    assert resultado["operator_token"]

    payload = jwt.decode(
        resultado["operator_token"], pos_auth_mod.POS_JWT_SECRET, algorithms=["HS256"]
    )
    assert payload["operador_id"] == "op-1"
    assert payload["loja_id"] == "loja-1"


def test_entrar_pin_errado_e_recusado_401_sem_dizer_se_existe(monkeypatch):
    """A mensagem tem de ser a mesma quer o PIN pertença a alguém quer não —
    senão o 401 vira um oráculo que revela PINs válidos por tentativa e erro."""
    registo = []
    db_com_gente = _db(registo, utilizadores=[_operador()])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db_com_gente)
    with pytest.raises(HTTPException) as excinfo_errado:
        _corre(entrar(PedidoEntrar(pin="0000"), dispositivo={"loja_id": "loja-1"}))
    assert excinfo_errado.value.status_code == 401

    db_vazia = _db([], utilizadores=[])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db_vazia)
    with pytest.raises(HTTPException) as excinfo_vazio:
        _corre(entrar(PedidoEntrar(pin="0000"), dispositivo={"loja_id": "loja-1"}))
    assert excinfo_vazio.value.status_code == 401

    assert excinfo_errado.value.detail == excinfo_vazio.value.detail


def test_entrar_duas_correspondencias_e_recusado_409(monkeypatch):
    """Regra 2 (spec §7.1): a unicidade do PIN não é garantida por índice —
    se a verificação no servidor falhar (ex.: alguém movido de loja sem lhe
    mudar o PIN), a entrada tem de tratar isso como conflito explícito e
    NUNCA escolher a primeira correspondência."""
    registo = []
    ana = _operador(id="op-1", nome="Ana", pin_hash=hash_pin("1234"))
    bia = _operador(id="op-2", nome="Bia", pin_hash=hash_pin("1234"))
    db = _db(registo, utilizadores=[ana, bia])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(entrar(PedidoEntrar(pin="1234"), dispositivo={"loja_id": "loja-1"}))
    assert excinfo.value.status_code == 409
    assert "gestor" in excinfo.value.detail.lower()


def test_entrar_operador_inactivo_nao_entra(monkeypatch):
    registo = []
    saiu = _operador(id="op-1", nome="Ana (saiu)", ativo=False, pin_hash=hash_pin("1234"))
    db = _db(registo, utilizadores=[saiu])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(entrar(PedidoEntrar(pin="1234"), dispositivo={"loja_id": "loja-1"}))
    assert excinfo.value.status_code == 401
    assert any(chamada == ("find", {"ativo": True}) for chamada in registo)


def test_entrar_operador_de_outra_loja_nao_entra(monkeypatch):
    registo = []
    de_outra_loja = _operador(id="op-1", nome="Ana", lojas=["loja-2"], pin_hash=hash_pin("1234"))
    db = _db(registo, utilizadores=[de_outra_loja])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(entrar(PedidoEntrar(pin="1234"), dispositivo={"loja_id": "loja-1"}))
    assert excinfo.value.status_code == 401


def test_entrar_administrador_sem_lojas_entra_em_qualquer_loja(monkeypatch):
    """Regressão do mesmo âmbito usado em utilizadores.py: lojas=[] é o
    administrador, entra em qualquer loja."""
    registo = []
    admin = _operador(id="op-0", nome="Matheus", perfil="administrador", lojas=[],
                       pin_hash=hash_pin("9999"))
    db = _db(registo, utilizadores=[admin])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    resultado = _corre(entrar(PedidoEntrar(pin="9999"), dispositivo={"loja_id": "loja-7"}))
    assert resultado["operador"]["id"] == "op-0"


def test_entrar_verifica_pin_fora_do_event_loop(monkeypatch):
    """bcrypt custa ~166ms e é síncrono — a verificação tem de correr em
    asyncio.to_thread, nunca directamente no event loop (achado da revisão:
    com 20 operadores seriam ~3,3s a bloquear o portal inteiro)."""
    registo = []
    db = _db(registo, utilizadores=[_operador()])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    chamadas = []
    real_to_thread = pos_auth_mod.to_thread

    async def to_thread_espiao(func, *args, **kwargs):
        chamadas.append((func, args, kwargs))
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(pos_auth_mod, "to_thread", to_thread_espiao)

    _corre(entrar(PedidoEntrar(pin="1234"), dispositivo={"loja_id": "loja-1"}))
    assert len(chamadas) == 1
    assert chamadas[0][0] is pos_auth_mod.pin_valido


def test_entrar_mutante_escolhe_a_primeira_correspondencia_fica_vermelho(monkeypatch):
    """Documenta a mutação pedida no brief: se `entrar` escolhesse sempre a
    primeira correspondência em vez de tratar 2+ como conflito, este teste
    (idêntico ao do conflito) apanhava-o. Corrido manualmente com a guarda
    comentada, confirma-se o vermelho — ver relatório da tarefa."""
    registo = []
    ana = _operador(id="op-1", nome="Ana", pin_hash=hash_pin("1234"))
    bia = _operador(id="op-2", nome="Bia", pin_hash=hash_pin("1234"))
    db = _db(registo, utilizadores=[ana, bia])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(entrar(PedidoEntrar(pin="1234"), dispositivo={"loja_id": "loja-1"}))
    assert excinfo.value.status_code == 409


# --- Token de operador ---------------------------------------------------------


def test_operador_atual_com_token_valido(monkeypatch):
    registo = []
    db = _db(registo, utilizadores=[_operador()])
    monkeypatch.setattr(pos_auth_mod, "obter_db", lambda: db)
    resultado = _corre(entrar(PedidoEntrar(pin="1234"), dispositivo={"loja_id": "loja-1"}))

    payload = _corre(operador_atual(x_operator_token=resultado["operator_token"]))
    assert payload["operador_id"] == "op-1"


def test_operador_atual_sem_token_e_recusado_401():
    with pytest.raises(HTTPException) as excinfo:
        _corre(operador_atual(x_operator_token=None))
    assert excinfo.value.status_code == 401


def test_operador_atual_nunca_aceita_jwt_de_gestao():
    """A guarda central da tarefa: um administrador com sessão aberta no
    backoffice não pode vender sem se identificar com o PIN — o JWT de
    gestão não é aceite aqui, nem por partilhar o mesmo formato (JWT)."""
    token_gestao = jwt.encode(
        {"user_id": "u1", "email": "a@b.pt", "role": "admin"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    with pytest.raises(HTTPException) as excinfo:
        _corre(operador_atual(x_operator_token=token_gestao))
    assert excinfo.value.status_code == 401


def test_operador_atual_token_expirado_e_recusado_401():
    import time

    token_expirado = jwt.encode(
        {
            "operador_id": "op-1", "nome": "Ana", "perfil": "operador_caixa",
            "loja_id": "loja-1", "tipo": "operador_pos",
            "iat": int(time.time()) - 100000, "exp": int(time.time()) - 1,
        },
        pos_auth_mod.POS_JWT_SECRET, algorithm="HS256",
    )
    with pytest.raises(HTTPException) as excinfo:
        _corre(operador_atual(x_operator_token=token_expirado))
    assert excinfo.value.status_code == 401
