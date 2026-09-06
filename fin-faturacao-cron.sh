#!/usr/bin/env bash
# Faturacao do NOSSO POS -> fin_sales, loja a loja, do "Gestao Lisbonb".
#
# Existe porque o sync do Vendus nao consegue fazer isto: desde que o modulo de
# faturacao entrou nas cinco lojas da L'Acai, todas as Faturas Simplificadas
# saem pela MESMA caixa API, e do lado do Vendus essa caixa pertence a uma loja
# so'. Quem sabe a loja de cada documento e' o fat_documentos.
#
# Idempotente por origem (source: "faturacao"): correr de hora a hora nao
# duplica nada e nao toca no que o sync do Vendus escreveu.
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy).
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/fin/cron/faturacao?key="+os.environ["CRON_KEY"], method="POST"), timeout=3000).read().decode()[:400])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) faturacao disparado"
