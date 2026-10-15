"""Os instantes que o CRM grava têm um formato só (correções do plano, linha
"§1 Decisões (Tempo) / T2.8").

O Mongo compara texto por caracteres: `…09:00:00.5Z` < `…09:00:00Z`, e o
`+00:00` do isoformat ordena antes do `Z`. Misturar formatos partia, sem dar
erro, a ordem da linha do tempo (índice `(loja_id, ocorrida_em)`) e o `$max`
das datas (F4). Por isso:

- `formatos.instantes_fora_do_formato(documento)` (tests/crm/formatos.py)
  aponta os `*_em`/`*_desde` que não são `AAAA-MM-DDTHH:MM:SSZ` (ou null) e o
  `atualizado_em` que não é um carimbo de 6 casas. Prova-se aqui que apanha os
  formatos errados; hoje aplica-se ao membro gravado pelo `POST /membros`. A
  T2.10 aplica-o ao `documento_loja` e à loja gravada, a T2.11 à interação
  `mudanca_fase` e ao `$set` do PATCH, a T2.13 às definições (o
  `documento_loja` e a interação ainda não existem nesta tarefa).
- `formatos.usos_proibidos_do_relogio(codigo, e_o_relogio)` varre o código
  do pacote `crm`: nunca `.isoformat` (em lado nenhum) e, fora do
  `crm/relogio.py`, nem `strftime` nem leituras do relógio (`now`, `utcnow`,
  `today`, `fromtimestamp`, `time.time`) — o relógio é um só e substituível.
- `formatos.escritas_no_terreno(atualizacao)` (T3.14, plano F3 §1 "O terreno
  ganha"): numa atualização do Mongo (ou num documento inteiro a inserir), as
  violações ao contrato com a F4 — o escritório só escreve em
  `paragens.<índice>.<campo do escritório>` e acrescenta paragens novas com o
  terreno em `pendente`/null/null; nunca `$pull`/`$pop`/`$unset`/`$addToSet`/
  `$rename` em `paragens…`, a lista inteira, um campo do terreno nem um
  caminho posicional (`paragens.$…`). Provado aqui com amostras positivas e
  negativas; as tarefas das rotas (T3.17 em diante) aplicam-no a todas as
  escritas do registo do duplo.
"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crm
import crm.db
from crm import relogio
from faturacao.auth import utilizador_atual

from crm.dominio import rotas

from . import formatos
from .duplos import BaseFalsa
from .formatos import escritas_no_terreno, instantes_fora_do_formato, usos_proibidos_do_relogio

UTC = timezone.utc
PACOTE_CRM = Path(crm.__file__).resolve().parent


# --- instantes_fora_do_formato: o verificador apanha os formatos errados ----------------


def test_um_documento_escrito_pelo_relogio_passa():
    momento = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)
    documento = {
        "id": "l1",
        "nome": "Café Central",
        "fase_desde": relogio.instante(momento),
        "criado_em": relogio.instante(momento),
        "visita_pendente_desde": None,
        "ultima_interacao_em": None,
        "ultima_visita_ou_entrega_em": None,
        "atualizado_em": relogio.carimbo(momento),
        "janelas": [{"inicio": "10:00", "fim": "13:00"}],
        "dias_fechada": ["dom"],
    }
    assert instantes_fora_do_formato(documento) == []


def test_os_instantes_e_carimbos_do_relogio_passam_sempre():
    gerador = random.Random(808)
    inicio = datetime(1, 1, 1, tzinfo=UTC)
    for _ in range(2000):
        momento = inicio + timedelta(microseconds=gerador.randrange(315_537_897_600_000_000))
        documento = {"ocorrida_em": relogio.instante(momento), "atualizado_em": relogio.carimbo(momento)}
        assert instantes_fora_do_formato(documento) == []


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("criado_em", "2026-10-10T09:30:15+00:00"),
        ("criado_em", "2026-10-10T09:30:15.987654+00:00"),
        ("criado_em", "2026-10-10T09:30:15.987654Z"),
        ("criado_em", "2026-10-10T09:30:15.5Z"),
        ("criado_em", "2026-10-10 09:30:15"),
        ("criado_em", "2026-10-10T09:30:15"),
        ("criado_em", "2026-10-10T09:30:15z"),
        ("criado_em", "2026-10-10T09:30:15Z\n"),
        ("criado_em", "2026-02-30T09:30:15Z"),
        ("criado_em", "2026-10-10T24:00:00Z"),
        ("criado_em", "٢٠٢٦-١٠-١٠T٠٩:٣٠:١٥Z"),
        ("criado_em", "٢٠٢٦-10-10T09:30:15Z"),
        ("criado_em", "2026-10-10T09:30:١٥Z"),
        ("criado_em", "2026-10-10"),
        ("criado_em", ""),
        ("criado_em", datetime(2026, 10, 10, 9, 30, 15, tzinfo=UTC)),
        ("criado_em", 1791624615),
        ("criado_em", True),
        ("fase_desde", "2026-10-10T09:30:15+00:00"),
        ("ocorrida_em", "2026-10-10T09:30:15.000000Z"),
        ("visita_pendente_desde", "2026-10-10T09:30:15.987654Z"),
        ("ultima_interacao_em", datetime(2026, 10, 10, tzinfo=UTC)),
        ("atualizado_em", "2026-10-10T09:30:15Z"),
        ("atualizado_em", "2026-10-10T09:30:15.987Z"),
        ("atualizado_em", "2026-10-10T09:30:15.987654+00:00"),
        ("atualizado_em", "2026-10-10T09:30:15.987654"),
        ("atualizado_em", "2026-02-30T09:30:15.987654Z"),
        ("atualizado_em", None),
        ("atualizado_em", "2026-10-10T09:30:15.98765٤Z"),
        ("atualizado_em", "٢٠٢٦-10-10T09:30:15.987654Z"),
        ("atualizado_em", datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)),
    ],
    ids=[
        "isoformat", "isoformat com micro", "instante com seis casas", "instante com uma casa", "formato da BD",
        "sem Z", "z minúsculo", "mudança de linha no fim", "dia que não existe", "hora que não existe",
        "algarismos árabes", "algarismos árabes só no ano (o strptime aceita-os)", "algarismos árabes só nos segundos",
        "só a data", "vazio", "datetime do BSON", "número", "verdadeiro",
        "fase_desde com isoformat", "ocorrida_em com casas", "visita_pendente_desde com casas",
        "ultima_interacao_em datetime", "atualizado_em sem casas", "atualizado_em com milissegundos",
        "atualizado_em isoformat", "atualizado_em sem Z", "atualizado_em em dia que não existe",
        "atualizado_em null", "atualizado_em com um algarismo árabe nas casas", "atualizado_em com o ano em árabe",
        "atualizado_em datetime",
    ],
)
def test_o_verificador_aponta_o_instante_fora_do_formato(campo, valor):
    assert instantes_fora_do_formato({"id": "x", campo: valor}) == [(campo, valor)]


def test_o_verificador_procura_em_subdocumentos_e_listas_e_diz_o_caminho():
    documento = {
        "id": "r1",
        "criado_em": "2026-10-10T09:00:00Z",
        "paragens": [
            {"id": "p1", "feita_em": "2026-10-10T10:00:00Z"},
            {"id": "p2", "feita_em": "2026-10-10T10:00:00+00:00"},
        ],
        "resumo": {"fechada_em": "2026-10-10T18:00:00.1Z"},
    }
    assert instantes_fora_do_formato(documento) == [
        ("paragens.1.feita_em", "2026-10-10T10:00:00+00:00"),
        ("resumo.fechada_em", "2026-10-10T18:00:00.1Z"),
    ]


def test_o_verificador_aponta_todos_os_erros_pela_ordem_do_documento():
    documento = {"fase_desde": "x", "nome": "2026-10-10T09:00:00+00:00", "criado_em": "y", "atualizado_em": "z"}
    assert instantes_fora_do_formato(documento) == [("fase_desde", "x"), ("criado_em", "y"), ("atualizado_em", "z")]


def test_o_verificador_ignora_os_campos_que_nao_sao_instantes():
    documento = {
        "nome": "2026-10-10T09:00:00+00:00",
        "janelas": [{"inicio": "10:00", "fim": "13:00"}],
        "janela1_inicio": "10:00",
        "data": "2026-10-10",
        "em": "qualquer coisa",
        "tempo": 5,
    }
    assert instantes_fora_do_formato(documento) == []


# --- O que o CRM grava hoje ------------------------------------------------------------------


def test_o_membro_gravado_pelo_post_tem_os_instantes_no_formato(monkeypatch):
    """O único documento com instantes que o CRM grava antes da T2.10. O
    relógio está parado num instante COM microssegundos: o `criado_em` tem de
    sair sem eles, na base e na resposta."""
    admin = {"user_id": "u-admin", "email": "admin.local@example.com", "role": "admin"}
    base = BaseFalsa({
        "users": [
            {"id": "u-admin", "email": "admin.local@example.com", "name": "Admin", "role": "admin"},
            {"id": "u-eli", "email": "elio@example.com", "name": "Élio Matos", "role": "gerente"},
        ],
    })
    monkeypatch.setenv("ADMIN_EMAIL", "admin.local@example.com")
    monkeypatch.setattr(relogio, "agora", lambda: datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC))
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    app.dependency_overrides[utilizador_atual] = lambda: dict(admin)

    resposta = TestClient(app).post("/api/crm/membros", json={"user_id": "u-eli", "perfil": "utilizador"})

    assert resposta.status_code == 201
    [guardado] = base.crm_membros.sem_id()
    assert guardado["criado_em"] == "2026-10-10T09:30:15Z"
    assert instantes_fora_do_formato(guardado) == []
    assert instantes_fora_do_formato(resposta.json()) == []


# --- usos_proibidos_do_relogio: o varrimento do código -------------------------------------


@pytest.mark.parametrize(
    "codigo, esperado",
    [
        ("x = momento.isoformat()\n", [(1, "isoformat")]),
        ("from datetime import datetime, timezone\nx = datetime.now(timezone.utc).isoformat()\n",
         [(2, "isoformat"), (2, "now")]),
        ("x = momento.isoformat\n", [(1, "isoformat")]),
        ("x = momento.strftime('%Y-%m-%d')\n", [(1, "strftime")]),
        ("x = datetime.now()\n", [(1, "now")]),
        ("x = datetime.datetime.utcnow()\n", [(1, "utcnow")]),
        ("x = date.today()\n", [(1, "today")]),
        ("x = datetime.fromtimestamp(0)\n", [(1, "fromtimestamp")]),
        ("x = datetime.utcfromtimestamp(0)\n", [(1, "utcfromtimestamp")]),
        ("import time\nx = time.time()\n", [(2, "time.time")]),
        ("import time\nx = time.time_ns()\n", [(2, "time.time_ns")]),
        ("from datetime import datetime as _dt\nx = _dt.now()\n", [(2, "now")]),
    ],
    ids=[
        "isoformat", "now e isoformat na mesma linha", "isoformat sem chamar", "strftime", "now", "utcnow com módulo",
        "today", "fromtimestamp", "utcfromtimestamp", "time.time", "time.time_ns", "now com outro nome",
    ],
)
def test_o_varrimento_apanha_o_relogio_lido_ou_formatado_fora_do_relogio(codigo, esperado):
    assert usos_proibidos_do_relogio(codigo) == esperado


def test_no_proprio_relogio_so_o_isoformat_e_proibido():
    codigo = (
        "from datetime import datetime, timezone\n"
        "def agora():\n"
        "    return datetime.now(timezone.utc)\n"
        "def hoje(m):\n"
        "    return m.strftime('%Y-%m-%d')\n"
        "def mau(m):\n"
        "    return m.isoformat()\n"
    )
    assert usos_proibidos_do_relogio(codigo, e_o_relogio=True) == [(7, "isoformat")]
    assert usos_proibidos_do_relogio(codigo) == [(3, "now"), (5, "strftime"), (7, "isoformat")]


def test_o_varrimento_nao_se_engana_com_texto_nem_com_o_relogio_do_crm():
    codigo = (
        '"""Nunca .isoformat() nem datetime.now() aqui: usar relogio.instante()."""\n'
        "# time.time() também não\n"
        "from . import relogio\n"
        "x = relogio.instante()\n"
        "y = relogio.carimbo(relogio.agora())\n"
        "z = {'now': 1, 'isoformat': 2}['now']\n"
        "agora = relogio.agora\n"
        "timeout = httpx.Timeout(5.0, connect=3.0)\n"
        "hora = momento.time()\n"
        "inicio = datetime.time(9, 0)\n"
    )
    assert usos_proibidos_do_relogio(codigo) == []


def test_o_varrimento_da_os_usos_pela_ordem_das_linhas():
    # O ast.walk visita primeiro os nós menos fundos: sem ordenar, o da linha
    # 2 vinha antes do da linha 1.
    codigo = "a = f(g(h(x.isoformat())))\nb = y.strftime('%H')\n"
    assert usos_proibidos_do_relogio(codigo) == [(1, "isoformat"), (2, "strftime")]


def test_nenhum_modulo_do_crm_usa_isoformat_nem_le_o_relogio_por_fora():
    """O grep da correção §1 Tempo / T2.8, com o AST (não se engana com as
    docstrings que explicam a regra)."""
    ficheiros = sorted(p for p in PACOTE_CRM.rglob("*.py") if "__pycache__" not in p.parts)
    relogio_py = PACOTE_CRM / "relogio.py"
    assert relogio_py in ficheiros
    assert len(ficheiros) >= 15  # o varrimento viu mesmo o pacote
    encontrados = {
        str(p.relative_to(PACOTE_CRM)): usos
        for p in ficheiros
        if (usos := usos_proibidos_do_relogio(p.read_text(encoding="utf-8"), e_o_relogio=p == relogio_py))
    }
    assert encontrados == {}


# --- escritas_no_terreno: o escritório nunca toca no terreno (T3.14) ----------------------
# (plano F3 §1 "O terreno ganha" e a correção "T3.26 / T3.14": os caminhos posicionais)


PARAGEM_NOVA = {
    "id": "p9",
    "loja_id": "l9",
    "ordem": 2,
    "motivo": "amostra",
    "tempo_servico_min": 10,
    "manter_fechada": False,
    "nao_cabe": False,
    "chegada_prevista": None,
    "espera_min": None,
    "fora_de_horario": False,
    "adicionada_em": "2026-10-20T09:00:00Z",
    "adicionada_por": "u1",
    "removida_em": None,
    "estado": "pendente",
    "resultado": None,
    "concluida_em": None,
}


def _sem(paragem, campo):
    return {c: v for c, v in paragem.items() if c != campo}


def test_os_campos_do_terreno_do_verificador_sao_os_do_dominio():
    """Escritos à parte de propósito (como as expressões dos instantes): um
    engano no domínio não passa por estar copiado no teste. Se a F4 alargar os
    campos do terreno, têm de mudar nos dois sítios."""
    assert formatos.CAMPOS_DO_TERRENO == rotas.CAMPOS_DO_TERRENO == ("estado", "resultado", "concluida_em")


@pytest.mark.parametrize(
    "atualizacao",
    [
        {"$set": rotas.caminhos_paragem(1, {"ordem": 0, "removida_em": None}), "$inc": {"versao": 1}},
        {"$push": {"paragens": PARAGEM_NOVA}, "$inc": {"versao": 1}, "$set": {"atualizado_em": "x", "atualizado_por": "u1"}},
        {"$set": {"estado": "planeada", "calculo": None, "hora_saida": "08:30", "resultado": "x", "concluida_em": None}},
        {"$set": {"paragens.0.chegada_prevista": "09:10", "paragens.12.espera_min": 5, "paragens.3.fora_de_horario": True}},
        {"$inc": {"paragens.0.tempo_servico_min": 5}},
        {"$set": {"calculo.atual": False, "paragens.0.motivo": "entrega"}},
        {"$setOnInsert": {"criado_em": "2026-10-20T09:00:00Z"}},
        {"$unset": {"calculo": ""}, "$pull": {"avisos": "x"}, "$rename": {"antigo": "novo"}},
        {},
        {"id": "r1", "data": "2026-10-20", "versao": 1, "paragens": [PARAGEM_NOVA, {**PARAGEM_NOVA, "id": "p8"}]},
        {"id": "r1", "data": "2026-10-20", "versao": 1, "paragens": []},
    ],
    ids=[
        "caminhos por índice", "paragem nova", "campos de topo com os nomes do terreno", "horas do Directions",
        "inc por índice", "subcampo do cálculo", "setOnInsert de topo", "operadores fora de paragens", "vazia",
        "documento inteiro com paragens novas", "documento inteiro sem paragens",
    ],
)
def test_as_escritas_do_escritorio_passam_no_verificador_do_terreno(atualizacao):
    assert escritas_no_terreno(atualizacao) == []


@pytest.mark.parametrize(
    "atualizacao, violacoes",
    [
        ({"$pull": {"paragens": {"id": "p1"}}}, [("$pull", "paragens", formatos.OPERADOR_PROIBIDO)]),
        ({"$pop": {"paragens": 1}}, [("$pop", "paragens", formatos.OPERADOR_PROIBIDO)]),
        ({"$unset": {"paragens.0.motivo": ""}}, [("$unset", "paragens.0.motivo", formatos.OPERADOR_PROIBIDO)]),
        ({"$unset": {"paragens": ""}}, [("$unset", "paragens", formatos.OPERADOR_PROIBIDO)]),
        ({"$addToSet": {"paragens": PARAGEM_NOVA}}, [("$addToSet", "paragens", formatos.OPERADOR_PROIBIDO)]),
        ({"$rename": {"paragens": "antigas"}}, [("$rename", "paragens", formatos.OPERADOR_PROIBIDO)]),
        ({"$rename": {"antigas": "paragens"}}, [("$rename", "paragens", formatos.OPERADOR_PROIBIDO)]),
        ({"$rename": {"paragens.0.estado": "paragens.0.x"}}, [("$rename", "paragens.0.estado", formatos.OPERADOR_PROIBIDO)]),
        ({"$bit": {"paragens.0.ordem": {"and": 1}}}, [("$bit", "paragens.0.ordem", formatos.OPERADOR_PROIBIDO)]),
        ({"$setOnInsert": {"paragens.0.ordem": 0}}, [("$setOnInsert", "paragens.0.ordem", formatos.OPERADOR_PROIBIDO)]),
        ({"$set": {"paragens": []}}, [("$set", "paragens", formatos.SUBSTITUI_A_LISTA)]),
        ({"$set": {"paragens": [PARAGEM_NOVA]}}, [("$set", "paragens", formatos.SUBSTITUI_A_LISTA)]),
        ({"$setOnInsert": {"paragens": [PARAGEM_NOVA]}}, [("$setOnInsert", "paragens", formatos.SUBSTITUI_A_LISTA)]),
        ({"$inc": {"paragens": 1}}, [("$inc", "paragens", formatos.SUBSTITUI_A_LISTA)]),
        ({"$set": {"paragens.0": PARAGEM_NOVA}}, [("$set", "paragens.0", formatos.SUBSTITUI_A_PARAGEM)]),
        ({"$set": {"paragens.ordem": 0}}, [("$set", "paragens.ordem", formatos.CAMINHO_SEM_INDICE)]),
        ({"$set": {"paragens.0.estado": "feita"}}, [("$set", "paragens.0.estado", formatos.CAMPO_DO_TERRENO)]),
        ({"$set": {"paragens.3.resultado": "entregue"}}, [("$set", "paragens.3.resultado", formatos.CAMPO_DO_TERRENO)]),
        ({"$set": {"paragens.12.concluida_em": None}}, [("$set", "paragens.12.concluida_em", formatos.CAMPO_DO_TERRENO)]),
        ({"$set": {"paragens.0.estado.x": 1}}, [("$set", "paragens.0.estado.x", formatos.CAMPO_DO_TERRENO)]),
        ({"$inc": {"paragens.0.estado": 1}}, [("$inc", "paragens.0.estado", formatos.CAMPO_DO_TERRENO)]),
        ({"$set": {"paragens.$.estado": "feita"}}, [("$set", "paragens.$.estado", formatos.CAMINHO_POSICIONAL)]),
        ({"$set": {"paragens.$.ordem": 0}}, [("$set", "paragens.$.ordem", formatos.CAMINHO_POSICIONAL)]),
        ({"$set": {"paragens.$[].ordem": 0}}, [("$set", "paragens.$[].ordem", formatos.CAMINHO_POSICIONAL)]),
        ({"$set": {"paragens.$[p].ordem": 0}}, [("$set", "paragens.$[p].ordem", formatos.CAMINHO_POSICIONAL)]),
        ({"$inc": {"paragens.$.tempo_servico_min": 5}}, [("$inc", "paragens.$.tempo_servico_min", formatos.CAMINHO_POSICIONAL)]),
        ({"$push": {"paragens.$.historico": 1}}, [("$push", "paragens.$.historico", formatos.CAMINHO_POSICIONAL)]),
        ({"$push": {"paragens": {**PARAGEM_NOVA, "estado": "feita"}}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens": {**PARAGEM_NOVA, "resultado": "entregue"}}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens": {**PARAGEM_NOVA, "concluida_em": "2026-10-20T10:00:00Z"}}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens": _sem(PARAGEM_NOVA, "estado")}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens": _sem(PARAGEM_NOVA, "resultado")}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens": _sem(PARAGEM_NOVA, "concluida_em")}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens": "p1"}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens": {"$each": [PARAGEM_NOVA]}}}, [("$push", "paragens", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)]),
        ({"$push": {"paragens.0.historico": {"x": 1}}}, [("$push", "paragens.0.historico", formatos.PUSH_DENTRO_DA_PARAGEM)]),
        (
            {"id": "r1", "paragens": [PARAGEM_NOVA, {**PARAGEM_NOVA, "estado": "feita"}, "p"]},
            [("documento", "paragens.1", formatos.PARAGEM_NOVA_FORA_DO_FORMATO), ("documento", "paragens.2", formatos.PARAGEM_NOVA_FORA_DO_FORMATO)],
        ),
        ({"id": "r1", "paragens": None}, [("documento", "paragens", formatos.SUBSTITUI_A_LISTA)]),
        (
            {"$pull": {"paragens": {}}, "$set": {"paragens.0.estado": "feita", "paragens.1.ordem": 0, "paragens.$.ordem": 1}},
            [
                ("$pull", "paragens", formatos.OPERADOR_PROIBIDO),
                ("$set", "paragens.0.estado", formatos.CAMPO_DO_TERRENO),
                ("$set", "paragens.$.ordem", formatos.CAMINHO_POSICIONAL),
            ],
        ),
    ],
    ids=[
        "pull", "pop", "unset num campo", "unset da lista", "addToSet", "rename da lista", "rename para a lista",
        "rename de um campo do terreno", "bit", "setOnInsert por índice", "set da lista vazia", "set da lista",
        "setOnInsert da lista", "inc na lista", "set de uma paragem inteira", "caminho sem índice",
        "set estado", "set resultado", "set concluida_em", "subcampo do terreno", "inc no terreno",
        "posicional no terreno", "posicional no escritório", "posicional todos", "posicional filtrado",
        "inc posicional", "push posicional", "push com estado feita", "push com resultado", "push com concluida_em",
        "push sem estado", "push sem resultado", "push sem concluida_em", "push de texto", "push com each",
        "push dentro da paragem", "documento com paragens fora do formato", "documento com paragens null",
        "várias violações pela ordem",
    ],
)
def test_o_verificador_do_terreno_aponta_as_escritas_proibidas(atualizacao, violacoes):
    assert escritas_no_terreno(atualizacao) == violacoes


@pytest.mark.parametrize(
    "atualizacao",
    ["x", None, [{"$set": {}}], {"$set": "x"}, {"$set": {"a": 1}, "id": "r1"}],
    ids=["texto", "null", "lista", "operador sem dicionário", "operadores misturados com campos"],
)
def test_o_verificador_do_terreno_recusa_o_que_nao_e_uma_atualizacao_nem_um_documento(atualizacao):
    with pytest.raises(TypeError):
        escritas_no_terreno(atualizacao)
