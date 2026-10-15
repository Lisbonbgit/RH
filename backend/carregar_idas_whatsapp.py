"""Carrega no calendário as idas de outubro a dezembro de 2026 da mensagem de WhatsApp
(«Escala Outubro / Alfragide: 01- Deb …»). É para o DONO correr em produção — o assistente
não chega à base de produção.

    # 1) ver o que faria (ensaio; não grava nada):
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T backend python -" < backend/carregar_idas_whatsapp.py
    # 2) só depois de ler e aprovar o que o ensaio mostrou:
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e GRAVAR=1 backend python -" < backend/carregar_idas_whatsapp.py
    # um nome que casa com dois registos (ou com nenhum) desfaz-se sem mudar este ficheiro:
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e PROCURAR_JSON='{\"Carol\": \"Carolina\"}' backend python -" < backend/carregar_idas_whatsapp.py

Corre dentro do contentor do backend (lido do stdin, na pasta /app), por isso importa o
`calendario` (Fase 2) e os ajudantes do `arranque_calendario` (Fase 1) que lá estão.

As regras:
- as pessoas encontram-se pelo nome entre as contas `admin`/`gerente` (o `_um` do arranque:
  palavra inteira, sem acentos — «Carol» não casa com «Carolina»); nenhuma ou mais de uma →
  PÁRA sem gravar nada;
- as lojas encontram-se da mesma maneira, mas SÓ nos Locais da empresa EMPRESA_DAS_LOJAS (a do
  açaí: há uma «Loja Alfragide» com o mesmo nome na pizzaria) e só entre as que têm horário
  (posto pelo arranque da Fase 1). Nenhuma, ou mais de uma → PÁRA. Excepto Benfica: sem
  horário (ou sem loja), as idas de Benfica ficam de fora e diz-se;
- PROCURAR_JSON='{"Carol": "Carolina"}' troca o nome a procurar (pessoa ou loja, ex.:
  {"Oeiras": "Loja Oeiras"}) por um mais comprido, para desfazer uma ambiguidade sem mudar
  este ficheiro;
- cada ida é o dia inteiro: o horário da loja nesse dia. Loja fechada ou por abrir nesse
  dia → essa ida fica de fora e diz-se;
- datas passadas entram (são o histórico da contagem);
- a mesma pessoa em duas lojas no mesmo dia choca (o dia inteiro nas duas). PROPOSTA: dividir
  ao meio — a primeira loja (pela ordem da mensagem) do abrir até ao meio do SEU horário, a
  segunda desde aí (ou desde que abre, se for mais tarde) até fechar. O ensaio mostra cada
  divisão E os buracos que ela deixa nas duas lojas (com a escala real); correr com GRAVAR=1
  é aprová-las. Três lojas no mesmo dia → PÁRA;
- uma ida igual a uma já gravada fica de fora; uma que choque com outra já gravada fica de fora
  e diz-se qual (nada se apaga nem se muda);
- nunca apaga nada.
"""
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone

from pymongo.errors import DuplicateKeyError

import calendario
from arranque_calendario import EMPRESA_DAS_LOJAS, Paragem, _normal, _um


def _dias(mes, *dias):
    return ["2026-%02d-%02d" % (mes, d) for d in dias]


# A mensagem, tal como o dono a mandou (gestores; tudo dia inteiro), pela ordem dela.
IDAS = {
    "Débora": [
        ("Benfica", _dias(10, 24, 25, 31)),
        ("Algueirão", _dias(10, 24) + _dias(12, 8)),
        ("Alfragide", _dias(10, 1, 2, 5, 6, 7, 8, 12, 13, 14, 15, 19, 20, 21, 22, 26, 27, 28, 29)
         + _dias(11, 2) + _dias(12, 8, 9, 10, 15, 16, 22, 30)),
        ("Oeiras", _dias(10, 6, 13, 20, 21, 27, 29, 30) + _dias(11, 1) + _dias(12, 10, 11, 14, 29)),
    ],
    "Carol": [
        ("Alfragide", _dias(10, 5) + _dias(11, 1, 3, 4, 5, 9, 10, 11, 12, 16, 17, 18, 19, 23, 24, 25, 26, 30)
         + _dias(12, 1, 2, 3, 7, 14, 17, 21, 23, 28, 29)),
        ("Oeiras", _dias(10, 31) + _dias(11, 2, 3, 10, 17, 24) + _dias(12, 1, 8, 12, 13, 15, 22)),
        ("Amadora", _dias(10, 22, 23, 25)),
    ],
    "Matheus": [
        ("Benfica", _dias(10, 24, 25, 26, 28, 29, 30, 31) + _dias(11, 2)),
        ("Algueirão", _dias(11, 1)),
    ],
    "Bruce": [
        ("Alfragide", _dias(11, 1)),
    ],
}
OPCIONAL = "Benfica"
CRIADO_POR = "whatsapp-out-dez-2026"


def _horas(horas):
    return "%s–%s" % (calendario.hora_curta(calendario.hhmm(horas[0])), calendario.hora_curta(calendario.hhmm(horas[1])))


def _achar(docs, nome, procurar, o_que, empresas):
    """O `_um` do arranque com o nome trocado pelo PROCURAR_JSON; ao parar, diz como desfazer."""
    try:
        return _um(docs, procurar.get(nome, nome), o_que, empresas)
    except Paragem as e:
        raise Paragem("%s — desfaz-se sem mudar o ficheiro, com -e PROCURAR_JSON='{\"%s\": "
                      "\"<um nome mais comprido>\"}'." % (e, nome))


def planear(idas, utilizadores, lojas, empresas, existentes, procurar=None):
    """Decide tudo sem tocar na base. Devolve {gravar, divididas, divididas_em, saltadas};
    levanta `Paragem` antes de qualquer escrita se um nome ou uma loja não forem inequívocos.
    `empresas` = {company_id: nome}; `procurar` troca um nome curto por um mais comprido (o
    PROCURAR_JSON)."""
    procurar = procurar or {}
    gestores = [u for u in utilizadores if u.get("role") in calendario.GESTORES]
    pessoas = {nome: _achar(gestores, nome, procurar, "A pessoa", empresas) for nome in idas}
    saltadas, divididas, divididas_em, gravar = [], [], [], []
    # Só as lojas do açaí (a pizzaria tem uma loja com o mesmo nome) e só as com horário.
    empresa = _um([{"id": i, "name": n} for i, n in empresas.items()], EMPRESA_DAS_LOJAS,
                  "A empresa das lojas", {})
    da_empresa = [l for l in lojas if l.get("company_id") == empresa["id"]]
    com_horario = [l for l in da_empresa if l.get("horario")]
    por_loja = {}
    for nome in sorted({loja for pares in idas.values() for loja, _datas in pares}):
        alvo = " %s " % _normal(procurar.get(nome, nome))
        if not [l for l in com_horario if alvo in " %s " % _normal(l.get("name"))]:
            existe = [l for l in da_empresa if alvo in " %s " % _normal(l.get("name"))]
            motivo = "ainda não tem horário" if existe else "não existe na empresa «%s»" % empresa["name"]
            if nome == OPCIONAL:
                saltadas.append("%s %s: as idas de %s ficam de fora." % (nome, motivo, nome))
                continue
            raise Paragem("A loja «%s» %s — correr primeiro o arranque da Fase 1." % (nome, motivo))
        por_loja[nome] = _achar(com_horario, nome, procurar,
                                "A procurar só na empresa «%s», a loja" % empresa["name"], empresas)

    # Por pessoa e dia, as lojas abertas nesse dia, pela ordem da mensagem.
    dias = {}
    for nome, pares in idas.items():
        for nome_loja, datas in pares:
            loja = por_loja.get(nome_loja)
            if not loja:
                continue
            for iso in datas:
                estado, janela = calendario.horario_do_dia(loja, date.fromisoformat(iso))
                if estado != "aberta":
                    saltadas.append("%s %s em %s: a loja está %s nesse dia." % (
                        nome, calendario.data_curta(iso), loja["name"], estado.replace("_", " ")))
                    continue
                dias.setdefault((nome, iso), []).append((loja, janela))

    for (nome, iso), lista in sorted(dias.items(), key=lambda par: (par[0][1], par[0][0])):
        if len(lista) > 2:
            raise Paragem("%s está em %d lojas a %s — dividir à mão." % (nome, len(lista), calendario.data_curta(iso)))
        partes = lista
        if len(lista) == 2:
            (loja1, j1), (loja2, j2) = lista
            meio = (j1[0] + j1[1]) // 2
            partes = [(loja1, (j1[0], meio)), (loja2, (max(meio, j2[0]), j2[1]))]
            if partes[1][1][0] >= partes[1][1][1]:
                raise Paragem("%s a %s: %s fecha antes do meio do horário de %s — dividir à mão." % (
                    nome, calendario.data_curta(iso), loja2["name"], loja1["name"]))
            divididas.append("%s %s: %s %s + %s %s" % (nome, calendario.data_curta(iso), loja1["name"],
                                                       _horas(partes[0][1]), loja2["name"], _horas(partes[1][1])))
            divididas_em.append((iso, (loja1["id"], loja2["id"])))
        for loja, horas in partes:
            nova = {"data": iso, "location_id": loja["id"], "user_id": pessoas[nome]["id"],
                    "inicio": calendario.hhmm(horas[0]), "fim": calendario.hhmm(horas[1])}
            resumo = "%s %s %s %s" % (nome, calendario.data_curta(iso), loja["name"], _horas(horas))
            if [e for e in existentes if all(e.get(k) == nova[k] for k in ("data", "location_id", "user_id", "inicio"))]:
                saltadas.append("%s: já estava gravada." % resumo)
                continue
            choque = calendario.choques([nova], existentes)
            if choque:
                outra = choque[0][1]
                saltadas.append("%s: choca com a ida já gravada das %s às %s — fica a que lá está." % (
                    resumo, calendario.hora_curta(outra["inicio"]), calendario.hora_curta(outra["fim"])))
                continue
            gravar.append(nova)
    return {"gravar": gravar, "divididas": divididas, "divididas_em": divididas_em, "saltadas": saltadas}


def _buracos_que_ficam(plano, dados):
    """Para cada divisão, os buracos que ficam nas duas lojas nesse dia — com a escala real,
    as ausências aprovadas, as idas já gravadas e as do plano (o mesmo cálculo do ecrã)."""
    textos = []
    for iso, ids in plano["divididas_em"]:
        lojas_do_dia = calendario.dia_do_calendario(date.fromisoformat(iso), dados)["lojas"]
        ficam = ["%s %s" % (l["nome"], ", ".join("%s–%s" % (calendario.hora_curta(b["inicio"]), calendario.hora_curta(b["fim"]))
                                                  for b in l["buracos"]))
                 for l in lojas_do_dia if l["location_id"] in ids and l["buracos"]]
        textos.append("; ".join(ficam) or "nenhum nestas duas lojas")
    return textos


def executar(db, gravar, escrever=print):
    """0 = feito (ou ensaio feito); 1 = parado sem gravar nada."""
    # Um JSON partido rebenta aqui, antes de qualquer leitura ou escrita na base.
    procurar = json.loads(os.environ.get("PROCURAR_JSON") or "{}")
    empresas = {e["id"]: e.get("name") for e in db.companies.find({}, {"_id": 0, "id": 1, "name": 1})}
    utilizadores = list(db.users.find({}, {"_id": 0, "id": 1, "name": 1, "role": 1, "employee_id": 1}))
    lojas = list(db.locations.find(
        {}, {"_id": 0, "id": 1, "name": 1, "company_id": 1, "horario": 1, "aberta_desde": 1}))
    existentes = list(db.bolso_idas.find({"data": {"$gte": "2026-10-01", "$lte": "2026-12-31"}}, {"_id": 0}))
    try:
        plano = planear(IDAS, utilizadores, lojas, empresas, existentes, procurar)
    except Paragem as e:
        escrever("PARADO: %s" % e)
        escrever("Nada foi gravado.")
        return 1
    for linha in plano["saltadas"]:
        escrever("fica de fora: " + linha)
    novas = [dict(i, id="plano-%d" % n) for n, i in enumerate(plano["gravar"])]
    dados = {
        "lojas": lojas, "utilizadores": utilizadores, "idas": existentes + novas,
        "empregados": list(db.employees.find({}, {"_id": 0, "id": 1, "name": 1, "location_id": 1})),
        "atribuicoes": list(db.work_schedule_assignments.find({}, {"_id": 0})),
        "modelos": list(db.work_schedule_templates.find({}, {"_id": 0, "id": 1, "work_days": 1, "dias": 1})),
        "ausencias": list(db.leave_requests.find(
            {"status": "aprovado"}, {"_id": 0, "employee_id": 1, "start_date": 1, "end_date": 1, "status": 1})),
    }
    for linha, ficam in zip(plano["divididas"], _buracos_que_ficam(plano, dados)):
        escrever("DIVIDIDO AO MEIO: %s · ficam buracos: %s" % (linha, ficam))
    nomes = {u["id"]: u.get("name") for u in utilizadores}
    for user_id in sorted({i["user_id"] for i in plano["gravar"]}, key=lambda u: nomes.get(u) or ""):
        escrever("%s: %d idas" % (nomes.get(user_id), sum(1 for i in plano["gravar"] if i["user_id"] == user_id)))
    escrever("Total: %d idas a gravar." % len(plano["gravar"]))
    if not gravar:
        escrever("ENSAIO — nada foi gravado. Para gravar, correr de novo com GRAVAR=1.")
        return 0
    agora = datetime.now(timezone.utc).isoformat()
    feitas = 0
    for ida in plano["gravar"]:
        doc = dict(ida, id=str(uuid.uuid4()), criado_por=CRIADO_POR, criado_em=agora,
                   alterado_por=None, alterado_em=None)
        try:
            db.bolso_idas.insert_one(doc)
            feitas += 1
        except DuplicateKeyError:
            escrever("não gravada (alguém a marcou entretanto): %s %s" % (ida["data"], ida["user_id"]))
    escrever("Gravadas %d idas." % feitas)
    return 0


if __name__ == "__main__":
    from pymongo import MongoClient

    cliente = MongoClient(os.environ["MONGO_URL"])
    sys.exit(executar(cliente[os.environ["DB_NAME"]], os.environ.get("GRAVAR") == "1"))
