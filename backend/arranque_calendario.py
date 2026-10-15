"""Arranque do calendário das lojas, fase 1 — corre UMA vez, pelo dono, em produção.

Põe o horário nas 6 lojas e uma escala por pessoa às 7 da semana normal, tal como o
dono as descreveu (docs/superpowers/specs/2026-10-14-calendario-gestao-design.md,
«A semana normal» e «Entrega por fases»).

- Por omissão é um ENSAIO: mostra tudo o que faria e não escreve nada. Só grava com
  GRAVAR=1.
- Lê tudo e decide tudo ANTES da primeira escrita: se um nome casar com mais de uma
  loja/pessoa (ou com nenhuma), PÁRA sem ter escrito nada.
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
from datetime import date

from pymongo import MongoClient

DESDE_POR_OMISSAO = "2026-10-01"
DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

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

# Quando um nome curto casa com mais de um registo em produção: o nome mais comprido a
# procurar em vez dele (ex.: {"Joana": "Joana Pereira"}). Vazio = procura-se a chave.
PROCURAR = {}


class Paragem(Exception):
    """Obriga a parar ANTES de escrever: um nome ambíguo, dados que pedem uma decisão."""


def _normal(texto):
    """Minúsculas, sem acentos, só letras e algarismos separados por um espaço."""
    sem_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acentos.lower()).split())


def _um(docs, chave, o_que):
    """O único documento cujo nome contém `chave` como palavra(s) inteira(s)."""
    alvo = " %s " % _normal(chave)
    achados = [d for d in docs if alvo in " %s " % _normal(d.get("name"))]
    if len(achados) != 1:
        nomes = ", ".join("«%s» (%s)" % (d.get("name"), d.get("id")) for d in achados) or "nenhum"
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


def _planear_lojas(lojas, benfica_desde, linhas, ops):
    """Junta às `linhas` e às `ops` o horário de cada loja; devolve {chave: id}."""
    ids = {}
    for chave, horario in HORARIOS.items():
        if chave == "Benfica" and benfica_desde is None:
            linhas.append("Loja Benfica: SALTADA — falta BENFICA_DESDE=AAAA-MM-DD (o dia em que abre).")
            continue
        loja = _um(lojas, PROCURAR.get(chave, chave), "A loja")
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


def planear(db, desde, benfica_desde):
    """(linhas para mostrar, operações para gravar) — sem escrever nada."""
    lojas = list(db.locations.find({}, {"_id": 0}))
    linhas, ops = [], []
    _planear_lojas(lojas, benfica_desde, linhas, ops)
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
