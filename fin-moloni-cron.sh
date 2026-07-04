#!/usr/bin/env bash
# Sync noturno das vendas Moloni (Purple House) -> fin_sales do "Gestao Lisbonb".
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy).
# A CRON_KEY e lida do ambiente do contentor (nao fica no crontab).
# Por omissao o endpoint sincroniza os ultimos 3 dias.
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/fin/cron/moloni?key="+os.environ["CRON_KEY"], method="POST"), timeout=3000).read().decode()[:400])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) moloni sync disparado"
