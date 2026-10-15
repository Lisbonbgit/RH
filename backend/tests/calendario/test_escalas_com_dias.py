"""As Escalas ganham loja e horas por dia — e o que já existia não muda.

Cada dia de uma escala diz a loja (vazia = a loja da ficha do colaborador) e,
opcionalmente, as horas (vazias = o horário da loja nesse dia). O `work_days` tem
três leitores sem testes (o saldo de férias, o «Em falta» do painel e o lembrete do
ponto — desenho, «medido 2»); por isso, com `dias`, o servidor deriva `work_days`
deles e põe o MESMO valor no modelo e nas atribuições, o `start_time` fica, e um PUT
da página antiga não apaga os `dias`.
"""
import pytest
from pydantic import ValidationError

import server

# A Joana: Amadora seg/ter, Oeiras qua, Algueirão qui/sex (com horas à quinta, para
# haver um dia com horas). É a forma exacta que o formulário manda.
JOANA = [
    {"dia": 0, "location_id": "amadora", "inicio": None, "fim": None},
    {"dia": 1, "location_id": "amadora", "inicio": None, "fim": None},
    {"dia": 2, "location_id": "oeiras", "inicio": None, "fim": None},
    {"dia": 3, "location_id": "algueirao", "inicio": "13:00", "fim": "22:00"},
    {"dia": 4, "location_id": "algueirao", "inicio": None, "fim": None},
]


def _escala(**extra):
    corpo = {"name": "Escala Joana", "workDays": [0, 1, 2, 3, 4], "startTime": "13:00"}
    corpo.update(extra)
    return server.WorkScheduleTemplateCreate.model_validate(corpo)


def test_um_dia_com_loja_e_horas():
    dia = server.DiaDaEscala.model_validate(JOANA[3])
    assert dia.model_dump() == JOANA[3]


def test_vazio_quer_dizer_loja_da_ficha_e_horario_da_loja():
    dia = server.DiaDaEscala.model_validate({"dia": 0, "location_id": "", "inicio": "", "fim": ""})
    assert dia.model_dump() == {"dia": 0, "location_id": None, "inicio": None, "fim": None}


@pytest.mark.parametrize("dia, mensagem", [
    ({"dia": 7}, "Dia inválido"),
    ({"dia": 0, "inicio": "13:00"}, "as duas"),
    ({"dia": 0, "fim": "22:00"}, "as duas"),
    ({"dia": 0, "inicio": "22:00", "fim": "13:00"}, "antes da saída"),
    ({"dia": 0, "inicio": "13:00", "fim": "13:00"}, "antes da saída"),
    ({"dia": 0, "inicio": "9:00", "fim": "13:00"}, "HH:MM"),
])
def test_dias_que_o_servidor_recusa(dia, mensagem):
    with pytest.raises(ValidationError, match=mensagem):
        server.DiaDaEscala.model_validate(dia)


def test_o_mesmo_dia_duas_vezes_e_recusado():
    with pytest.raises(ValidationError, match="Dia repetido"):
        _escala(dias=[{"dia": 2}, {"dia": 2, "location_id": "oeiras"}])


def test_com_dias_a_escala_traz_os():
    escala = _escala(dias=JOANA)
    assert [d.model_dump() for d in escala.dias] == JOANA
    assert "dias" in escala.model_fields_set


def test_sem_dias_a_escala_fica_como_sempre():
    escala = _escala()
    assert escala.dias is None
    assert "dias" not in escala.model_fields_set
