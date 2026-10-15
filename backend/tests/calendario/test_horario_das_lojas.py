"""O horário das lojas nos Locais.

Só as lojas com `horario` vão entrar no calendário (a Pizzaria e os escritórios ficam
de fora sem ninguém os esconder); `aberta_desde` esconde uma loja antes de abrir. Aqui
prende-se o que o servidor aceita e recusa; mais abaixo (Tarefa 2), o que fica gravado.
"""
from datetime import date

import pytest
from pydantic import ValidationError

import server

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
