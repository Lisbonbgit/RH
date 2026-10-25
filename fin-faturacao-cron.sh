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
#
# Duas maneiras de o chamar:
#   fin-faturacao-cron.sh        -> os ultimos 3 dias (de hora a hora; corrige
#                                   ontem, anulacoes tardias, o fecho da noite)
#   fin-faturacao-cron.sh hoje   -> so' o dia de HOJE em Lisboa (ao minuto; e'
#                                   o que poe a app "quase ao vivo")
#
# A TRANCA e' obrigatoria: cada corrida APAGA as linhas do intervalo e volta a
# inseri-las. Duas corridas cruzadas (a de hora a hora e a do minuto) podiam
# apagar as duas e inserir as duas -> o dia de hoje a DOBRAR na app. Com a
# tranca so' corre uma de cada vez: a do minuto desiste se estiver ocupada (a
# seguinte apanha), a de hora a hora espera a sua vez.
cd /root/RH || exit 1
exec 9>/tmp/fin-faturacao.lock
if [ "$1" = "hoje" ]; then
  flock -n 9 || exit 0
  DIA=$(TZ=Europe/Lisbon date +%F)
  QUERY="&since=$DIA&until=$DIA"
else
  flock -w 600 9 || { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) tranca ocupada ha 10 min, desisti"; exit 1; }
  QUERY=""
fi
docker compose exec -T backend python -c 'import os, sys, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/fin/cron/faturacao?key="+os.environ["CRON_KEY"]+sys.argv[1], method="POST"), timeout=3000).read().decode()[:400])' "$QUERY"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) faturacao disparado ${1:-3 dias}"
