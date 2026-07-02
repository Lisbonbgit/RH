#!/usr/bin/env bash
# Ingestao diaria de faturas por email (IMAP + IA) do "Gestao Lisbonb".
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy).
# A CRON_KEY e lida do ambiente do contentor (nao fica no crontab).
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; u.urlopen(u.Request("http://localhost:8000/api/fin/cron/ingest?key="+os.environ["CRON_KEY"], method="POST"), timeout=3000)'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ingestao disparada"
