"""Autenticação do backoffice do módulo Faturação.

Repete ~15 linhas do server.py de propósito: se importasse o server.py, e o
server.py importa este pacote para o montar, tínhamos um import circular.
Mesmo JWT_SECRET, mesmo algoritmo, mesmo formato de payload.
"""
import os
from typing import Dict

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from faturacao.db import obter_db

# Os mesmos papéis do server.py (MANAGER_ROLES). Ver server.py:62.
PERFIS_GESTAO = ["admin", "gerente", "contabilista"]

# Valor por omissão do JWT_SECRET, copiado de server.py:52
# (`os.environ.get('JWT_SECRET', 'hr-system-secret-key-2024')`). A paridade é
# deliberada: se este módulo e o server.py divergirem no valor por omissão,
# o portal (server.py) continua a emitir tokens com a sua própria chave
# assim que JWT_SECRET não estiver definido no ambiente, e este módulo passa
# a recusá-los — ou, como acontecia antes desta constante existir, a rebentar
# com um KeyError não tratado (500) em vez de um 401.
JWT_SECRET_POR_OMISSAO = "hr-system-secret-key-2024"

_seguranca = HTTPBearer(auto_error=True)


def descodificar_token(token: str) -> Dict:
    try:
        segredo = os.environ.get("JWT_SECRET", JWT_SECRET_POR_OMISSAO)
        return jwt.decode(token, segredo, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")


def exigir_gestao(utilizador: Dict) -> Dict:
    if utilizador.get("role") not in PERFIS_GESTAO:
        raise HTTPException(status_code=403, detail="Sem permissão para esta área")
    return utilizador


async def utilizador_atual(
    credenciais: HTTPAuthorizationCredentials = Depends(_seguranca),
) -> Dict:
    """O papel vem da BASE, não do token: o token vale 24 h e a pessoa pode ter
    sido apagada ou despromovida entretanto (a mesma regra do server.py)."""
    utilizador = descodificar_token(credenciais.credentials)
    doc = await obter_db().users.find_one(
        {"id": utilizador.get("user_id")}, {"_id": 0, "role": 1, "email": 1, "employee_id": 1}
    )
    if not doc:
        raise HTTPException(status_code=401, detail="Sessão terminada")
    utilizador.update(role=doc.get("role"), email=doc.get("email"), employee_id=doc.get("employee_id"))
    return utilizador


async def gestor_atual(utilizador: Dict = Depends(utilizador_atual)) -> Dict:
    return exigir_gestao(utilizador)
