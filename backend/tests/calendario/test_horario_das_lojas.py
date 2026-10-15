"""O horário das lojas nos Locais.

Só as lojas com `horario` vão entrar no calendário (a Pizzaria e os escritórios ficam
de fora sem ninguém os esconder); `aberta_desde` esconde uma loja antes de abrir. Aqui
prende-se o que o servidor aceita e recusa; mais abaixo (Tarefa 2), o que fica gravado.
"""
from datetime import date

import pytest
from pydantic import ValidationError

import server

from .apoio import ADMIN, corre

# Belém: 11h30–19h, ao domingo até às 20h, fechada à terça (a tabela do dono).
BELEM = {
    "abre": "11:30", "fecha": "19:00",
    "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}],
    "fechada": [1],
}


def _loja(**extra):
    corpo = {"name": "L'Açaí Belém", "company_id": "c1"}
    corpo.update(extra)
    return server.LocationCreate.model_validate(corpo)


def test_o_horario_de_belem_passa_e_fica_igual():
    assert server.HorarioLoja.model_validate(BELEM).model_dump() == BELEM


def test_os_dias_fechados_ficam_por_ordem():
    horario = server.HorarioLoja.model_validate({**BELEM, "excecoes": [], "fechada": [3, 1]})
    assert horario.fechada == [1, 3]


@pytest.mark.parametrize("mudanca, mensagem", [
    ({"abre": "19:00", "fecha": "11:30"}, "abrir antes de fechar"),
    ({"abre": "11:30", "fecha": "11:30"}, "abrir antes de fechar"),
    ({"abre": "9:00"}, "HH:MM"),
    ({"fecha": "24:00"}, "HH:MM"),
    ({"excecoes": [{"dia": 7, "abre": "11:30", "fecha": "20:00"}]}, "Dia inválido"),
    ({"excecoes": [{"dia": 6, "abre": "20:00", "fecha": "11:30"}]}, "abrir antes de fechar"),
    ({"excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"},
                   {"dia": 6, "abre": "12:00", "fecha": "20:00"}]}, "repetido nas exceções"),
    ({"fechada": [1, 1]}, "repetido nos dias em que fecha"),
    ({"fechada": [-1]}, "Dia inválido"),
    ({"fechada": [6]}, "outro horário e estar fechado"),
])
def test_horarios_que_o_servidor_recusa(mudanca, mensagem):
    with pytest.raises(ValidationError, match=mensagem):
        server.HorarioLoja.model_validate({**BELEM, **mudanca})


def test_a_data_de_abertura():
    assert _loja(aberta_desde="2026-10-24").aberta_desde == date(2026, 10, 24)
    assert _loja(aberta_desde="").aberta_desde is None      # o <input type="date"> vazio
    assert _loja(aberta_desde=None).aberta_desde is None
    with pytest.raises(ValidationError):
        _loja(aberta_desde="2026-02-30")


def test_a_pagina_antiga_nao_manda_os_campos_novos_e_o_servidor_sabe_disso():
    velha = _loja(address="Rua X")
    assert velha.horario is None and velha.aberta_desde is None
    assert not {"horario", "aberta_desde"} & velha.model_fields_set
    nova = _loja(horario=None, aberta_desde=None)
    assert {"horario", "aberta_desde"} <= nova.model_fields_set


def test_um_horario_invalido_nem_chega_a_rota():
    with pytest.raises(ValidationError, match="abrir antes de fechar"):
        _loja(horario={**BELEM, "fecha": "10:00"})


# ---- Tarefa 2: o que fica gravado (contra um mongod real, ver conftest) ----

ALFRAGIDE = {"abre": "10:00", "fecha": "23:00", "excecoes": [], "fechada": []}


@pytest.fixture
def empresa(base):
    corre(base.companies.insert_one({"id": "c1", "name": "L'Açaí", "created_at": "2026-01-01T00:00:00+00:00"}))
    return base


def _gravada(base, location_id):
    return corre(base.locations.find_one({"id": location_id}, {"_id": 0}))


def test_o_post_grava_o_horario_e_a_data_de_abertura_e_o_get_devolve_os(empresa):
    criada = corre(server.create_location(_loja(horario=BELEM, aberta_desde="2026-10-24"), current_user=ADMIN))
    assert criada.horario == BELEM and criada.aberta_desde == "2026-10-24"
    gravada = _gravada(empresa, criada.id)
    assert gravada["horario"] == BELEM and gravada["aberta_desde"] == "2026-10-24"
    [lida] = corre(server.get_locations(current_user=ADMIN))
    assert lida.horario == BELEM and lida.aberta_desde == "2026-10-24"


def test_um_put_da_pagina_antiga_nao_apaga_o_horario(empresa):
    criada = corre(server.create_location(_loja(horario=BELEM, aberta_desde="2026-10-24"), current_user=ADMIN))
    # A página antiga, em cache no browser, manda o formulário SEM os campos novos.
    corre(server.update_location(criada.id, _loja(name="L'Açaí Belém (renomeada)", address="Rua Nova"),
                                 current_user=ADMIN))
    gravada = _gravada(empresa, criada.id)
    assert gravada["name"] == "L'Açaí Belém (renomeada)" and gravada["address"] == "Rua Nova"
    assert gravada["horario"] == BELEM and gravada["aberta_desde"] == "2026-10-24"


def test_o_formulario_novo_muda_e_tambem_tira_o_horario(empresa):
    criada = corre(server.create_location(_loja(horario=BELEM, aberta_desde="2026-10-24"), current_user=ADMIN))
    devolvida = corre(server.update_location(criada.id, _loja(horario=ALFRAGIDE, aberta_desde=None),
                                             current_user=ADMIN))
    assert devolvida.horario == ALFRAGIDE and devolvida.aberta_desde is None
    assert _gravada(empresa, criada.id)["horario"] == ALFRAGIDE
    corre(server.update_location(criada.id, _loja(horario=None, aberta_desde=None), current_user=ADMIN))
    gravada = _gravada(empresa, criada.id)
    assert gravada["horario"] is None and gravada["aberta_desde"] is None


def test_um_local_antigo_sem_os_campos_le_se_como_sempre(empresa):
    corre(empresa.locations.insert_one({"id": "l-velho", "name": "Escritório", "company_id": "c1", "address": None}))
    [lida] = corre(server.get_locations(current_user=ADMIN))
    assert lida.name == "Escritório" and lida.horario is None and lida.aberta_desde is None
