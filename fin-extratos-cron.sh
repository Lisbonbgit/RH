#!/bin/sh
# Vai buscar à caixa de email os documentos que os BANCOS mandam (extratos e
# avisos de lançamento) e mete os movimentos no Financeiro.
#
# Instalar no crontab do servidor (de 4 em 4 horas; a quota da IA é 20 pedidos
# por dia e é partilhada com a leitura das faturas e das plataformas):
#
#   0 */4 * * * /root/RH/fin-extratos-cron.sh >> /var/log/fin-extratos.log 2>&1
#
# Corre de dentro do contentor para apanhar CRON_KEY e IMAP_MAILBOXES do .env.
set -e
cd /root/RH
docker compose exec -T backend python - <<'PY'
import json
import os
import urllib.request

chave = os.environ.get("CRON_KEY") or ""
if not chave:
    raise SystemExit("CRON_KEY em falta — nada feito")
pedido = urllib.request.Request(
    "http://localhost:8000/api/fin/cron/extratos?key=" + chave, method="POST")
with urllib.request.urlopen(pedido, timeout=3000) as r:
    # Ler a resposta e imprimi-la: o cron das faturas não a lê, e por isso o
    # log dizia "disparado" mesmo quando a corrida devolvia erros.
    print(r.status, r.read().decode("utf-8", "replace")[:2000])
PY
