#!/usr/bin/env bash
# Sync HORARIO das vendas Vendus -> fin_sales (rapido, SEM CMV) do "Gestao Lisbonb".
# O CMV e calculado 1x/noite pelo fin-vendus-cron.sh (03:30) e e preservado aqui.
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy).
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/fin/cron/vendus?key="+os.environ["CRON_KEY"]+"&with_cost=false", method="POST"), timeout=3000).read().decode()[:300])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) vendus hourly disparado"
