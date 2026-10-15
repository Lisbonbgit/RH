"""O script do dono que carrega as idas de outubro a dezembro da mensagem de WhatsApp
(`backend/carregar_idas_whatsapp.py`): o plano (puro) e a gravação contra o mongod.

Os dados têm a forma da produção (fictícios): as lojas do açaí são de uma empresa
«Fordaimon …», há uma loja com o MESMO nome noutra empresa do grupo (a pizzaria), a de
Belém chama-se outra coisa e a conta da Carol pode chamar-se «Carolina …»."""
import json
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import pytest  # noqa: E402
from pymongo import MongoClient  # noqa: E402

import calendario  # noqa: E402
import carregar_idas_whatsapp as script  # noqa: E402
from arranque_calendario import Paragem  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402

EMPRESAS = {sn.FORDAIMON: "Fordaimon Foods, Lda.", sn.LENHA: "Pizza Horta, Lda."}
CONTAS = [{"id": "u-deb", "name": "Débora Ferreira", "role": "admin"},
          {"id": "u-car", "name": "Carol Santos", "role": "admin"},
          {"id": "u-mat", "name": "Matheus Moraes", "role": "admin"},
          {"id": "u-bru", "name": "Bruce Lima", "role": "gerente"},
          {"id": "u-deb2", "name": "Débora Colaboradora", "role": "colaborador"},
          {"id": "u-rita", "name": "Rita Contas", "role": "contabilista"}]


def _lojas(**mudar):
    lojas = sn.semana_normal()["lojas"]
    for loja in lojas:
        loja.update(mudar.get(loja["name"], {}))
        if loja["id"] == sn.BELEM:
            loja["name"] = "Caselas"      # como em produção: a de Belém tem outro nome
    # Como em produção: outra loja com o MESMO nome, noutra empresa (a pizzaria), sem horário.
    lojas.append({"id": "loja-pizzaria-alfragide", "name": "Alfragide", "company_id": sn.LENHA,
                  "horario": None})
    return lojas


def test_planeia_as_96_idas_da_mensagem_com_o_horario_de_cada_loja():
    plano = script.planear(script.IDAS, CONTAS, _lojas(), EMPRESAS, [])
    assert (len(plano["gravar"]), plano["saltadas"]) == (96, [])
    assert [i for i in plano["gravar"] if i["user_id"] == "u-bru"] == [
        {"data": "2026-11-01", "location_id": sn.ALFRAGIDE, "user_id": "u-bru", "inicio": "10:00", "fim": "23:00"}]
    com_id = [dict(i, id=str(n)) for n, i in enumerate(plano["gravar"])]
    assert not [i for i in com_id if calendario.choques([i], com_id, ignorar_id=i["id"])]


def test_a_loja_com_o_mesmo_nome_noutra_empresa_nao_recebe_idas_mesmo_com_horario():
    lojas = _lojas()
    lojas[-1]["horario"] = {"abre": "12:00", "fecha": "23:00", "excecoes": [], "fechada": []}
    plano = script.planear(script.IDAS, CONTAS, lojas, EMPRESAS, [])
    assert len(plano["gravar"]) == 96
    assert "loja-pizzaria-alfragide" not in {i["location_id"] for i in plano["gravar"]}


def test_a_mesma_pessoa_em_duas_lojas_no_mesmo_dia_divide_o_dia_ao_meio():
    plano = script.planear(script.IDAS, CONTAS, _lojas(), EMPRESAS, [])
    assert len(plano["divididas"]) == 14
    assert plano["divididas"][0] == "Débora 06/10: Alfragide 10h–16h30 + Oeiras 16h30–22h"
    assert "Débora 24/10: Benfica 13h–17h30 + Algueirão 17h30–22h" in plano["divididas"]
    assert sorted((i["location_id"], i["inicio"], i["fim"]) for i in plano["gravar"]
                  if i["user_id"] == "u-deb" and i["data"] == "2026-10-06") == [
        (sn.ALFRAGIDE, "10:00", "16:30"), (sn.OEIRAS, "16:30", "22:00")]


def test_um_nome_que_casa_com_duas_contas_de_gestor_para_tudo():
    with pytest.raises(Paragem, match="Débora"):
        script.planear(script.IDAS, CONTAS + [{"id": "u-x", "name": "Débora Silva", "role": "gerente"}],
                       _lojas(), EMPRESAS, [])


def test_uma_pessoa_que_nao_existe_para_tudo():
    with pytest.raises(Paragem, match="Bruce"):
        script.planear(script.IDAS, [c for c in CONTAS if c["id"] != "u-bru"], _lojas(), EMPRESAS, [])


def test_procurar_tambem_desfaz_uma_loja():
    lojas = _lojas(Oeiras={"name": "Loja Oeiras"}) + [
        dict(sn.LOJAS[5], id="loja-oeiras-quiosque", name="Oeiras Parque (quiosque)")]
    with pytest.raises(Paragem, match="a loja «Oeiras» casa com 2"):
        script.planear(script.IDAS, CONTAS, lojas, EMPRESAS, [])
    plano = script.planear(script.IDAS, CONTAS, lojas, EMPRESAS, [], {"Oeiras": "Loja Oeiras"})
    assert sum(1 for i in plano["gravar"] if i["location_id"] == sn.OEIRAS) == 24
    assert "loja-oeiras-quiosque" not in {i["location_id"] for i in plano["gravar"]}


def test_uma_loja_sem_horario_para_tudo_excepto_benfica():
    with pytest.raises(Paragem, match="Oeiras"):
        script.planear(script.IDAS, CONTAS, _lojas(Oeiras={"horario": None}), EMPRESAS, [])
    plano = script.planear(script.IDAS, CONTAS, _lojas(Benfica={"horario": None}), EMPRESAS, [])
    assert plano["saltadas"] == ["Benfica ainda não tem horário: as idas de Benfica ficam de fora."]
    assert len(plano["gravar"]) == 96 - 11 and not [i for i in plano["gravar"] if i["location_id"] == sn.BENFICA]
    sem_benfica = [l for l in _lojas() if l["name"] != "Benfica"]
    assert script.planear(script.IDAS, CONTAS, sem_benfica, EMPRESAS, [])["saltadas"] == [
        "Benfica não existe na empresa «Fordaimon Foods, Lda.»: as idas de Benfica ficam de fora."]


def test_um_dia_em_que_a_loja_esta_fechada_fica_de_fora():
    oeiras = {"horario": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": [1]}}
    plano = script.planear(script.IDAS, CONTAS, _lojas(Oeiras=oeiras), EMPRESAS, [])
    assert "Débora 06/10 em Oeiras: a loja está fechada nesse dia." in plano["saltadas"]


def test_uma_ida_ja_gravada_fica_de_fora_e_uma_que_choca_fica_a_que_la_esta():
    existentes = [dict(sn.ida("2026-11-01", sn.ALFRAGIDE, "u-bru", "10:00", "23:00"), id="x1"),
                  dict(sn.ida("2026-11-01", sn.OEIRAS, "u-mat", "12:00", "14:00"), id="x2")]
    plano = script.planear(script.IDAS, CONTAS, _lojas(), EMPRESAS, existentes)
    assert len(plano["gravar"]) == 94
    assert plano["saltadas"] == [
        "Bruce 01/11 Alfragide 10h–23h: já estava gravada.",
        "Matheus 01/11 Algueirão 13h–22h: choca com a ida já gravada das 12h às 14h — fica a que lá está."]


@pytest.fixture
def prod(mongod_porta, monkeypatch):
    """Uma base pymongo com a forma da produção: empresas, contas, lojas com horário, o índice
    único e uma ida que não é da mensagem."""
    monkeypatch.delenv("PROCURAR_JSON", raising=False)
    cliente = MongoClient("mongodb://127.0.0.1:%d" % mongod_porta)
    cliente.drop_database("teste_whatsapp")
    db = cliente["teste_whatsapp"]
    db.companies.insert_many([{"id": i, "name": n} for i, n in EMPRESAS.items()])
    db.users.insert_many([dict(c) for c in CONTAS])
    db.locations.insert_many([dict(l) for l in _lojas()])
    semana = sn.semana_normal()
    for chave in ("empregados", "modelos", "atribuicoes"):   # a escala: o ensaio mostra os buracos que ficam
        db[sn.COLECOES[chave]].insert_many([dict(d) for d in semana[chave]])
    db.bolso_idas.create_index([("data", 1), ("user_id", 1), ("location_id", 1), ("inicio", 1)], unique=True)
    db.bolso_idas.insert_one(dict(sn.ida("2026-10-02", sn.AMADORA, "u-car", "14:00", "23:00"), id="de-antes"))
    yield db
    cliente.close()


def test_o_ensaio_nao_grava_nada(prod):
    linhas = []
    assert script.executar(prod, gravar=False, escrever=linhas.append) == 0
    assert prod.bolso_idas.count_documents({}) == 1
    assert "Total: 96 idas a gravar." in linhas
    assert linhas[-1].startswith("ENSAIO")
    assert sum(1 for l in linhas if l.startswith("DIVIDIDO AO MEIO: ")) == 14
    # Terça, 06/10: Alfragide fica coberta (Emily 14h–23h + Débora 10h–16h30), Oeiras fica
    # sem ninguém das 13h às 16h30 — o dono vê-o ANTES de gravar.
    assert ("DIVIDIDO AO MEIO: Débora 06/10: Alfragide 10h–16h30 + Oeiras 16h30–22h"
            " · ficam buracos: Oeiras 13h–16h30") in linhas


def test_gravar_grava_e_correr_outra_vez_nao_duplica_nem_apaga(prod):
    assert script.executar(prod, gravar=True, escrever=lambda _linha: None) == 0
    assert prod.bolso_idas.count_documents({}) == 97
    bruce = prod.bolso_idas.find_one({"user_id": "u-bru"}, {"_id": 0})
    assert (bruce["criado_por"], bruce["inicio"], bruce["fim"]) == ("whatsapp-out-dez-2026", "10:00", "23:00")
    assert bruce["location_id"] == sn.ALFRAGIDE          # a do açaí, não a da pizzaria
    linhas = []
    assert script.executar(prod, gravar=True, escrever=linhas.append) == 0
    assert prod.bolso_idas.count_documents({}) == 97
    assert "Total: 0 idas a gravar." in linhas
    assert prod.bolso_idas.find_one({"id": "de-antes"}) is not None


def test_parado_nao_grava_nada(prod):
    prod.users.insert_one({"id": "u-y", "name": "Carol Lopes", "role": "gerente"})
    linhas = []
    assert script.executar(prod, gravar=True, escrever=linhas.append) == 1
    assert prod.bolso_idas.count_documents({}) == 1
    assert linhas[-1] == "Nada foi gravado."


def test_procurar_json_desfaz_o_nome_ambiguo_sem_mudar_o_ficheiro(prod, monkeypatch):
    # Como o dono o faz em produção: -e PROCURAR_JSON='{"Carol": "Carol Santos"}'.
    prod.users.insert_one({"id": "u-y", "name": "Carol Lopes", "role": "gerente"})
    monkeypatch.setenv("PROCURAR_JSON", json.dumps({"Carol": "Carol Santos"}))
    linhas = []
    assert script.executar(prod, gravar=False, escrever=linhas.append) == 0
    assert "Total: 96 idas a gravar." in linhas


def test_carol_nao_casa_com_carolina_para_a_dizer_como_e_procurar_json_resolve(prod, monkeypatch):
    # Como em produção: a conta é «Carolina …» e «Carol», como palavra inteira, não casa com ela.
    prod.users.update_one({"id": "u-car"}, {"$set": {"name": "Carolina Santos"}})
    linhas = []
    assert script.executar(prod, gravar=True, escrever=linhas.append) == 1
    assert linhas == [
        "PARADO: A pessoa «Carol» casa com 0: nenhum — desfaz-se sem mudar o ficheiro, "
        "com -e PROCURAR_JSON='{\"Carol\": \"<um nome mais comprido>\"}'.",
        "Nada foi gravado."]
    assert prod.bolso_idas.count_documents({}) == 1
    monkeypatch.setenv("PROCURAR_JSON", json.dumps({"Carol": "Carolina"}))
    linhas = []
    assert script.executar(prod, gravar=False, escrever=linhas.append) == 0
    assert "Total: 96 idas a gravar." in linhas
