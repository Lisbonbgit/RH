"""As regras dos contactos de uma loja (crm/dominio/contactos.py; desenho dos
contactos §3, "Regras" e "Último contacto").

Sem base nem relógio: o `hoje` e os dias entram como `date`. As rotas estão em
test_contactos.py.
"""
import copy
import uuid
from datetime import date

import pytest

from crm.dominio.contactos import (
    DATA_MINIMA,
    MENSAGEM_CLIENT_UUID,
    MENSAGEM_DATA,
    MENSAGEM_DATA_FORA,
    MENSAGEM_RESUMO,
    MENSAGEM_TIPO,
    RESUMO_MAXIMO,
    TIPOS_CONTACTO,
    TIPOS_ULTIMA_INTERACAO,
    TIPOS_VISITA_OU_ENTREGA,
    alteracao,
    criacao,
    mudancas,
    numerados,
    pode_alterar,
    ultimos_instantes,
)

HOJE = date(2026, 11, 7)
UUID = "5b0c6f1e-2d3a-4b8c-9e7f-0a1b2c3d4e5f"


def corpo(**outros):
    """Um corpo válido do POST, com as alterações por cima."""
    return {"tipo": "visita", "data": "2026-11-05", "resumo": "Falou-se do verão.", **outros}


def erros_de(**outros):
    return list(criacao(corpo(**outros), HOJE)[1].items())


# --- As constantes ---


def test_os_tipos_sao_os_do_desenho():
    assert TIPOS_CONTACTO == ("visita", "chamada", "mensagem")


def test_a_mensagem_conta_para_o_ultimo_contacto_e_nao_para_a_ultima_visita():
    """A exceção ao §4.2 do desenho original: a `mensagem` também atualiza
    `ultima_interacao_em`. Nem as notas nem as mudanças de fase contam."""
    assert TIPOS_ULTIMA_INTERACAO == ("visita", "chamada", "mensagem", "amostra", "entrega")
    assert TIPOS_VISITA_OU_ENTREGA == ("visita", "amostra", "entrega")


def test_os_limites_sao_os_do_desenho():
    assert DATA_MINIMA == date(2000, 1, 1)
    assert RESUMO_MAXIMO == 5000


# --- criacao ---


def test_um_contacto_valido_normaliza_se():
    dados, erros = criacao(corpo(resumo="  O que foi falado.\nPróximo passo.  ", client_uuid=UUID), HOJE)

    assert erros == {}
    assert list(dados.items()) == [
        ("tipo", "visita"),
        ("data", date(2026, 11, 5)),
        ("resumo", "O que foi falado.\nPróximo passo."),
        ("client_uuid", UUID),
    ]


@pytest.mark.parametrize("tipo", TIPOS_CONTACTO)
def test_cada_tipo_e_aceite(tipo):
    dados, erros = criacao(corpo(tipo=tipo), HOJE)
    assert erros == {}
    assert dados["tipo"] == tipo


@pytest.mark.parametrize("valor", [
    None, "", "Visita", " visita", "visita ", "nota", "amostra", "entrega", "mudanca_fase", 1, True, ["visita"],
    {"$ne": None},
], ids=[
    "null", "vazio", "maiúscula", "espaço antes", "espaço depois", "nota", "amostra", "entrega", "mudança de fase",
    "número", "booleano", "lista", "operador do Mongo",
])
def test_um_tipo_que_nao_e_dos_tres_da_erro_no_campo(valor):
    assert erros_de(tipo=valor) == [("tipo", MENSAGEM_TIPO)]


def test_a_data_pode_ser_hoje_passada_e_a_primeira_do_limite():
    for texto, dia in (("2026-11-07", HOJE), ("2026-11-06", date(2026, 11, 6)), ("2000-01-01", DATA_MINIMA)):
        dados, erros = criacao(corpo(data=texto), HOJE)
        assert erros == {}
        assert dados["data"] == dia


@pytest.mark.parametrize("valor", ["2026-11-08", "2027-01-01", "1999-12-31"], ids=["amanhã", "ano seguinte", "antes de 2000"])
def test_uma_data_fora_do_limite_da_erro_no_campo(valor):
    assert erros_de(data=valor) == [("data", MENSAGEM_DATA_FORA)]


@pytest.mark.parametrize("valor", [
    None, "", "ontem", "7/11/2026", "2026-11-7", "2026-02-30", "2026-11-05T12:00:00Z", "2026-11-05\n", 20261105, True,
    ["2026-11-05"],
], ids=[
    "null", "vazia", "palavra", "outro formato", "sem zero", "30 de fevereiro", "instante", "fim de linha", "número",
    "booleano", "lista",
])
def test_uma_data_que_nao_e_um_dia_da_erro_no_campo(valor):
    assert erros_de(data=valor) == [("data", MENSAGEM_DATA)]


@pytest.mark.parametrize("valor", [None, "", "   ", " ﻿　 "], ids=["null", "vazio", "espaços", "espaços Unicode"])
def test_o_resumo_e_obrigatorio_depois_de_aparado(valor):
    assert erros_de(resumo=valor) == [("resumo", MENSAGEM_RESUMO)]


def test_o_resumo_vai_ate_5000_caracteres():
    assert criacao(corpo(resumo="é" * 5000), HOJE)[1] == {}
    assert criacao(corpo(resumo=" " + "é" * 5000 + " "), HOJE)[0]["resumo"] == "é" * 5000
    assert erros_de(resumo="é" * 5001) == [("resumo", "O resumo tem no máximo 5000 caracteres.")]


@pytest.mark.parametrize("valor", [1, True, ["x"], {"$ne": ""}], ids=["número", "booleano", "lista", "operador"])
def test_um_resumo_que_nao_e_texto_da_erro_no_campo(valor):
    assert erros_de(resumo=valor) == [("resumo", "Tem de ser texto.")]


def test_sem_client_uuid_fica_null():
    assert criacao(corpo(), HOJE)[0]["client_uuid"] is None
    assert criacao(corpo(client_uuid=None), HOJE)[0]["client_uuid"] is None


@pytest.mark.parametrize("valor", [
    "", "x", UUID.upper(), f" {UUID}", f"{UUID}\n", "5b0c6f1e-2d3a-1b8c-9e7f-0a1b2c3d4e5f", 1, True, [UUID], {"$ne": None},
], ids=[
    "vazio", "texto", "maiúsculas", "espaço", "fim de linha", "outra versão", "número", "booleano", "lista",
    "operador do Mongo",
])
def test_um_client_uuid_que_nao_e_um_uuid4_da_erro_no_campo(valor):
    assert erros_de(client_uuid=valor) == [("client_uuid", MENSAGEM_CLIENT_UUID)]


def test_o_uuid_gerado_pelo_python_e_aceite():
    valor = str(uuid.uuid4())
    assert criacao(corpo(client_uuid=valor), HOJE)[0]["client_uuid"] == valor


def test_sem_nada_diz_o_que_falta_pela_ordem_do_bloco():
    assert list(criacao({}, HOJE)[1].items()) == [
        ("tipo", MENSAGEM_TIPO),
        ("data", MENSAGEM_DATA),
        ("resumo", MENSAGEM_RESUMO),
    ]


def test_as_outras_chaves_ignoram_se():
    dados, erros = criacao(corpo(id="x", loja_id="y", utilizador_id="z", paragem_id="p", ocorrida_em="w"), HOJE)
    assert erros == {}
    assert list(dados) == ["tipo", "data", "resumo", "client_uuid"]


def test_nao_mexe_no_corpo_recebido():
    recebido = corpo(resumo="  x  ", client_uuid=UUID)
    copia = copy.deepcopy(recebido)
    criacao(recebido, HOJE)
    alteracao(recebido, HOJE)
    assert recebido == copia


# --- alteracao ---


def test_o_corpo_vazio_nao_tem_dados_nem_erros():
    assert alteracao({}, HOJE) == ({}, {})


def test_so_as_chaves_enviadas_pela_ordem_do_bloco():
    dados, erros = alteracao({"resumo": " novo ", "tipo": "chamada"}, HOJE)
    assert erros == {}
    assert list(dados.items()) == [("tipo", "chamada"), ("resumo", "novo")]


def test_a_data_le_se_como_um_dia():
    assert alteracao({"data": "2026-11-01"}, HOJE) == ({"data": date(2026, 11, 1)}, {})


@pytest.mark.parametrize("campo, valor, mensagem", [
    ("tipo", None, MENSAGEM_TIPO),
    ("tipo", "", MENSAGEM_TIPO),
    ("data", None, MENSAGEM_DATA),
    ("data", "", MENSAGEM_DATA),
    ("data", "2026-11-08", MENSAGEM_DATA_FORA),
    ("resumo", None, MENSAGEM_RESUMO),
    ("resumo", "", MENSAGEM_RESUMO),
    ("resumo", "   ", MENSAGEM_RESUMO),
])
def test_uma_chave_presente_com_null_ou_vazio_e_erro_do_campo(campo, valor, mensagem):
    assert alteracao({campo: valor}, HOJE)[1] == {campo: mensagem}


def test_o_client_uuid_nao_se_muda_num_patch():
    assert alteracao({"client_uuid": "nem sequer um uuid"}, HOJE) == ({}, {})


# --- pode_alterar ---


def _linha(**outros):
    return {"id": "c1", "utilizador_id": "u-rui", "paragem_id": None, **outros}


def test_quem_escreveu_pode_alterar():
    assert pode_alterar(_linha(), "utilizador", "u-rui") is True


def test_outro_utilizador_nao_pode():
    assert pode_alterar(_linha(), "utilizador", "u-ana") is False


def test_um_administrador_do_crm_pode_sem_ter_escrito():
    assert pode_alterar(_linha(), "admin", "u-ana") is True


@pytest.mark.parametrize("perfil, user_id", [("admin", "u-ana"), ("utilizador", "u-rui")], ids=["admin", "autor"])
def test_um_registo_de_uma_paragem_ninguem_o_altera_do_escritorio(perfil, user_id):
    assert pode_alterar(_linha(paragem_id="p1"), perfil, user_id) is False


def test_uma_linha_sem_paragem_id_conta_como_da_ficha():
    linha = {"id": "c1", "utilizador_id": "u-rui"}
    assert pode_alterar(linha, "utilizador", "u-rui") is True


# --- mudancas ---


LINHA = {"tipo": "visita", "notas": "Falou-se do verão."}
DIA = date(2026, 11, 5)


@pytest.mark.parametrize("dados", [
    {},
    {"tipo": "visita"},
    {"data": DIA},
    {"resumo": "Falou-se do verão."},
    {"tipo": "visita", "data": DIA, "resumo": "Falou-se do verão."},
], ids=["vazio", "o mesmo tipo", "o mesmo dia", "o mesmo resumo", "tudo igual"])
def test_sem_nada_diferente_nao_ha_mudancas(dados):
    assert mudancas(LINHA, DIA, dados) == {}


def test_so_ficam_os_valores_diferentes():
    dados = {"tipo": "chamada", "data": DIA, "resumo": "Outro."}
    assert mudancas(LINHA, DIA, dados) == {"tipo": "chamada", "resumo": "Outro."}
    assert mudancas(LINHA, DIA, {"data": date(2026, 11, 4)}) == {"data": date(2026, 11, 4)}


# --- numerados ---


def _contacto(id_, ocorrida_em, criado_em="2026-11-07T10:00:00Z"):
    return {"id": id_, "ocorrida_em": ocorrida_em, "criado_em": criado_em}


def _ordem(linhas):
    return [(numero, linha["id"]) for numero, linha in numerados(linhas)]


def test_sem_contactos_a_lista_vem_vazia():
    assert numerados([]) == []


def test_o_mais_recente_vem_primeiro_e_o_mais_antigo_tem_o_numero_1():
    linhas = [
        _contacto("b", "2026-11-05T12:00:00Z"),
        _contacto("c", "2026-11-06T12:00:00Z"),
        _contacto("a", "2026-11-04T12:00:00Z"),
    ]
    assert _ordem(linhas) == [(3, "c"), (2, "b"), (1, "a")]


def test_um_contacto_antigo_renumera_os_outros():
    linhas = [_contacto("a", "2026-11-04T12:00:00Z"), _contacto("b", "2026-11-05T12:00:00Z")]
    assert _ordem(linhas) == [(2, "b"), (1, "a")]
    assert _ordem([*linhas, _contacto("antigo", "2026-10-01T11:00:00Z")]) == [(3, "b"), (2, "a"), (1, "antigo")]


def test_no_mesmo_instante_desempata_pelo_criado_em_e_depois_pelo_id():
    linhas = [
        _contacto("c", "2026-11-05T12:00:00Z", "2026-11-06T09:00:00Z"),
        _contacto("b", "2026-11-05T12:00:00Z", "2026-11-05T09:00:00Z"),
        _contacto("a", "2026-11-05T12:00:00Z", "2026-11-06T09:00:00Z"),
    ]
    assert _ordem(linhas) == [(3, "c"), (2, "a"), (1, "b")]


def test_uma_linha_sem_criado_em_ordena_se_na_mesma():
    """A F4 pode gravar visitas sem o `criado_em`: contam como as mais antigas do instante."""
    linhas = [_contacto("a", "2026-11-05T12:00:00Z"), {"id": "z", "ocorrida_em": "2026-11-05T12:00:00Z"}]
    assert _ordem(linhas) == [(2, "a"), (1, "z")]


def test_nao_mexe_na_lista_recebida():
    linhas = [_contacto("b", "2026-11-05T12:00:00Z"), _contacto("a", "2026-11-04T12:00:00Z")]
    copia = copy.deepcopy(linhas)
    numerados(linhas)
    assert linhas == copia


# --- ultimos_instantes ---


INSTANTE = "2026-11-05T12:00:00Z"


def test_a_visita_sobe_os_dois_campos():
    assert ultimos_instantes("visita", INSTANTE) == {
        "ultima_interacao_em": INSTANTE, "ultima_visita_ou_entrega_em": INSTANTE,
    }


@pytest.mark.parametrize("tipo", ["chamada", "mensagem"])
def test_a_chamada_e_a_mensagem_so_sobem_o_ultimo_contacto(tipo):
    assert ultimos_instantes(tipo, INSTANTE) == {"ultima_interacao_em": INSTANTE}

