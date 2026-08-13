"""Descodificação do JWT do backoffice. Mesmo segredo e mesmo formato do server.py,
mas implementado aqui para o pacote não depender do server.py (import circular).
"""
import os

import jwt
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET", "segredo-de-teste")

from faturacao.auth import PERFIS_GESTAO, descodificar_token, exigir_gestao


def _token(**extra):
    dados = {"user_id": "u1", "email": "a@b.pt", "role": "admin"}
    dados.update(extra)
    return jwt.encode(dados, os.environ["JWT_SECRET"], algorithm="HS256")


def test_descodifica_token_valido():
    assert descodificar_token(_token())["email"] == "a@b.pt"


def test_token_com_segredo_errado_e_recusado():
    mau = jwt.encode({"user_id": "u1"}, "outro-segredo", algorithm="HS256")
    with pytest.raises(HTTPException) as e:
        descodificar_token(mau)
    assert e.value.status_code == 401


def test_token_lixo_e_recusado():
    with pytest.raises(HTTPException) as e:
        descodificar_token("isto-nao-e-um-token")
    assert e.value.status_code == 401


def test_perfis_de_gestao_sao_os_do_repositorio():
    assert PERFIS_GESTAO == ["admin", "gerente", "contabilista"]


def test_colaborador_nao_passa_na_gestao():
    with pytest.raises(HTTPException) as e:
        exigir_gestao({"role": "colaborador"})
    assert e.value.status_code == 403


def test_admin_passa_na_gestao():
    assert exigir_gestao({"role": "admin"})["role"] == "admin"


def test_sem_jwt_secret_no_ambiente_aceita_token_do_valor_por_omissao(monkeypatch):
    """Trava a paridade com o server.py (linha 52): quando JWT_SECRET não está
    definido no ambiente, o server.py cai para o valor por omissão
    'hr-system-secret-key-2024' e continua a emitir tokens válidos com ele. Se o
    auth.py não usar o mesmo valor por omissão, este teste falha (antes só dava
    KeyError, um 500 não tratado, em vez de aceitar o token do portal).
    """
    monkeypatch.delenv("JWT_SECRET", raising=False)
    token = jwt.encode(
        {"user_id": "u1", "email": "a@b.pt", "role": "admin"},
        "hr-system-secret-key-2024",
        algorithm="HS256",
    )
    assert descodificar_token(token)["email"] == "a@b.pt"
