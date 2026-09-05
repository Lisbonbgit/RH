#!/usr/bin/env bash
# Sincronizacao das faturas da app L'Acai — de 5 em 5 minutos.
#
# Vai buscar ao Vendus os documentos da Caixa Online que NAO sairam do nosso
# POS (a referencia externa deles nao comeca por "pos-") e grava-os na loja
# escolhida em Configuracao -> Lojas. So entram FS e NC: os orcamentos (OT) e
# os recibos (RG) que tambem vivem naquela caixa ficam de fora — medido a
# 2026-09-04, eram 3.582,10 EUR de orcamentos que uma regra mais larga tinha
# importado como receita.
#
# Le sempre HOJE e ONTEM. O ontem existe por duas razoes: apanha a fatura das
# 23h50 que o Vendus so mostrou depois da meia-noite, e apanha as anulacoes do
# dia anterior (uma fatura anulada no painel do Vendus e marcada aqui e deixa
# de contar). Uma anulacao com mais de dois dias NAO e apanhada — e o limite
# conhecido, e esta escrito na especificacao.
#
# Um buraco maior do que 24h (cron parado, API em baixo, uma janela de deploy)
# NAO se recupera sozinho: os dias que passaram pedem-se a mao pelo botao
# "Sincronizar agora" com um intervalo, em Configuracao -> Lojas.
#
# De 5 em 5 minutos e nao mais depressa: cada volta e um pedido ao Vendus por
# dia, mais um por documento novo. A esmagadora maioria das voltas nao tem
# nada para trazer e fica-se pelos dois pedidos.
#
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy), no
# mesmo padrao dos outros crons desta casa. A hora nao importa (corre o dia
# todo), ao contrario do relatorio-diario-cron.sh, onde o servidor estar em
# UTC e Lisboa nao morde a serio.
#
# Instalar (no servidor), UMA vez:
#   crontab -e
#   */5 * * * *  /root/RH/faturacao-app-cron.sh >> /var/log/rh-sinc-app.log 2>&1
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/faturacao/cron/sincronizar-app?key="+os.environ["CRON_KEY"], method="POST"), timeout=600).read().decode()[:400])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sincronizacao da app disparada"
