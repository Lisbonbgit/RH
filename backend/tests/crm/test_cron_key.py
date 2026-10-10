"""A guarda das tarefas agendadas do CRM: `crm.auth.exigir_cron_key`
(desenho §3.3; dossiê §4, "Famílias de rotas"; revisão da F0/F1, AC-1).

As rotas `/api/crm/cron/*` (F5) não têm sessão: quem as chama é o crontab do
VPS, com a `CRON_KEY` no parâmetro `key`, como as tarefas do portal
(`/api/faturacao/cron/relatorio-diario?key=…`, `relatorio-diario-cron.sh`).
A guarda vive numa dependência só, e o teste de proteção das rotas exige ESSA
função em cada rota de `ROTAS_DE_CRON` — assim uma rota de cron que se esqueça
da chave, ou que a compare com `==`, não passa por estar só "sem sessão".

Regras (molde `faturacao/relatorio_rota.py::cron_relatorio_diario`):
- a variável lê-se do ambiente a CADA pedido;
- sem a variável, ou vazia, ninguém entra (nem com `key=` vazio);
- `secrets.compare_digest`, e não `==`, sobre bytes UTF-8 (com `str`, um
  carácter fora do ASCII dava `TypeError` → 500 em vez de 403);
- recusa → 403 com a forma dos erros do CRM (`sem_permissao`).
"""
import inspect

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import crm.auth
from crm.auth import exigir_cron_key, membro_crm_atual
from faturacao.auth import utilizador_atual

CHAVE = "chave-de-teste-do-cron"
SEM_PERMISSAO = {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}


@pytest.fixture
def cron(monkeypatch):
    """Uma app com uma rota de cron protegida pela guarda; a `CRON_KEY` fica
    por conta de cada teste."""
    monkeypatch.delenv("CRON_KEY", raising=False)
    app = FastAPI()

    @app.post("/api/crm/cron/tarefa")
    async def tarefa(_: None = Depends(exigir_cron_key)):
        return {"corrida": True}

    return TestClient(app)


def _recusado(r):
    return r.status_code == 403 and r.json() == {"detail": SEM_PERMISSAO}


def test_com_a_chave_certa_entra(cron, monkeypatch):
    monkeypatch.setenv("CRON_KEY", CHAVE)
    r = cron.post("/api/crm/cron/tarefa", params={"key": CHAVE})
    assert r.status_code == 200
    assert r.json() == {"corrida": True}


@pytest.mark.parametrize(
    "parametros",
    [{"key": "outra-coisa"}, {"key": CHAVE + "x"}, {"key": CHAVE[:-1]}, {"key": ""}, {}, {"key": CHAVE.upper()}],
    ids=["outra", "a mais", "a menos", "vazia", "sem key", "maiusculas"],
)
def test_com_a_chave_errada_ou_sem_ela_da_403(cron, monkeypatch, parametros):
    monkeypatch.setenv("CRON_KEY", CHAVE)
    assert _recusado(cron.post("/api/crm/cron/tarefa", params=parametros))


@pytest.mark.parametrize("valor", [None, ""], ids=["sem a variavel", "variavel vazia"])
@pytest.mark.parametrize("parametros", [{"key": ""}, {"key": CHAVE}, {}], ids=["key vazia", "key qualquer", "sem key"])
def test_sem_cron_key_no_ambiente_fica_fechada(cron, monkeypatch, valor, parametros):
    """Fechada por omissão: uma instalação sem a variável não abre a porta,
    nem a quem mande `key=` vazio."""
    if valor is not None:
        monkeypatch.setenv("CRON_KEY", valor)
    assert _recusado(cron.post("/api/crm/cron/tarefa", params=parametros))


def test_a_chave_le_se_do_ambiente_a_cada_pedido(cron, monkeypatch):
    monkeypatch.setenv("CRON_KEY", CHAVE)
    assert cron.post("/api/crm/cron/tarefa", params={"key": CHAVE}).status_code == 200
    monkeypatch.setenv("CRON_KEY", "chave-nova")
    assert _recusado(cron.post("/api/crm/cron/tarefa", params={"key": CHAVE}))
    assert cron.post("/api/crm/cron/tarefa", params={"key": "chave-nova"}).status_code == 200
    monkeypatch.delenv("CRON_KEY")
    assert _recusado(cron.post("/api/crm/cron/tarefa", params={"key": "chave-nova"}))


@pytest.mark.parametrize("enviada", ["chavé-de-teste", "ключ", "🔑"], ids=["acento", "cirilico", "emoji"])
def test_uma_chave_fora_do_ascii_da_403_e_nunca_500(cron, monkeypatch, enviada):
    """O `compare_digest` com `str` lança `TypeError` fora do ASCII (o
    TestClient relançava-o aqui); com bytes, é só uma chave errada."""
    monkeypatch.setenv("CRON_KEY", CHAVE)
    assert _recusado(cron.post("/api/crm/cron/tarefa", params={"key": enviada}))


def test_uma_cron_key_fora_do_ascii_tambem_funciona(cron, monkeypatch):
    monkeypatch.setenv("CRON_KEY", "chavé-ç")
    assert cron.post("/api/crm/cron/tarefa", params={"key": "chavé-ç"}).status_code == 200


def test_compara_com_compare_digest_e_nunca_com_igual(cron, monkeypatch):
    """`==` pára no primeiro carácter diferente: o tempo da resposta dizia
    quantos estavam certos. O espião prova que a decisão passa pelo
    `compare_digest` (e com bytes)."""
    chamadas = []
    original = crm.auth.secrets.compare_digest

    def espiao(a, b):
        chamadas.append((type(a), type(b)))
        return original(a, b)

    monkeypatch.setattr(crm.auth.secrets, "compare_digest", espiao)
    monkeypatch.setenv("CRON_KEY", CHAVE)
    assert cron.post("/api/crm/cron/tarefa", params={"key": CHAVE}).status_code == 200
    assert _recusado(cron.post("/api/crm/cron/tarefa", params={"key": "outra"}))
    assert chamadas == [(bytes, bytes), (bytes, bytes)]


def test_a_guarda_nao_usa_a_sessao_do_portal():
    """Só o parâmetro `key`; nada de `utilizador_atual` nem de
    `membro_crm_atual` (o crontab não tem sessão)."""
    parametros = list(inspect.signature(exigir_cron_key).parameters.values())
    assert [p.name for p in parametros] == ["key"]
    dependencia = getattr(parametros[0].default, "dependency", None)
    assert dependencia not in (utilizador_atual, membro_crm_atual)
    assert inspect.iscoroutinefunction(exigir_cron_key)


def test_um_cabecalho_de_sessao_nao_abre_a_porta(cron, monkeypatch):
    monkeypatch.setenv("CRON_KEY", CHAVE)
    r = cron.post("/api/crm/cron/tarefa", params={"key": "errada"}, headers={"Authorization": "Bearer qualquer"})
    assert _recusado(r)
