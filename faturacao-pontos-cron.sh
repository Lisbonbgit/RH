#!/usr/bin/env bash
# Pontos L'Acai dados na caixa — de 1 em 1 minuto.
#
# Envia a app L'Acai as linhas da fila fat_pontos_app que estao pendentes e ja
# chegaram a hora: o credito de cada fatura das lojas em que a funcionaria leu
# o QR da app, e o estorno de cada nota de credito dessas faturas. A tentativa
# imediata sai logo a seguir a fatura, em segundo plano; este cron e a rede
# para quando a app estava em baixo e para o que um reinicio deixou a meio.
#
# De 1 em 1 minuto e nao de 5: e o tempo que o cliente espera entre pagar e ver
# os pontos na app. Uma volta sem nada para enviar e uma leitura ao Mongo.
#
# Uma linha que falha espera 1, 2, 5, 10 e depois 30 minutos, e passa a
# "falhado" ao fim de 24 h A FALHAR - contadas da primeira falha tecnica e nao
# do nascimento da linha (o backoffice mostra-o no detalhe da fatura). Sem
# APP_LACAI_URL/APP_LACAI_CHAVE no .env espera, sem gastar tentativas, e nao se
# perde nada: e por isso que a ordem de arranque poe a app a andar primeiro.
#
# Corre DENTRO do contentor backend (localhost:8000, sem o proxy pelo meio), no
# mesmo padrao dos outros crons desta casa. A CRON_KEY vem do ambiente do
# contentor, nunca do crontab.
#
# Instalar (no servidor), UMA vez:
#   crontab -e
#   * * * * *  /root/RH/faturacao-pontos-cron.sh >> /var/log/rh-pontos-app.log 2>&1
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/faturacao/cron/pontos-app?key="+os.environ["CRON_KEY"], method="POST"), timeout=300).read().decode()[:400])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) envio dos pontos da app disparado"
