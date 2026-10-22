"""As rotas das trocas contra um mongod REAL (desenho `2026-10-20-calendario-trocas-historico-design.md`,
§1 «Recusas», «Mudar e desfazer», «Contagem», e §5 4). Semana normal: a 27/10 (terça) a Emily está
em Alfragide 14h–23h e a Joana na Amadora 14h–23h, a Beatrice e o Weber de folga; o Weber está de
férias de 21 a 25/10."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorCollection  # noqa: E402

import calendario  # noqa: E402
import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402
from .apoio import corre  # noqa: E402
from .test_rotas_de_escrita import _dependencias, _rota  # noqa: E402

DEBORA = {"user_id": sn.DEBORA, "role": "admin"}
GERENTE = {"user_id": sn.GERENTE, "role": "gerente"}
EMILY, BEATRICE, JOANA, WEBER = (sn.user(n) for n in ("Emily", "Beatrice", "Joana", "Weber"))
TERCA = "2026-10-27"


def _semana(base, mexer=None):
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    if mexer:
        mexer(dados)
    corre(sn.gravar(base, dados))
    corre(server._bolso_criar_indices())
    return base


@pytest.fixture
def semana(base):
    return _semana(base)


def _trocar(quem=DEBORA, **corpo):
    return corre(server.bolso_trocar(server.BolsoTrocaIn(**corpo), current_user=quem))


def _entre_si(quem=DEBORA, **corpo):
    return corre(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(**corpo), current_user=quem))


def _recusa(coro):
    with pytest.raises(HTTPException) as erro:
        corre(coro)
    return erro.value.status_code, erro.value.detail


def _recusa_troca(**corpo):
    pedido = dict(data=TERCA, sai=EMILY, entra=BEATRICE, inicio="14:00", fim="23:00")
    pedido.update(corpo)
    return _recusa(server.bolso_trocar(server.BolsoTrocaIn(**pedido), current_user=DEBORA))


def _idas(db):
    return corre(db.bolso_idas.find({}, {"_id": 0}).sort([("data", 1), ("user_id", 1)]).to_list(100))


# --- Gravar ----------------------------------------------------------------------------------


def test_a_troca_simples_grava_uma_ida_na_loja_de_quem_sai(semana):
    r = _trocar(data=TERCA, sai=EMILY, entra=BEATRICE, inicio="14:00", fim="18:00")
    [ida] = _idas(semana)
    assert r == {"troca_id": ida["troca_id"], "ids": [ida["id"]]}
    assert ida["troca_id"]
    sem_ids = {k: v for k, v in ida.items() if k not in ("id", "troca_id", "criado_em")}
    assert sem_ids == {"data": TERCA, "location_id": sn.ALFRAGIDE, "user_id": BEATRICE, "inicio": "14:00",
                       "fim": "18:00", "no_lugar_de_emp": sn.emp("Emily"), "criado_por": sn.DEBORA,
                       "alterado_por": None, "alterado_em": None}
    assert ida["criado_em"]


def test_a_troca_entre_si_grava_duas_idas_com_o_mesmo_troca_id(semana):
    r = _entre_si(data=TERCA, uma=EMILY, outra=JOANA)
    idas = _idas(semana)
    assert [(i["user_id"], i["location_id"], i["inicio"], i["fim"], i["no_lugar_de_emp"]) for i in idas] == [
        (EMILY, sn.AMADORA, "14:00", "23:00", sn.emp("Joana")),
        (JOANA, sn.ALFRAGIDE, "14:00", "23:00", sn.emp("Emily"))]
    assert {i["troca_id"] for i in idas} == {r["troca_id"]}
    assert sorted(r["ids"]) == sorted(i["id"] for i in idas)
    assert {i["criado_por"] for i in idas} == {sn.DEBORA}


# --- As recusas (desenho, tabela «Recusas») ----------------------------------------------------


def test_quem_sai_nao_esta_na_escala_da_409(semana):
    assert _recusa_troca(sai=BEATRICE, entra=EMILY, inicio="10:00", fim="19:00") == (
        409, "Beatrice não está na escala a 27/10.")
    assert _recusa(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data=TERCA, uma=EMILY, outra=WEBER), current_user=DEBORA)) == (409, "Weber não está na escala a 27/10.")
    assert _idas(semana) == []


def test_as_horas_fora_das_de_quem_sai_dao_409(semana):
    assert _recusa_troca(inicio="13:00") == (409, "As horas da troca têm de estar dentro das de Emily (14h–23h).")
    assert _idas(semana) == []


def test_a_mesma_pessoa_dos_dois_lados_da_400(semana):
    assert _recusa_troca(entra=EMILY) == (400, "Escolha outra pessoa.")
    assert _recusa(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data=TERCA, uma=JOANA, outra=JOANA), current_user=DEBORA)) == (400, "Escolha outra pessoa.")
    assert _idas(semana) == []


def test_a_troca_entre_si_sem_diferenca_da_400(base):
    # Sexta 30/10: com a Joana também na Amadora 14h–23h, trocá-la com o Weber não mudava nada.
    def _joana_na_amadora(dados):
        modelo = next(m for m in dados["modelos"] if m["id"] == "m-joana")
        next(d for d in modelo["dias"] if d["dia"] == 4)["location_id"] = sn.AMADORA

    _semana(base, _joana_na_amadora)
    assert _recusa(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data="2026-10-30", uma=WEBER, outra=JOANA), current_user=DEBORA)) == (400, "Escolha outra pessoa.")
    assert _idas(base) == []


def test_ja_ha_troca_para_quem_sai_da_409(semana):
    _trocar(data=TERCA, sai=EMILY, entra=BEATRICE, inicio="14:00", fim="18:00")
    assert _recusa_troca(entra=sn.CAROL, inicio="17:00") == (409, "Já há uma troca para Emily a 27/10 (Beatrice).")
    assert _recusa(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data=TERCA, uma=JOANA, outra=EMILY), current_user=DEBORA)) == (
        409, "Já há uma troca para Emily a 27/10 (Beatrice).")
    assert len(_idas(semana)) == 1


def test_quem_entra_de_ferias_da_409_como_nas_idas(semana):
    # Quinta 22/10: a Beatrice está em Alfragide 10h–19h e o Weber de férias.
    estado, texto = _recusa_troca(data="2026-10-22", sai=BEATRICE, entra=WEBER, inicio="10:00", fim="19:00")
    assert (estado, texto.splitlines()) == (409, ["Weber está de férias a 22/10.", "Escolha outra pessoa ou outro dia."])
    assert _idas(semana) == []


def test_quem_entra_com_uma_ida_que_choca_da_409_como_nas_idas(semana):
    corre(semana.bolso_idas.insert_one(sn.ida(TERCA, sn.OEIRAS, sn.CAROL, "13:00", "22:00")))
    estado, texto = _recusa_troca(entra=sn.CAROL)
    assert (estado, texto.splitlines()) == (409, ["Carol já está em Oeiras das 13h às 22h a 27/10.",
                                                  "Mude as horas ou apague primeiro a outra ida."])
    assert len(_idas(semana)) == 1


def test_a_troca_entre_si_que_choca_com_outra_ida_da_409(semana):
    corre(semana.bolso_idas.insert_one(sn.ida(TERCA, sn.OEIRAS, EMILY, "10:00", "15:00")))
    estado, texto = _recusa(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data=TERCA, uma=EMILY, outra=JOANA), current_user=DEBORA))
    assert (estado, texto.splitlines()[0]) == (409, "Emily já está em Oeiras das 10h às 15h a 27/10.")
    assert len(_idas(semana)) == 1


@pytest.mark.parametrize("corpo, texto", [
    ({"inicio": "14h"}, "As horas escrevem-se HH:MM (por exemplo 13:00)."),
    ({"entra": sn.CONTABILISTA}, "Só administradores, gestores e colaboradores podem ser escalados."),
    ({"entra": "nao-existe"}, "Só administradores, gestores e colaboradores podem ser escalados."),
    ({"sai": sn.DEBORA, "entra": EMILY}, "Escolha outra pessoa."),      # quem sai sem ficha
    ({"sai": "nao-existe"}, "Escolha outra pessoa."),                    # quem sai sem conta
])
def test_os_400_da_troca_simples(semana, corpo, texto):
    assert _recusa_troca(**corpo) == (400, texto)
    assert _idas(semana) == []


@pytest.mark.parametrize("uma, outra", [(sn.DEBORA, EMILY), (EMILY, "nao-existe")])
def test_a_troca_entre_si_sem_ficha_da_400(semana, uma, outra):
    assert _recusa(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data=TERCA, uma=uma, outra=outra), current_user=DEBORA)) == (400, "Escolha outra pessoa.")
    assert _idas(semana) == []


# --- Tudo ou nada ------------------------------------------------------------------------------


def test_a_troca_entre_si_e_tudo_ou_nada(semana, monkeypatch):
    """Outra admin grava, no mesmo segundo, a MESMA ida que a segunda desta troca (a Joana em
    Alfragide). Desliga-se a verificação; o índice único apanha a segunda e a primeira (a
    Emily na Amadora) tem de ser apagada."""
    corre(semana.bolso_idas.insert_one(dict(sn.ida(TERCA, sn.ALFRAGIDE, JOANA, "14:00", "23:00"), id="da-outra-admin")))
    monkeypatch.setattr(calendario, "choques", lambda *a, **k: [])
    estado, texto = _recusa(server.bolso_trocar_entre_si(server.BolsoTrocaEntreSiIn(
        data=TERCA, uma=EMILY, outra=JOANA), current_user=DEBORA))
    assert estado == 409
    assert "Nada foi gravado" in texto
    assert [i["id"] for i in _idas(semana)] == ["da-outra-admin"]


def test_qualquer_falha_ao_gravar_a_segunda_ida_apaga_a_primeira(semana, monkeypatch):
    """Não só o índice único: uma falha qualquer (rede, servidor) no 2.º insert de uma troca entre
    si não pode deixar meia troca gravada. O erro segue para cima, como era."""
    original = AsyncIOMotorCollection.insert_one
    vezes = []

    def _rebenta_a_segunda(self, *args, **kwargs):
        if self.name == "bolso_idas":
            vezes.append(1)
            if len(vezes) == 2:
                raise RuntimeError("a rede caiu")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncIOMotorCollection, "insert_one", _rebenta_a_segunda)
    with pytest.raises(RuntimeError, match="a rede caiu"):
        _entre_si(data=TERCA, uma=EMILY, outra=JOANA)
    assert len(vezes) == 2
    assert _idas(semana) == []


# --- Mudar e desfazer --------------------------------------------------------------------------


def test_uma_ida_de_troca_nao_se_muda_nem_se_apaga_como_ida(semana):
    [ida_id] = _trocar(data=TERCA, sai=EMILY, entra=BEATRICE, inicio="14:00", fim="23:00")["ids"]
    corpo = server.BolsoIdaIn(data=TERCA, location_id=sn.ALFRAGIDE, user_id=WEBER, inicio="14:00", fim="23:00")
    for quem in (DEBORA, GERENTE):
        assert _recusa(server.bolso_mudar_ida(ida_id, corpo, current_user=quem)) == (
            409, "Isto é uma troca: desfaça-a e faça outra.")
        assert _recusa(server.bolso_apagar_ida(ida_id, current_user=quem)) == (
            409, "Isto é uma troca: desfaça-a e faça outra.")
    [ida] = _idas(semana)
    assert (ida["id"], ida["user_id"]) == (ida_id, BEATRICE)


def test_desfazer_apaga_as_duas_idas_da_troca_e_mais_nenhuma(semana):
    corre(semana.bolso_idas.insert_one(sn.ida(TERCA, sn.OEIRAS, sn.DEBORA, "13:00", "22:00")))
    troca_id = _entre_si(data=TERCA, uma=EMILY, outra=JOANA)["troca_id"]
    assert corre(server.bolso_desfazer_troca(troca_id, current_user=DEBORA)) == {"desfeita": troca_id, "apagadas": 2}
    assert [i["user_id"] for i in _idas(semana)] == [sn.DEBORA]
    assert _recusa(server.bolso_desfazer_troca(troca_id, current_user=DEBORA))[0] == 404


# --- A porta: só administradores ---------------------------------------------------------------


@pytest.mark.parametrize("metodo, caminho", [
    ("POST", "/api/bolso/calendario/trocas"), ("POST", "/api/bolso/calendario/trocas/entre-si"),
    ("DELETE", "/api/bolso/calendario/trocas/{troca_id}")])
def test_as_tres_rotas_das_trocas_passam_pela_porta_dos_administradores(metodo, caminho):
    deps = _dependencias(_rota(caminho, metodo))
    assert server.bolso_quem_troca in deps
    assert server.admin_manager_required in deps


def test_o_gerente_leva_403_e_o_admin_passa(semana):
    assert _recusa(server.bolso_quem_troca(current_user=dict(GERENTE))) == (
        403, "Só os administradores trocam pessoas.")
    assert _recusa(server.bolso_quem_troca(current_user={"user_id": sn.CONTABILISTA, "role": "contabilista"}))[0] == 403
    assert corre(server.bolso_quem_troca(current_user=dict(DEBORA)))["role"] == "admin"


# --- Leituras ----------------------------------------------------------------------------------


def test_pode_trocar_so_para_o_admin(semana):
    assert corre(server.bolso_calendario(ano=2026, mes=10, current_user=DEBORA))["pode_trocar"] is True
    r = corre(server.bolso_calendario(ano=2026, mes=10, current_user=GERENTE))
    assert (r["pode_marcar"], r["pode_trocar"]) == (True, False)


def test_a_contagem_nao_conta_a_troca_entre_colaboradores(semana):
    _entre_si(data=TERCA, uma=EMILY, outra=JOANA)
    _trocar(data="2026-10-30", sai=EMILY, entra=sn.CAROL, inicio="14:00", fim="23:00")
    corre(semana.bolso_idas.insert_one(sn.ida("2026-10-28", sn.OEIRAS, JOANA, "13:00", "22:00")))
    linhas = corre(server.bolso_calendario_contagem(ano=2026, current_user=DEBORA))
    assert sorted((l["user_id"], l["total"]) for l in linhas) == [(sn.CAROL, 1.0), (JOANA, 1.0)]
