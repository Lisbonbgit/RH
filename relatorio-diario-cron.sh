#!/usr/bin/env bash
# Relatorio diario de faturacao por email — 23:30 todos os dias.
#
# A hora e' 23:30 e nao 00:00 por decisao do dono: a essa hora as lojas ja'
# fecharam, e o relatorio fala do dia que esta' a acabar (nao do anterior).
# Uma venda depois das 23:30 entra no relatorio do dia seguinte — a hora vai
# escrita no proprio email, para nunca haver duvida do que la' esta' dentro.
#
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy),
# no mesmo padrao dos outros crons desta casa.
#
# **A HORA E' EM UTC, e o servidor esta' em UTC.** Escrevi isto a assumir que
# o relogio do servidor era o de Lisboa e nao e': `date` no VPS responde UTC.
# As `30 23` que aqui estavam disparavam a's 00:30 de Lisboa — ja' no dia
# seguinte, com o relatorio a sair com os numeros de um dia acabado de comecar.
#
# `30 22` em UTC sao 23:30 em Lisboa no Verao. No Inverno (UTC+0) passam a ser
# 22:30 — meia hora mais cedo, e continua depois de as lojas fecharem (os Z sao
# por volta das 21:50). O proprio email diz sempre a hora do corte, por isso
# quem o le' nunca fica em duvida sobre o que esta' la' dentro.
#
# Instalar (no servidor), UMA vez — duas linhas sao dois emails por noite:
#   crontab -e
#   30 22 * * *  /root/RH/relatorio-diario-cron.sh >> /var/log/rh-relatorio.log 2>&1
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/faturacao/cron/relatorio-diario?key="+os.environ["CRON_KEY"], method="POST"), timeout=600).read().decode()[:400])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) relatorio diario disparado"
