"""As portas do módulo: os caminhos, quem lá pode entrar, e a garantia de que o
email de segunda-feira sai UMA vez.

**Os pedidos passam pelo FastAPI a sério, e não por chamadas directas às
funções.** Escrevi a primeira versão deste ficheiro a chamar `cron_semanal(...)`
à mão e ela dizia que o travão da segunda corrida não existia — o `forcar: bool
= Query(False)` chega à função como o objecto `Query`, que é verdadeiro, e o
`if not forcar` saltava a reserva inteira. Não era um defeito do código: era o
teste a exercitar um caminho que o servidor nunca percorre. Um cliente de teste
custa quinze linhas e responde à pergunta certa — o que acontece quando o cron
bate à porta.

Os caminhos são confrontados com o `router` a sério e nunca afirmados à mão:
uma string repetida no teste diz o que o programador escreveu, não o que o
FastAPI serve, e um prefixo trocado passa nos dois sítios ao mesmo tempo.
"""
from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

import plataformas
from faturacao.auth import gestor_atual
from plataformas import rotas


def caminhos():
    return {(sorted(r.methods)[0], r.path) for r in plataformas.router.routes}


# --- Os caminhos ------------------------------------------------------------

def test_as_rotas_servidas_sao_exactamente_estas():
    assert caminhos() == {
        ("GET", "/api/plataformas/definicoes"),
        ("PUT", "/api/plataformas/definicoes"),
        ("GET", "/api/plataformas/relatorio"),
        ("GET", "/api/plataformas/historico"),
        ("POST", "/api/plataformas/recolher-agora"),
        ("POST", "/api/plataformas/enviar-agora"),
        ("POST", "/api/plataformas/cron/semanal"),
    }


def test_o_prefixo_esta_no_router_e_nao_so_no_frontend():
    """O ecrã chama `/api/plataformas/...`. Se o prefixo do pacote mudar, é
    aqui que se vê — e não no browser com um 404."""
    assert plataformas.router.prefix == "/api/plataformas"
    for _, caminho in caminhos():
        assert caminho.startswith("/api/plataformas/")


def test_o_cron_nao_esta_atras_do_login_e_tudo_o_resto_esta():
    """O cron corre dentro do contentor, sem sessão nenhuma; as outras rotas
    são do backoffice e exigem um gestor."""
    for rota in plataformas.router.routes:
        dependencias = [d.call.__name__ for d in rota.dependant.dependencies
                        if getattr(d, "call", None)]
        if rota.path.endswith("/cron/semanal"):
            assert "gestor_atual" not in dependencias
        else:
            assert "gestor_atual" in dependencias, rota.path


# --- Um duplo do Mongo, só com o que estas rotas usam -----------------------

class _Coleccao:
    def __init__(self):
        self.docs = {}

    async def find_one(self, filtro, projeccao=None):
        for doc in self.docs.values():
            if all(doc.get(campo) == valor for campo, valor in filtro.items()):
                return {k: v for k, v in doc.items() if k != "_id"}
        return None

    async def insert_one(self, doc):
        # É isto que o `_id` único do Mongo faz, e é nisso que assenta a
        # garantia de um email por semana.
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("_id repetido: %s" % doc["_id"])
        self.docs[doc["_id"]] = dict(doc)

    async def replace_one(self, filtro, doc, upsert=False):
        self.docs[filtro["_id"]] = dict(doc)

    async def update_one(self, filtro, alteracao, upsert=False):
        chave = filtro.get("_id") or filtro.get("id")
        doc = self.docs.get(chave) or dict(filtro)
        doc.update(alteracao.get("$set") or {})
        doc.setdefault("_id", chave)
        self.docs[chave] = doc

    async def delete_one(self, filtro):
        self.docs.pop(filtro["_id"], None)

    def find(self, filtro=None, projeccao=None):
        return _Consulta(list(self.docs.values()))


class _Consulta:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, _limite):
        return [{k: v for k, v in d.items() if k != "_id"} for d in self.docs]


class _Base:
    def __init__(self):
        self.coleccoes = {}

    def __getitem__(self, nome):
        if nome not in self.coleccoes:
            self.coleccoes[nome] = _Coleccao()
        return self.coleccoes[nome]


@pytest.fixture
def mundo(monkeypatch):
    """O módulo com a base de dados, o dia e o envio substituídos — e um
    cliente HTTP que fala com o router a sério."""
    db = _Base()
    enviados = []

    monkeypatch.setattr(rotas, "obter_db", lambda: db)
    monkeypatch.setattr(rotas, "_hoje_em_lisboa", lambda: date(2026, 8, 31))
    monkeypatch.setenv("CRON_KEY", "chave-de-teste")

    recolhas = []

    async def recolha_falsa(_db, _hoje):
        recolhas.append(1)
        return {"lidos": 0, "avisos": []}

    async def envio_falso(_db, _hoje, para, _avisos):
        enviados.append(list(para))
        return {"enviado_para": para, "email_id": "id-%d" % len(enviados),
                "semana": {}, "total": 1.0, "completo": True}

    monkeypatch.setattr(rotas, "_recolher_e_gravar", recolha_falsa)
    monkeypatch.setattr(rotas, "_produzir_e_enviar", envio_falso)

    app = FastAPI()
    app.include_router(plataformas.router)
    app.dependency_overrides[gestor_atual] = lambda: {"role": "admin"}

    class Mundo:
        def __init__(self):
            self.db = db
            self.enviados = enviados
            self.recolhas = recolhas
            self.cliente = TestClient(app)

        def com_destinatarios(self, *emails):
            emails = emails or ("dono@lisbonb.com",)
            resposta = self.cliente.put("/api/plataformas/definicoes",
                                        json={"emails": list(emails), "ativo": True})
            assert resposta.status_code == 200
            return self

        def cron(self, chave="chave-de-teste", **params):
            return self.cliente.post("/api/plataformas/cron/semanal",
                                     params=dict(key=chave, **params))

    return Mundo()


# --- Definições -------------------------------------------------------------

def test_a_lista_de_destinatarios_grava_se_sem_repetidos(mundo):
    resposta = mundo.cliente.put(
        "/api/plataformas/definicoes",
        json={"emails": ["Dono@Lisbonb.com", "dono@lisbonb.com", "b@x.pt"],
              "ativo": True})
    assert resposta.json()["emails"] == ["dono@lisbonb.com", "b@x.pt"]
    assert mundo.cliente.get("/api/plataformas/definicoes").json()["emails"] == \
        ["dono@lisbonb.com", "b@x.pt"]


def test_um_email_mal_escrito_e_recusado_antes_de_chegar_a_lista(mundo):
    """Um endereço inválido faz o Resend recusar o envio INTEIRO: o relatório
    não sairia para ninguém, e não só para quem se enganou a escrever."""
    resposta = mundo.cliente.put("/api/plataformas/definicoes",
                                 json={"emails": ["isto não é um email"]})
    assert resposta.status_code == 422


def test_sem_definicoes_gravadas_a_lista_vem_vazia_e_ligada(mundo):
    assert mundo.cliente.get("/api/plataformas/definicoes").json() == \
        {"emails": [], "ativo": True}


# --- O cron: uma vez por semana ---------------------------------------------

def test_o_cron_envia_uma_vez_e_a_segunda_corrida_nao_envia_nada(mundo):
    """O `crontab` pode disparar duas vezes (uma retentativa, uma linha
    duplicada). Dois emails iguais na mesma manhã lêem-se como um erro."""
    mundo.com_destinatarios()

    primeira = mundo.cron().json()
    assert primeira["enviado"] is True
    assert primeira["semana_chave"] == "2026-W35"

    segunda = mundo.cron().json()
    assert segunda["enviado"] is False
    assert "2026-W35" in segunda["razao"]
    assert len(mundo.enviados) == 1


def test_a_recolha_acontece_na_mesma_quando_o_email_ja_saiu(mundo):
    """Um relatório que a plataforma envie à tarde tem de aparecer no painel,
    mesmo que o email das 08:00 já tenha saído de manhã."""
    mundo.com_destinatarios()
    mundo.cron()
    mundo.cron()
    assert len(mundo.recolhas) == 2
    assert len(mundo.enviados) == 1


def test_se_o_envio_falhar_a_semana_NAO_fica_marcada_como_enviada(mundo, monkeypatch):
    """Sem isto, uma falha do Resend marcava a semana como enviada e o email
    nunca mais saía — a avaria silenciosa na peça que existe para avisar."""
    tentativas = []

    async def falha_uma_vez(_db, _hoje, para, _avisos):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise HTTPException(status_code=502, detail="o Resend recusou")
        return {"enviado_para": para, "email_id": "ok", "semana": {},
                "total": 1.0, "completo": True}

    monkeypatch.setattr(rotas, "_produzir_e_enviar", falha_uma_vez)
    mundo.com_destinatarios()

    assert mundo.cron().status_code == 502
    # A retentativa tem de conseguir enviar.
    assert mundo.cron().json()["enviado"] is True
    assert len(tentativas) == 2


def test_o_forcar_reenvia_mesmo_com_a_semana_ja_marcada(mundo):
    mundo.com_destinatarios()
    mundo.cron()
    assert mundo.cron(forcar="true").json()["enviado"] is True
    assert len(mundo.enviados) == 2


def test_semanas_diferentes_sao_envios_diferentes(mundo, monkeypatch):
    mundo.com_destinatarios()
    mundo.cron()
    monkeypatch.setattr(rotas, "_hoje_em_lisboa", lambda: date(2026, 9, 7))
    seguinte = mundo.cron().json()
    assert seguinte["enviado"] is True
    assert seguinte["semana_chave"] == "2026-W36"
    assert len(mundo.enviados) == 2


# --- O cron: quem não entra --------------------------------------------------

def test_uma_chave_errada_e_recusada_e_nao_envia_nada(mundo):
    mundo.com_destinatarios()
    assert mundo.cron(chave="chave-errada").status_code == 403
    assert mundo.enviados == []


def test_sem_chave_nenhuma_o_pedido_nem_e_aceite(mundo):
    mundo.com_destinatarios()
    assert mundo.cliente.post("/api/plataformas/cron/semanal").status_code == 422


def test_sem_CRON_KEY_no_servidor_ninguem_entra(mundo, monkeypatch):
    """Sem a variável definida, a porta fecha-se — nunca fica aberta a todos."""
    monkeypatch.delenv("CRON_KEY", raising=False)
    mundo.com_destinatarios()
    assert mundo.cron(chave="").status_code == 403
    assert mundo.cron(chave="qualquer-coisa").status_code == 403


def test_desligado_nas_definicoes_nao_e_erro_mas_nao_envia(mundo):
    mundo.cliente.put("/api/plataformas/definicoes",
                      json={"emails": ["dono@lisbonb.com"], "ativo": False})
    assert mundo.cron().json() == {"enviado": False, "razao": "desligado nas definições"}
    assert mundo.enviados == []


def test_sem_destinatarios_nao_envia_e_diz_porque(mundo):
    saida = mundo.cron().json()
    assert saida["enviado"] is False and saida["razao"] == "sem destinatários"


# --- O botão de enviar agora -------------------------------------------------

def test_o_enviar_agora_sem_lista_recusa_com_uma_frase_util(mundo):
    resposta = mundo.cliente.post("/api/plataformas/enviar-agora", json={})
    assert resposta.status_code == 400
    assert "Painel → Plataformas" in resposta.json()["detail"]


def test_o_enviar_agora_NAO_gasta_a_reserva_da_semana(mundo):
    """O botão é para ver o email. O das 08:00 tem de sair na mesma."""
    mundo.com_destinatarios()
    mundo.cliente.post("/api/plataformas/enviar-agora", json={"para": "eu@x.pt"})
    assert mundo.cron().json()["enviado"] is True
    assert mundo.enviados == [["eu@x.pt"], ["dono@lisbonb.com"]]


def test_o_enviar_agora_so_le_a_caixa_se_lho_pedirem(mundo):
    """Uma leitura IMAP mais a IA a cada carregar do botão custa dinheiro e
    demora; por omissão o botão desenha o email com o que já está guardado."""
    mundo.com_destinatarios()
    mundo.cliente.post("/api/plataformas/enviar-agora", json={})
    assert mundo.recolhas == []
    mundo.cliente.post("/api/plataformas/enviar-agora", json={"recolher": True})
    assert len(mundo.recolhas) == 1


def test_o_botao_de_recolher_le_a_caixa_e_nao_envia_email_nenhum(mundo):
    mundo.com_destinatarios()
    resposta = mundo.cliente.post("/api/plataformas/recolher-agora")
    assert resposta.status_code == 200
    assert len(mundo.recolhas) == 1
    assert mundo.enviados == []


# --- Os registos gravados ---------------------------------------------------

def test_gravar_o_mesmo_registo_duas_vezes_deixa_UM_documento(mundo):
    """É o `_id` do Mongo a fazer a idempotência, sem índice nenhum declarado."""
    import asyncio

    registo = {"id": "uber:2026-08-24..2026-08-30", "plataforma": "uber",
               "periodo_inicio": "2026-08-24", "periodo_fim": "2026-08-30",
               "valores": {"liquido": 10.0}}

    async def grava():
        await rotas._gravar_registos(mundo.db, [registo])
        await rotas._gravar_registos(
            mundo.db, [dict(registo, valores={"liquido": 20.0})])

    asyncio.get_event_loop().run_until_complete(grava())

    guardados = mundo.cliente.get("/api/plataformas/historico").json()["registos"]
    assert len(guardados) == 1
    # Fica o mais recente: um relatório corrigido substitui o antigo.
    assert guardados[0]["valores"]["liquido"] == 20.0


def test_periodos_e_plataformas_diferentes_sao_documentos_diferentes(mundo):
    """A outra metade da mesma regra, e a que uma mutação apanhou em falta: se
    a chave não for o `id` do registo, as semanas empilham-se todas no mesmo
    documento e o histórico do painel fica com uma linha só."""
    import asyncio

    def r(plataforma, inicio, fim):
        return {"id": "%s:%s..%s" % (plataforma, inicio, fim),
                "plataforma": plataforma, "periodo_inicio": inicio,
                "periodo_fim": fim, "valores": {"liquido": 1.0}}

    async def grava():
        await rotas._gravar_registos(mundo.db, [
            r("uber", "2026-08-24", "2026-08-30"),
            r("bolt", "2026-08-24", "2026-08-30"),      # outra plataforma
            r("uber", "2026-08-17", "2026-08-23"),      # outra semana
        ])

    asyncio.get_event_loop().run_until_complete(grava())

    guardados = mundo.cliente.get("/api/plataformas/historico").json()["registos"]
    assert len(guardados) == 3
    assert len({g["id"] for g in guardados}) == 3


def test_o_relatorio_do_ecra_nao_vai_a_caixa_de_email(mundo):
    """Abrir o ecrã do Painel não pode custar uma leitura IMAP e uma factura
    da IA."""
    resposta = mundo.cliente.get("/api/plataformas/relatorio")
    assert resposta.status_code == 200
    assert mundo.recolhas == []
    assert resposta.json()["semana"]["inicio"] == "2026-08-24"
