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

from .apoio import ADMIN, corre

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


# ---- Tarefa 4: o que fica gravado e quem o lê (contra um mongod real) ----

def _cria(**extra):
    return corre(server.create_schedule_template(_escala(**extra), current_user=ADMIN))


def _muda(template_id, **extra):
    return corre(server.update_schedule_template(template_id, _escala(**extra), current_user=ADMIN))


def _atribui(base, employee_id, template_id, inicio="2026-01-01"):
    corre(base.employees.update_one(
        {"id": employee_id},
        {"$setOnInsert": {"name": "Pessoa " + employee_id, "company_id": "c1", "location_id": "oeiras"}},
        upsert=True))
    pedido = server.WorkScheduleAssignmentCreate.model_validate(
        {"employeeId": employee_id, "templateId": template_id, "startDate": inicio})
    return corre(server.assign_schedule(pedido, current_user=ADMIN))


def _gravado(base, colecao, doc_id):
    return corre(base[colecao].find_one({"id": doc_id}, {"_id": 0}))


def test_o_post_deriva_os_dias_de_trabalho_dos_dias(base):
    # O formulário manda workDays igual aos dias; mesmo que não mande, valem os `dias`.
    criada = _cria(workDays=[0, 1, 2, 3, 4, 5, 6], dias=JOANA)
    assert criada.work_days == [0, 1, 2, 3, 4]
    assert criada.dias == JOANA
    gravada = _gravado(base, "work_schedule_templates", criada.id)
    assert gravada["work_days"] == [0, 1, 2, 3, 4]
    assert gravada["dias"] == JOANA


def test_o_put_deriva_e_poe_o_mesmo_valor_no_modelo_e_nas_atribuicoes(base):
    criada = _cria()                                   # 5x2 sem dias, como as de hoje
    atribuicao = _atribui(base, "emp-j", criada.id)
    _muda(criada.id, workDays=[6], dias=JOANA[:3])     # workDays de propósito diferente
    assert _gravado(base, "work_schedule_templates", criada.id)["work_days"] == [0, 1, 2]
    assert _gravado(base, "work_schedule_assignments", atribuicao.id)["work_days"] == [0, 1, 2]


def test_o_start_time_fica_e_o_lembrete_do_ponto_le_o_mesmo(base):
    criada = _cria(dias=JOANA)
    _atribui(base, "emp-j", criada.id)
    joana = {"user_id": "u-j", "role": "colaborador", "employee_id": "emp-j"}
    assert corre(server.get_my_schedule(current_user=joana)) == {
        "work_days": [0, 1, 2, 3, 4], "start_time": "13:00", "template_name": "Escala Joana"}
    _muda(criada.id, workDays=[0, 1, 2, 3], dias=JOANA[:4])
    assert corre(server.get_my_schedule(current_user=joana)) == {
        "work_days": [0, 1, 2, 3], "start_time": "13:00", "template_name": "Escala Joana"}


def test_um_put_da_pagina_antiga_nao_apaga_os_dias(base):
    criada = _cria(dias=JOANA)
    _muda(criada.id, name="Escala Joana (renomeada)")   # sem a chave `dias`, como a página antiga
    gravada = _gravado(base, "work_schedule_templates", criada.id)
    assert gravada["name"] == "Escala Joana (renomeada)"
    assert gravada["dias"] == JOANA


def test_uma_escala_antiga_sem_dias_continua_a_ler_se_e_a_gravar_se(base):
    corre(base.work_schedule_templates.insert_one({
        "id": "t-velha", "name": "5x2", "work_days": [0, 1, 2, 3, 4], "start_time": None,
        "created_at": "2026-01-01T00:00:00+00:00"}))
    [lida] = corre(server.get_schedule_templates(current_user=ADMIN))
    assert lida.dias is None and lida.work_days == [0, 1, 2, 3, 4]
    _muda("t-velha", name="5x2", workDays=[0, 1, 2, 3, 4, 5], startTime=None)
    gravada = _gravado(base, "work_schedule_templates", "t-velha")
    assert gravada["work_days"] == [0, 1, 2, 3, 4, 5]
    assert "dias" not in gravada


def test_o_saldo_de_ferias_de_quem_passa_a_ter_dias_da_o_mesmo(base):
    """A Rafaela: Belém fecha à terça. Outubro de 2026 tem 31 dias, 4 terças
    (6, 13, 20, 27) e o feriado de 5/10: 31 - 4 - 1 = 26 dias contados."""
    rafaela = [0, 2, 3, 4, 5, 6]
    criada = _cria(name="6x1", workDays=rafaela, startTime="11:30")
    _atribui(base, "emp-r", criada.id)
    antes = corre(server.calculate_leave_counted_days("emp-r", "2026-10-01", "2026-10-31"))
    _muda(criada.id, name="Escala Rafaela", workDays=rafaela, startTime="11:30",
          dias=[{"dia": d, "location_id": "belem", "inicio": None, "fim": None} for d in rafaela])
    depois = corre(server.calculate_leave_counted_days("emp-r", "2026-10-01", "2026-10-31"))
    assert antes == 26
    assert depois == antes
