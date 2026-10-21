"""Os dados da semana normal, como o dono os descreveu (desenho, «A semana normal»).

Uma fonte só para os testes do cálculo, os das rotas (contra o mongod) e o seed do ensaio
local. Os documentos têm a forma das colecções de produção (`COLECOES` diz qual é qual):
lojas com `horario`/`aberta_desde` (Fase 1), uma escala por pessoa (`dias` com a loja e as
horas de cada dia; três delas SEM `dias`, como as escalas antigas) e uma atribuição desde
1/1/2026. As gestoras não têm ficha de colaborador (`employee_id: None`).

`semana_normal()` devolve dados NOVOS a cada chamada: os testes mexem-lhes à vontade.
"""
import copy

FORDAIMON, LENHA = "emp-fordaimon", "emp-lenha"
ALFRAGIDE, ALGUEIRAO, AMADORA = "loja-alfragide", "loja-algueirao", "loja-amadora"
BELEM, BENFICA, OEIRAS, PIZZARIA = "loja-belem", "loja-benfica", "loja-oeiras", "loja-pizzaria"
DEBORA, CAROL, GERENTE, CONTABILISTA = "u-debora", "u-carol", "u-gerente", "u-contabilista"


def _loja(id_, nome, abre, fecha, excecoes=(), fechada=(), desde=None):
    return {"id": id_, "name": nome, "company_id": FORDAIMON,
            "horario": {"abre": abre, "fecha": fecha, "excecoes": list(excecoes), "fechada": list(fechada)},
            "aberta_desde": desde}


LOJAS = [
    _loja(ALFRAGIDE, "Alfragide", "10:00", "23:00"),
    _loja(ALGUEIRAO, "Algueirão", "13:00", "22:00"),
    _loja(AMADORA, "Amadora", "14:00", "23:00"),
    _loja(BELEM, "Belém", "11:30", "19:00", excecoes=[{"dia": 6, "abre": "11:30", "fecha": "20:00"}], fechada=[1]),
    _loja(BENFICA, "Benfica", "13:00", "22:00", desde="2026-10-24"),
    _loja(OEIRAS, "Oeiras", "13:00", "22:00"),
    # Sem horário: não entra no calendário sem ninguém a esconder.
    {"id": PIZZARIA, "name": "Pizzaria", "company_id": LENHA, "horario": None, "aberta_desde": None},
]

# (nome, loja da ficha, dias de trabalho, `dias` por dia da semana -> (loja, início, fim), ou
# None para uma escala antiga). Loja None = a da ficha; horas None = o horário da loja.
_ESCALAS = [
    ("Emily", ALFRAGIDE, [0, 1, 4, 5, 6], {d: (None, "14:00", "23:00") for d in (0, 1, 4, 5, 6)}),
    ("Beatrice", ALFRAGIDE, [2, 3, 4, 5, 6], {d: (None, "10:00", "19:00") for d in (2, 3, 4, 5, 6)}),
    ("Walisson", ALGUEIRAO, [0, 1, 2, 5, 6], None),
    ("Joana", ALGUEIRAO, [0, 1, 2, 3, 4], {0: (AMADORA, None, None), 1: (AMADORA, None, None),
                                           2: (OEIRAS, None, None), 3: (ALGUEIRAO, None, None),
                                           4: (ALGUEIRAO, None, None)}),
    ("Weber", AMADORA, [2, 3, 4, 5, 6], None),
    ("Rafaela", BELEM, [0, 2, 3, 4, 5, 6], None),
    ("Emanuela", OEIRAS, [0, 3, 4, 5, 6], {d: (None, None, None) for d in (0, 3, 4, 5, 6)}),
]

COLECOES = {
    "lojas": "locations", "empregados": "employees", "utilizadores": "users",
    "modelos": "work_schedule_templates", "atribuicoes": "work_schedule_assignments",
    "ausencias": "leave_requests", "idas": "bolso_idas", "feriados": "holidays",
}


def emp(nome):
    return "e-" + nome.lower()


def user(nome):
    return "u-" + nome.lower()


def semana_normal():
    empregados, utilizadores, modelos, atribuicoes = [], [], [], []
    for nome, loja, dias_de_trabalho, dias in _ESCALAS:
        empregados.append({"id": emp(nome), "name": nome, "location_id": loja, "company_id": FORDAIMON})
        utilizadores.append({"id": user(nome), "name": nome, "role": "colaborador", "employee_id": emp(nome)})
        modelo = {"id": "m-" + nome.lower(), "name": "Escala " + nome,
                  "work_days": list(dias_de_trabalho), "start_time": None}
        if dias is not None:
            modelo["dias"] = [{"dia": d, "location_id": l, "inicio": i, "fim": f}
                              for d, (l, i, f) in sorted(dias.items())]
        modelos.append(modelo)
        atribuicoes.append({"id": "a-" + nome.lower(), "employee_id": emp(nome), "template_id": modelo["id"],
                            "work_days": list(dias_de_trabalho), "start_date": "2026-01-01", "end_date": None})
    utilizadores += [
        {"id": DEBORA, "name": "Débora Ferreira", "role": "admin", "employee_id": None},
        {"id": CAROL, "name": "Carol Santos", "role": "admin", "employee_id": None},
        {"id": GERENTE, "name": "Guilherme Gestor", "role": "gerente", "employee_id": None},
        {"id": CONTABILISTA, "name": "Rita Contas", "role": "contabilista", "employee_id": None},
    ]
    return {"lojas": copy.deepcopy(LOJAS), "empregados": empregados, "utilizadores": utilizadores,
            "modelos": modelos, "atribuicoes": atribuicoes, "ausencias": [], "idas": [], "feriados": []}


def ida(data, loja, user_id, inicio, fim):
    return {"id": "i-%s-%s-%s-%s" % (data, loja, user_id, inicio.replace(":", "")), "data": data,
            "location_id": loja, "user_id": user_id, "inicio": inicio, "fim": fim}


def ausencia(nome, inicio, fim, status="aprovado", tipo="ferias"):
    return {"id": "f-%s-%s" % (nome.lower(), inicio), "employee_id": emp(nome), "leave_type": tipo,
            "start_date": inicio, "end_date": fim, "status": status}


async def gravar(db, dados):
    """Grava `dados` numa base Motor (cópias: o insert acrescenta o `_id` aos dicionários)."""
    for chave, colecao in COLECOES.items():
        if dados[chave]:
            await db[colecao].insert_many([dict(d) for d in dados[chave]])
