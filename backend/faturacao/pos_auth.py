"""Autenticação do POS — separada da autenticação de gestão (auth.py).

Duas peças, duas vidas diferentes (spec §7.1):
- Token de DISPOSITIVO: o PC da loja é autorizado uma vez, no backoffice —
  o gestor gera um código de emparelhamento de uso único
  (`gerar_codigo_emparelhamento`, exige `gestor_atual`) e o próprio POS
  troca-o por um token de dispositivo (`emparelhar`, sem Depends — é o
  bootstrap da cadeia, o dispositivo ainda não tem nenhum token nesse
  momento). O token fica em localStorage no browser da loja e vai no
  cabeçalho X-Device-Token em cada pedido seguinte (`dispositivo_atual`).
- Token de OPERADOR: sai da entrada por PIN (`entrar`, exige
  `dispositivo_atual`) e dura o turno. É o que identifica quem fez cada
  venda. Vai no cabeçalho X-Operator-Token (`operador_atual`), NUNCA no
  Authorization — esse cabeçalho é do JWT de gestão (auth.py).

Nenhum dos dois mecanismos usa `descodificar_token` nem o `JWT_SECRET` de
gestão: o token de operador é assinado com `POS_JWT_SECRET`, uma chave
própria, para que um JWT de gestão nunca seja aceite aqui — nem por
coincidência de segredo. Um administrador com sessão aberta no backoffice
não pode, por isso, vender sem se identificar com o PIN: senão a venda
entrava na caixa sem dono e o fecho deixava de responsabilizar ninguém.

Regra 2 da spec (§7.1), aplicada em `entrar`: a unicidade do PIN não é
garantida por índice (bcrypt tem sal — ver faturacao/pins.py e
faturacao/db.py). A verificação no servidor, em utilizadores.py, cobre criar
e mudar PIN, mas não cobre alguém ser movido de loja ou reactivado. Por
isso a entrada busca TODOS os operadores activos cujo âmbito de loja inclui
a loja do dispositivo, verifica um a um, e:
- 0 correspondências → 401 genérico (não diz se o PIN existe nalgum lado)
- 1 correspondência → emite o token de operador
- 2+ correspondências → 409 explícito, NUNCA escolhe a primeira — escolher
  a primeira atribuiria as vendas à pessoa errada e destruía a
  responsabilização do fecho de caixa.

bcrypt custa ~166ms e é síncrono. A entrada compara o PIN contra todos os
operadores activos da loja — com 20 pessoas seriam ~3,3s a bloquear o event
loop do portal INTEIRO (RH, Financeiro, picagem de ponto incluídos). Por
isso cada verificação corre em `asyncio.to_thread`, nunca directamente no
loop.
"""
import hashlib
import os
import secrets
import uuid
from asyncio import to_thread
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .pins import pin_valido

router = APIRouter()

# Segredo próprio dos tokens de operador — deliberadamente DIFERENTE do
# JWT_SECRET de gestão (auth.py). Não é só para não colidir por acaso: é a
# garantia de que um JWT de gestão nunca decodifica aqui, mesmo que alguém
# tente usá-lo num cabeçalho X-Operator-Token.
POS_JWT_SECRET = os.environ.get("POS_JWT_SECRET", "faturacao-pos-secret-key-2026")
_ALGORITMO = "HS256"
_TIPO_TOKEN_OPERADOR = "operador_pos"
_TTL_OPERADOR_HORAS = 12
_TTL_CODIGO_MINUTOS = 15

_MSG_PIN_INCORRECTO = "PIN incorrecto."
_MSG_PIN_EM_CONFLITO = "PIN em conflito, contacte o gestor."
_MSG_CODIGO_INVALIDO = "Código de emparelhamento inválido ou expirado."
_MSG_DISPOSITIVO_INVALIDO = "Dispositivo não emparelhado."
_MSG_SESSAO_OPERADOR_INVALIDA = "Sessão de operador inválida ou expirada."


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(valor: str) -> str:
    # sha256 chega aqui: o código/token já tem entropia própria (uso único
    # com expiração curta, ou 256 bits de secrets.token_urlsafe) — ao
    # contrário do PIN de 4 dígitos (10 000 combinações), não há o problema
    # de espaço de procura pequeno que obriga o bcrypt.
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


class PedidoCodigo(BaseModel):
    loja_id: str


class PedidoEmparelhar(BaseModel):
    codigo: str = Field(min_length=1)


class PedidoEntrar(BaseModel):
    pin: str


@router.post("/dispositivos-pos", status_code=201)
async def gerar_codigo_emparelhamento(dados: PedidoCodigo, _: dict = Depends(gestor_atual)) -> dict:
    """Rota de gestão (exige gestor_atual): gera um código de emparelhamento
    de uso único para uma loja. O gestor lê este código ao PC da loja, que o
    troca por um token de dispositivo em POST /pos/emparelhar."""
    db = obter_db()
    if not await db[COLECOES["lojas"]].find_one({"id": dados.loja_id}):
        raise HTTPException(status_code=404, detail="Loja não encontrada")

    codigo = secrets.token_hex(4).upper()
    doc = {
        "id": str(uuid.uuid4()),
        "loja_id": dados.loja_id,
        "codigo_hash": _hash_token(codigo),
        "estado": "pendente",
        "criado_em": _agora().isoformat(),
        "expira_em": (_agora() + timedelta(minutes=_TTL_CODIGO_MINUTOS)).isoformat(),
    }
    await db[COLECOES["dispositivos"]].insert_one(dict(doc))
    return {"codigo": codigo, "expira_em": doc["expira_em"]}


@router.post("/pos/emparelhar")
async def emparelhar(dados: PedidoEmparelhar) -> dict:
    """Troca um código de emparelhamento válido por um token de dispositivo.

    Sem Depends de propósito: é o próprio bootstrap da cadeia de
    autenticação do POS — o dispositivo ainda não tem nenhum token neste
    momento. A guarda aqui não é uma dependência do FastAPI, é o código em
    si: de uso único (o estado passa a "activo" e deixa de casar com
    {"estado": "pendente"}), com expiração curta, e comparado por hash
    (nunca em claro). Ver test_protecao_rotas.py para a excepção documentada
    e test_pos_auth.py para os testes desta guarda."""
    db = obter_db()
    codigo_normalizado = dados.codigo.strip().upper()
    disp = await db[COLECOES["dispositivos"]].find_one(
        {"codigo_hash": _hash_token(codigo_normalizado), "estado": "pendente"}
    )
    if not disp or datetime.fromisoformat(disp["expira_em"]) < _agora():
        raise HTTPException(status_code=401, detail=_MSG_CODIGO_INVALIDO)

    token = secrets.token_urlsafe(32)
    await db[COLECOES["dispositivos"]].update_one(
        {"id": disp["id"]},
        {"$set": {
            "estado": "activo",
            "token_hash": _hash_token(token),
            "emparelhado_em": _agora().isoformat(),
        }},
    )
    return {"device_token": token, "loja_id": disp["loja_id"]}


async def dispositivo_atual(x_device_token: Optional[str] = Header(default=None)) -> Dict:
    """Dependência das rotas do POS que só precisam do dispositivo (ainda
    sem operador identificado) — usa-se directamente em /pos/entrar."""
    if not x_device_token:
        raise HTTPException(status_code=401, detail=_MSG_DISPOSITIVO_INVALIDO)
    db = obter_db()
    disp = await db[COLECOES["dispositivos"]].find_one(
        {"token_hash": _hash_token(x_device_token), "estado": "activo"}
    )
    if not disp:
        raise HTTPException(status_code=401, detail=_MSG_DISPOSITIVO_INVALIDO)
    return disp


def _ambito_bate_com_loja(lojas_do_operador: List[str], loja_id: str) -> bool:
    """Lista vazia = administrador, entra em qualquer loja (mesma convenção
    de utilizadores.py::_sobrepoe_lojas)."""
    return not lojas_do_operador or loja_id in lojas_do_operador


@router.post("/pos/entrar")
async def entrar(dados: PedidoEntrar, dispositivo: Dict = Depends(dispositivo_atual)) -> dict:
    db = obter_db()
    loja_id = dispositivo["loja_id"]

    activos = await db[COLECOES["utilizadores"]].find({"ativo": True}).to_list(1000)
    candidatos = [u for u in activos if _ambito_bate_com_loja(u.get("lojas") or [], loja_id)]

    correspondencias = []
    for u in candidatos:
        # Fora do event loop: ver docstring do módulo — 20 candidatos a
        # ~166ms cada, em série no loop, travariam o portal inteiro.
        if await to_thread(pin_valido, dados.pin, u.get("pin_hash")):
            correspondencias.append(u)

    if not correspondencias:
        raise HTTPException(status_code=401, detail=_MSG_PIN_INCORRECTO)
    if len(correspondencias) > 1:
        raise HTTPException(status_code=409, detail=_MSG_PIN_EM_CONFLITO)

    operador = correspondencias[0]
    agora = _agora()
    payload = {
        "operador_id": operador["id"],
        "nome": operador.get("nome"),
        "perfil": operador.get("perfil"),
        "loja_id": loja_id,
        "tipo": _TIPO_TOKEN_OPERADOR,
        "iat": int(agora.timestamp()),
        "exp": int((agora + timedelta(hours=_TTL_OPERADOR_HORAS)).timestamp()),
    }
    token = jwt.encode(payload, POS_JWT_SECRET, algorithm=_ALGORITMO)
    return {
        "operator_token": token,
        "operador": {
            "id": operador["id"],
            "nome": operador.get("nome"),
            "perfil": operador.get("perfil"),
        },
    }


async def operador_atual(x_operator_token: Optional[str] = Header(default=None)) -> Dict:
    """Dependência das rotas do POS que precisam de saber quem está a
    vender (abrir/fechar caixa, vender — Tasks seguintes do Plano 2A)."""
    if not x_operator_token:
        raise HTTPException(status_code=401, detail=_MSG_SESSAO_OPERADOR_INVALIDA)
    try:
        payload = jwt.decode(x_operator_token, POS_JWT_SECRET, algorithms=[_ALGORITMO])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail=_MSG_SESSAO_OPERADOR_INVALIDA)
    if payload.get("tipo") != _TIPO_TOKEN_OPERADOR:
        raise HTTPException(status_code=401, detail=_MSG_SESSAO_OPERADOR_INVALIDA)
    return payload
