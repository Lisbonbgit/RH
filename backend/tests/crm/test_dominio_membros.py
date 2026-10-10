"""Regras puras dos membros do CRM (crm/dominio/membros.py).

Os três perfis do CRM (desenho §4.2; dossiê §4) e o "tipo de conta" do portal
que a lista de membros e de candidatos mostra (T1.6). O papel no portal não
conta para o CRM: é só uma etiqueta para o admin saber quem está a escolher.
"""
import pytest

from crm.dominio import membros
from crm.dominio.membros import PERFIS, erro_perfil, tipo_conta
from faturacao.auth import PERFIS_GESTAO

MENSAGEM = "Escolha um perfil: admin, utilizador ou motorista."


def test_os_perfis_do_crm_sao_tres_por_esta_ordem():
    assert PERFIS == ("admin", "utilizador", "motorista")


def test_a_mensagem_do_perfil_e_a_do_contrato():
    assert membros.MENSAGEM_PERFIL == MENSAGEM


@pytest.mark.parametrize("perfil", ["admin", "utilizador", "motorista"])
def test_um_perfil_conhecido_nao_tem_erro(perfil):
    assert erro_perfil(perfil) is None


@pytest.mark.parametrize(
    "perfil",
    ["Admin", "ADMIN", " admin", "admin ", "", None, 1, True, ["admin"], {"perfil": "admin"}, "gestor"],
    ids=[
        "maiuscula",
        "tudo em maiusculas",
        "espaco antes",
        "espaco depois",
        "vazio",
        "null",
        "numero",
        "verdadeiro",
        "lista",
        "objeto",
        "papel do portal",
    ],
)
def test_um_perfil_fora_da_lista_da_a_mensagem(perfil):
    assert erro_perfil(perfil) == MENSAGEM


@pytest.mark.parametrize(
    "papel, tipo",
    [
        ("admin", "gestor"),
        ("gerente", "gestor"),
        ("contabilista", "gestor"),
        ("colaborador", "colaborador"),
        (None, None),
    ],
    ids=["admin", "gerente", "contabilista", "colaborador", "sem papel"],
)
def test_tipo_de_conta_a_partir_do_papel_do_portal(papel, tipo):
    assert tipo_conta(papel) == tipo


def test_todos_os_papeis_de_gestao_do_portal_contam_como_gestor():
    # A mesma lista que o portal usa (faturacao.auth.PERFIS_GESTAO, cópia do
    # MANAGER_ROLES do server.py): se o portal ganhar um papel de gestão, o
    # CRM passa a contá-lo como gestor sem mudar nada aqui.
    assert all(tipo_conta(papel) == "gestor" for papel in PERFIS_GESTAO)


def test_um_papel_desconhecido_conta_como_colaborador_como_no_portal():
    # O portal manda para a área do colaborador qualquer papel que não seja
    # de gestão (App.js: ProtectedRoute/RoleBasedRedirect).
    assert tipo_conta("estagiario") == "colaborador"
    assert tipo_conta("Gerente") == "colaborador"


@pytest.mark.parametrize("papel", [1, True, ["gerente"], {"role": "admin"}], ids=["numero", "verdadeiro", "lista", "objeto"])
def test_um_papel_que_nao_e_texto_nao_tem_tipo(papel):
    assert tipo_conta(papel) is None
