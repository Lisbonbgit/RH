#!/usr/bin/env python3
"""O vigia: uma vez por dia, avisa por email se uma cópia ou um cron falhou.

Existe porque até 27/10/2026 ninguém era avisado de nada: a importação de
faturas deu TimeoutError todos os dias durante 7 semanas e só ficou no log.

Verifica três coisas e manda UM email só se alguma correr mal:
- as cópias de segurança da noite existem e são de hoje (e a cópia para fora,
  que o Mac do dono vai buscar, não tem mais de 3 dias);
- cada cron escreveu no seu log há pouco tempo (um cron que deixou de correr
  não deixa erro nenhum — só silêncio);
- as linhas novas de cada log desde a última volta não trazem erros.
Às segundas manda sempre, mesmo com tudo bem: se esse email não chegar, é o
próprio vigia que está parado.

Só usa a biblioteca padrão do Python do servidor (corre FORA dos contentores).
    vigia-cron.py           -> verifica e envia se for preciso
    vigia-cron.py --teste   -> mostra o email no ecrã, não envia nem avança
"""
import glob
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone

PARA = ["matheus.moraes@lisbonb.com", "bruce.silva@lisbonb.com"]
ESTADO = "/var/lib/vigia"
H = 3600

# (log, idade máxima em horas, o que é). Um log mais velho do que isto = cron parado.
LOGS = [
    ("/var/log/rh-pontos-app.log", 0.25, "envio dos pontos da app (ao minuto)"),
    ("/var/log/rh-sinc-app.log", 0.5, "faturas da app para o POS (5 em 5 min)"),
    ("/var/log/fin-faturacao.log", 1.5, "faturação do POS para a app Gestão (hora a hora)"),
    ("/var/log/fin-moloni.log", 1.5, "Moloni (hora a hora)"),
    ("/var/log/fin-vendus-hourly.log", 1.5, "Vendus (hora a hora)"),
    ("/var/log/fin-vendus.log", 26, "Vendus (noite)"),
    ("/var/log/fin-ingest.log", 26, "ingestão de faturas (manhã)"),
    ("/var/log/rh-relatorio.log", 26, "relatório diário (22:30)"),
    ("/var/log/rh-plataformas.log", 8 * 24, "relatório das plataformas (segunda)"),
    ("/root/backups-mongo/cron.log", 26, "cópia das bases Mongo (03:15)"),
    ("/root/backups/backup.log", 26, "cópia do Postgres do Menooo (04:00)"),
]

# (padrão do ficheiro, idade máxima em horas, tamanho mínimo em bytes, o que é)
COPIAS = [
    ("/root/backups-mongo/mongo-2*.archive.gz", 26, 10_000_000, "Mongo do RH/Financeiro/POS"),
    ("/root/backups-mongo/mongo-olacai-*.archive.gz", 26, 100_000, "Mongo da app L'Açaí"),
    ("/root/backups-mongo/segredos-*.p7m", 26, 1_000, "chaves (.env) encriptadas"),
    ("/root/backups/comanda-*.sql.gz", 26, 10_000, "Postgres do Menooo"),
    ("/root/backups-mongo/.ultima-copia-fora", 72, 1, "cópia para fora (o Mac vai buscar)"),
]

ERRO = re.compile(
    r'Traceback|"errors": ?\["|"erros": ?\["|\bERRO\b|HTTP Error|desisti|'
    r'"enviado": ?false|Connection refused|timed out|rebentou'
)


def _idade_h(caminho):
    return (time.time() - os.path.getmtime(caminho)) / H


def _linhas_novas(log):
    """As linhas escritas desde a última volta. Na primeira, nenhuma."""
    marca = os.path.join(ESTADO, log.strip("/").replace("/", "_") + ".pos")
    tamanho = os.path.getsize(log)
    try:
        inicio = int(open(marca).read())
    except (OSError, ValueError):
        inicio = tamanho
    if inicio > tamanho:  # o log foi cortado/rodado: lê-se do princípio
        inicio = 0
    with open(log, "rb") as f:
        f.seek(inicio)
        texto = f.read().decode("utf-8", "replace")
    return texto.splitlines(), (marca, tamanho)


def verificar():
    problemas, marcas = [], []

    for padrao, max_h, minimo, nome in COPIAS:
        ficheiros = sorted(glob.glob(padrao), key=os.path.getmtime)
        if not ficheiros:
            problemas.append(f"Cópia «{nome}»: não existe nenhuma ({padrao}).")
            continue
        ultimo = ficheiros[-1]
        if _idade_h(ultimo) > max_h:
            problemas.append(f"Cópia «{nome}»: a mais recente tem {_idade_h(ultimo):.0f} h "
                             f"({os.path.basename(ultimo)}).")
        elif os.path.getsize(ultimo) < minimo:
            problemas.append(f"Cópia «{nome}»: a de hoje é pequena demais "
                             f"({os.path.getsize(ultimo)} bytes, {os.path.basename(ultimo)}).")

    for log, max_h, nome in LOGS:
        if not os.path.exists(log):
            problemas.append(f"Cron «{nome}»: o log {log} não existe.")
            continue
        if _idade_h(log) > max_h:
            problemas.append(f"Cron «{nome}»: não escreve nada há {_idade_h(log):.1f} h "
                             f"(devia ser no máximo {max_h:g} h) — deixou de correr?")
        linhas, marca = _linhas_novas(log)
        marcas.append(marca)
        erros = [l for l in linhas if ERRO.search(l)]
        if erros:
            exemplo = re.sub(r"key=[^&\s\"']+", "key=***", erros[-1].strip())[:300]
            problemas.append(f"Cron «{nome}»: {len(erros)} linha(s) com erro desde ontem. "
                             f"Última: {exemplo}")

    disco = shutil.disk_usage("/")
    if disco.used / disco.total > 0.85:
        problemas.append(f"Disco do servidor a {disco.used / disco.total:.0%}.")

    return problemas, marcas


def _env(nome):
    for linha in open("/root/RH/backend/.env"):
        if linha.startswith(nome + "="):
            return linha.split("=", 1)[1].strip().strip("'\"")
    return None


def enviar(assunto, texto):
    corpo = json.dumps({
        "from": _env("SENDER_EMAIL") or "noreply@lisbonb.com",
        "to": PARA, "subject": assunto, "text": texto,
    }).encode()
    pedido = urllib.request.Request(
        "https://api.resend.com/emails", data=corpo, method="POST",
        headers={"Authorization": "Bearer " + _env("RESEND_API_KEY"),
                 "Content-Type": "application/json", "User-Agent": "vigia-lisbonb"})
    return urllib.request.urlopen(pedido, timeout=30).read().decode()


def main():
    teste = "--teste" in sys.argv
    os.makedirs(ESTADO, exist_ok=True)
    problemas, marcas = verificar()
    agora = datetime.now(timezone.utc)
    if problemas:
        assunto = f"⚠️ Servidor Lisbonb: {len(problemas)} coisa(s) a ver"
        texto = "O vigia do servidor encontrou isto:\n\n" + "\n\n".join(
            f"• {p}" for p in problemas)
    elif agora.weekday() == 0:
        assunto = "✅ Servidor Lisbonb: tudo bem esta semana"
        texto = ("Cópias de segurança e crons em dia. Este email chega todas as "
                 "segundas — se um dia não chegar, é o vigia que está parado.")
    else:
        assunto = None
    if assunto:
        texto += f"\n\n— vigia-cron.py em 187.124.4.163, {agora:%Y-%m-%d %H:%M} UTC"
    if teste:
        print(assunto or "(nada a enviar hoje)")
        print(texto if assunto else "")
        return
    if assunto:
        print(agora.isoformat(), "enviado:", enviar(assunto, texto))
    else:
        print(agora.isoformat(), "tudo bem, nada enviado")
    # Só depois de enviar: se o envio rebentar, as mesmas linhas voltam amanhã.
    for marca, tamanho in marcas:
        with open(marca, "w") as f:
            f.write(str(tamanho))


if __name__ == "__main__":
    main()
