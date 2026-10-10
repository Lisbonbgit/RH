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

from .duplos import BaseFalsa
from .formatos import instantes_fora_do_formato, usos_proibidos_do_relogio

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
