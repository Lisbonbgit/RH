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
