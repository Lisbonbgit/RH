"""Arranque do calendário das lojas, fase 1 — corre UMA vez, pelo dono, em produção.

Põe o horário nas 6 lojas e uma escala por pessoa às 7 da semana normal, tal como o
dono as descreveu (docs/superpowers/specs/2026-10-14-calendario-gestao-design.md,
«A semana normal» e «Entrega por fases»).

- Por omissão é um ENSAIO: mostra tudo o que faria e não escreve nada. Só grava com
  GRAVAR=1.
- Lê tudo e decide tudo ANTES da primeira escrita: se um nome casar com mais de uma
  loja/pessoa (ou com nenhuma), PÁRA sem ter escrito nada.
- As lojas procuram-se só nos Locais da empresa EMPRESA_DAS_LOJAS; as pessoas, em todas.
- Nunca apaga. Uma escala antiga fecha-se (end_date na véspera de DESDE) e cria-se
  uma nova a partir de DESDE.
- Pode correr-se outra vez: o que já está como devia não se reescreve.

Só usa pymongo e a biblioteca padrão; corre dentro do contentor do backend, lido do
stdin, com o MONGO_URL e o DB_NAME do próprio contentor:

    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T backend python -" < backend/arranque_calendario.py
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e GRAVAR=1 backend python -" < backend/arranque_calendario.py

Variáveis opcionais: DESDE=AAAA-MM-DD (por omissão 2026-10-01), o primeiro dia das
escalas novas; BENFICA_DESDE=AAAA-MM-DD, o dia em que Benfica abre — sem ela, Benfica
fica de fora e o script di-lo; PROCURAR_JSON='{"Joana": "Joana Pereira"}', quando um
nome casa com mais de um registo (junta-se ao PROCURAR, sem mudar este ficheiro).
"""
import json
import os
import re
import sys
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone

from pymongo import MongoClient

DESDE_POR_OMISSAO = "2026-10-01"
DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# As lojas procuram-se só nos Locais desta empresa (palavra inteira no nome): há lojas
# com o mesmo nome noutras empresas do grupo, ex. a «Loja Alfragide» da pizzaria.
EMPRESA_DAS_LOJAS = "Fordaimon"

# O horário de cada loja (0 = segunda … 6 = domingo), na forma que o servidor valida
# (server.HorarioLoja). A chave é o nome a procurar nos Locais.
HORARIOS = {
    "Alfragide": {"abre": "10:00", "fecha": "23:00", "excecoes": [], "fechada": []},
    "Algueirão": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": []},
    "Amadora": {"abre": "14:00", "fecha": "23:00", "excecoes": [], "fechada": []},
    "Belém": {"abre": "11:30", "fecha": "19:00",
              "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}], "fechada": [1]},
    "Benfica": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": []},
    "Oeiras": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": []},
}

# A escala de cada pessoa: (loja, dias, entrada, saída). Horas None = o horário da loja.
# A loja vai explícita em todos os dias, para não depender de a ficha estar certa.
ESCALAS = {
    "Emily": [("Alfragide", (0, 1, 4, 5, 6), "14:00", "23:00")],
    "Beatrice": [("Alfragide", (2, 3, 4, 5, 6), "10:00", "19:00")],
    "Walisson": [("Algueirão", (0, 1, 2, 5, 6), None, None)],
    "Joana": [("Amadora", (0, 1), None, None), ("Oeiras", (2,), None, None),
              ("Algueirão", (3, 4), None, None)],
    "Weber": [("Amadora", (2, 3, 4, 5, 6), None, None)],
    "Emanuela": [("Oeiras", (0, 3, 4, 5, 6), None, None)],
    # Belém fecha à terça: a Rafaela não trabalha à terça (nem lhe conta nas férias).
    "Rafaela": [("Belém", (0, 2, 3, 4, 5, 6), None, None)],
}

# Quando um nome curto casa com mais de um registo em produção: o nome mais comprido a
# procurar em vez dele (ex.: {"Joana": "Joana Pereira"}). Vazio = procura-se a chave.
PROCURAR = {}


class Paragem(Exception):
    """Obriga a parar ANTES de escrever: um nome ambíguo, dados que pedem uma decisão."""


def _normal(texto):
    """Minúsculas, sem acentos, só letras e algarismos separados por um espaço."""
    sem_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acentos.lower()).split())


def _um(docs, chave, o_que, empresas):
    """O único documento cujo nome contém `chave` como palavra(s) inteira(s). Num empate,
    `empresas` (id → nome) diz a empresa de cada candidato."""
    alvo = " %s " % _normal(chave)
    achados = [d for d in docs if alvo in " %s " % _normal(d.get("name"))]
    if len(achados) != 1:
        nomes = ", ".join("«%s» (%s)" % (d.get("name"), ", ".join(
            filter(None, (d.get("id"), empresas.get(d.get("company_id")))))) for d in achados) or "nenhum"
        raise Paragem("%s «%s» casa com %d: %s" % (o_que, chave, len(achados), nomes))
    return achados[0]


def _resumo_horario(h):
    if not h:
        return "sem horário"
    partes = ["%s–%s" % (h["abre"], h["fecha"])]
    partes += ["%s %s–%s" % (DIAS[e["dia"]], e["abre"], e["fecha"]) for e in h.get("excecoes") or []]
    if h.get("fechada"):
        partes.append("fecha " + ", ".join(DIAS[d] for d in h["fechada"]))
    return " · ".join(partes)


def _dia(texto):
    return date.fromisoformat(str(texto)[:10])


def _planear_lojas(lojas, empresas, benfica_desde, linhas, ops):
    """Junta às `linhas` e às `ops` o horário de cada loja da empresa EMPRESA_DAS_LOJAS;
    devolve {chave: id}."""
    empresa = _um([{"id": i, "name": n} for i, n in empresas.items()], EMPRESA_DAS_LOJAS,
                  "A empresa das lojas", {})
    lojas = [loja for loja in lojas if loja.get("company_id") == empresa["id"]]
    ids = {}
    for chave, horario in HORARIOS.items():
        if chave == "Benfica" and benfica_desde is None:
            linhas.append("Loja Benfica: SALTADA — falta BENFICA_DESDE=AAAA-MM-DD (o dia em que abre).")
            continue
        loja = _um(lojas, PROCURAR.get(chave, chave),
                   "A procurar só na empresa «%s», a loja" % empresa["name"], empresas)
        ids[chave] = loja["id"]
        campos = {"horario": horario}
        if chave == "Benfica":
            campos["aberta_desde"] = benfica_desde.isoformat()
        abre = ", abre a %s" % campos["aberta_desde"] if "aberta_desde" in campos else ""
        if all(loja.get(k) == v for k, v in campos.items()):
            linhas.append("Loja %s: já está (%s%s)." % (loja["name"], _resumo_horario(horario), abre))
            continue
        linhas.append("Loja %s: %s → %s%s" % (
            loja["name"], _resumo_horario(loja.get("horario")), _resumo_horario(horario), abre))
        ops.append(("locations", "update_one", {"id": loja["id"]}, {"$set": campos}))
    return ids


def _planear_escalas(lojas, empresas, pessoas, escalas, atribuicoes, ids, desde, linhas, ops):
    """Uma «Escala <Nome>» por pessoa; a atribuição activa fecha na véspera de `desde`
    e uma nova começa em `desde`. Junta tudo às `linhas` e às `ops`."""
    nome_da_loja = {loja["id"]: loja.get("name") for loja in lojas}
    agora = datetime.now(timezone.utc).isoformat()
    vespera = (desde - timedelta(days=1)).isoformat()
    for chave, blocos in ESCALAS.items():
        pessoa = _um(pessoas, PROCURAR.get(chave, chave), "A pessoa", empresas)
        fora = sorted({loja for loja, _, _, _ in blocos if loja not in ids})
        if fora:
            raise Paragem("A escala de %s usa %s, que ficou de fora." % (chave, ", ".join(fora)))
        dias = sorted(
            ({"dia": d, "location_id": ids[loja], "inicio": inicio, "fim": fim}
             for loja, ds, inicio, fim in blocos for d in ds),
            key=lambda x: x["dia"])
        work_days = [d["dia"] for d in dias]
        nome = "Escala %s" % chave

        minhas = sorted((a for a in atribuicoes if a.get("employee_id") == pessoa["id"]),
                        key=lambda a: a["start_date"])
        futuras = [a for a in minhas if _dia(a["start_date"]) > desde]
        if futuras:
            raise Paragem("%s já tem uma escala a começar a %s, depois de %s: decidir à mão."
                          % (pessoa["name"], futuras[0]["start_date"], desde.isoformat()))
        # Sem futuras, a que cobre `desde` é a que não acabou antes dele.
        activa = next((a for a in minhas if not a.get("end_date") or _dia(a["end_date"]) >= desde), None)
        com_o_nome = [e for e in escalas if e.get("name") == nome]
        if len(com_o_nome) > 1:
            raise Paragem("Há %d escalas chamadas «%s»: decidir à mão qual fica." % (len(com_o_nome), nome))
        escala = com_o_nome[0] if com_o_nome else None
        antiga = next((e for e in escalas if activa and e.get("id") == activa.get("template_id")), None)

        linhas.append("%s: %s" % (pessoa["name"], " · ".join(
            "%s %s%s" % (DIAS[d["dia"]], nome_da_loja[d["location_id"]],
                         " %s–%s" % (d["inicio"], d["fim"]) if d["inicio"] else "")
            for d in dias)))
        if pessoa.get("location_id") not in {d["location_id"] for d in dias}:
            linhas.append("  aviso: a ficha diz «%s»; o «Em falta» do painel continua a usar a ficha."
                          % nome_da_loja.get(pessoa.get("location_id"), "sem loja"))

        if escala is None:
            # A hora de início vem da escala antiga: é o que o lembrete do ponto lê.
            start_time = antiga.get("start_time") if antiga else None
            escala = {"id": str(uuid.uuid4()), "name": nome, "work_days": work_days,
                      "start_time": start_time, "dias": dias, "created_at": agora}
            ops.append(("work_schedule_templates", "insert_one", escala))
            linhas.append("  criar «%s» (hora de início: %s%s)" % (
                nome, start_time or "nenhuma", ", da escala «%s»" % antiga["name"] if antiga else ""))
        elif escala.get("dias") != dias or escala.get("work_days") != work_days:
            # O mesmo que o PUT /schedules: o modelo e a cópia das atribuições com o mesmo valor.
            ops.append(("work_schedule_templates", "update_one", {"id": escala["id"]},
                        {"$set": {"dias": dias, "work_days": work_days}}))
            ops.append(("work_schedule_assignments", "update_many", {"template_id": escala["id"]},
                        {"$set": {"work_days": work_days}}))
            linhas.append("  «%s» já existe: passa a ter estes dias" % nome)
        else:
            linhas.append("  «%s» já está assim" % nome)

        if activa and activa.get("template_id") == escala["id"]:
            linhas.append("  atribuição desde %s: já é esta" % activa["start_date"])
            continue
        if activa:
            if _dia(activa["start_date"]) >= desde:
                raise Paragem("A escala actual de %s começa a %s: não se pode fechar na véspera de %s."
                              % (pessoa["name"], activa["start_date"], desde.isoformat()))
            dias_antes = activa.get("work_days") or (antiga or {}).get("work_days") or []
            ops.append(("work_schedule_assignments", "update_one", {"id": activa["id"]},
                        {"$set": {"end_date": vespera}}))
            linhas.append("  fechar «%s» (%s → %s; dias %s) a %s" % (
                antiga["name"] if antiga else "(escala removida)", activa["start_date"],
                activa.get("end_date") or "em aberto", ", ".join(DIAS[d] for d in dias_antes), vespera))
        ops.append(("work_schedule_assignments", "insert_one", {
            "id": str(uuid.uuid4()), "employee_id": pessoa["id"], "template_id": escala["id"],
            "work_days": work_days, "start_date": desde.isoformat(), "end_date": None,
            "created_at": agora}))
        linhas.append("  nova atribuição desde %s (dias %s)" % (
            desde.isoformat(), ", ".join(DIAS[d] for d in work_days)))


def planear(db, desde, benfica_desde):
    """(linhas para mostrar, operações para gravar) — sem escrever nada."""
    empresas = {e["id"]: e.get("name") for e in db.companies.find({}, {"_id": 0, "id": 1, "name": 1})}
    lojas = list(db.locations.find({}, {"_id": 0}))
    pessoas = list(db.employees.find({}, {"_id": 0, "id": 1, "name": 1, "location_id": 1, "company_id": 1}))
    escalas = list(db.work_schedule_templates.find({}, {"_id": 0}))
    atribuicoes = list(db.work_schedule_assignments.find({}, {"_id": 0}))
    linhas, ops = [], []
    ids = _planear_lojas(lojas, empresas, benfica_desde, linhas, ops)
    _planear_escalas(lojas, empresas, pessoas, escalas, atribuicoes, ids, desde, linhas, ops)
    return linhas, ops


def aplicar(db, ops):
    for colecao, operacao, *argumentos in ops:
        getattr(db[colecao], operacao)(*argumentos)


def main():
    gravar = os.environ.get("GRAVAR") == "1"
    try:
        desde = date.fromisoformat(os.environ.get("DESDE") or DESDE_POR_OMISSAO)
        benfica = os.environ.get("BENFICA_DESDE")
        benfica_desde = date.fromisoformat(benfica) if benfica else None
    except ValueError as erro:
        print("PARADO, nada foi escrito: data inválida (%s). Use AAAA-MM-DD." % erro)
        return 1
    # Uma ambiguidade de produção desfaz-se sem commit nem merge:
    # -e PROCURAR_JSON='{"Joana": "Joana Pereira"}'. Um JSON partido rebenta aqui,
    # antes de qualquer leitura ou escrita na base.
    PROCURAR.update(json.loads(os.environ.get("PROCURAR_JSON") or "{}"))
    cliente = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        db = cliente[os.environ["DB_NAME"]]
        try:
            linhas, ops = planear(db, desde, benfica_desde)
        except Paragem as erro:
            print("PARADO, nada foi escrito: %s" % erro)
            return 1
        print("Base %s · escalas novas desde %s" % (os.environ["DB_NAME"], desde.isoformat()))
        print("\n".join(linhas))
        if not gravar:
            print("ENSAIO: %d escritas por fazer; nada foi escrito. "
                  "Para gravar, o mesmo comando com -e GRAVAR=1." % len(ops))
            return 0
        aplicar(db, ops)
        print("GRAVADO: %d escritas." % len(ops))
        return 0
    finally:
        cliente.close()


if __name__ == "__main__":
    sys.exit(main())
