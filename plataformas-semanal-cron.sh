#!/usr/bin/env bash
# Relatorio semanal das plataformas de entrega (Uber Eats, Bolt Food, Glovo)
# por email — segunda-feira de manha.
#
# Le a caixa de email configurada em IMAP_MAILBOXES (a MESMA da ingestao de
# faturas), encontra os relatorios que as plataformas mandam de madrugada,
# grava-os, e envia UM email com o resumo para quem estiver na lista do
# backoffice (Painel -> Plataformas).
#
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy),
# no mesmo padrao dos outros crons desta casa.
#
# =============================================================================
# A HORA — e porque e' que isto tem uma seccao so' para si
# =============================================================================
#
# **O servidor esta' em UTC** (`date` no VPS responde UTC), e Lisboa nao esta':
# UTC+1 de finais de Marco a finais de Outubro, UTC+0 no resto do ano. Uma
# linha de crontab escrita a pensar na hora de Lisboa dispara' a' hora errada
# durante metade do ano — foi exactamente o que aconteceu com o relatorio
# diario (ver o cabecalho de relatorio-diario-cron.sh).
#
# O pedido era "as 08:00, que ja' deu tempo de todos os emails entrarem". O que
# **nao pode acontecer** e' disparar ANTES disso: um relatorio que ainda nao
# chegou sai do email como "nao recebido" e a semana fica contada a menos.
#
# Por isso a linha leva `CRON_TZ=Europe/Lisbon`, que o cron do Debian/Ubuntu
# entende e que faz `0 8 * * 1` ser 08:00 de Lisboa o ano inteiro, com a
# mudanca da hora tratada por ele.
#
# **E se o cron desta maquina nao souber o que e' o CRON_TZ?** Nao ha' estrago:
# a linha e' lida como uma variavel de ambiente qualquer e o `0 8 * * 1` passa
# a ser 08:00 UTC — ou seja, 09:00 de Lisboa no Verao e 08:00 no Inverno.
# Uma hora mais tarde no Verao, nunca mais cedo do que as 08:00. E' o lado
# certo para onde errar.
#
# Confirmar qual dos dois esta' a acontecer, sem esperar por segunda:
#   man 5 crontab | grep -i cron_tz     # diz se e' suportado
# ou entao ler a primeira linha que este script escreve no log — leva a hora
# em UTC E a hora de Lisboa, precisamente para nao haver duvida.
#
# =============================================================================
# INSTALAR (no servidor, UMA vez)
# =============================================================================
#
#   chmod +x /root/RH/plataformas-semanal-cron.sh
#   crontab -e
#
# e juntar estas DUAS linhas (a do CRON_TZ tem de vir ANTES da do horario):
#
#   CRON_TZ=Europe/Lisbon
#   0 8 * * 1  /root/RH/plataformas-semanal-cron.sh >> /var/log/rh-plataformas.log 2>&1
#
# ATENCAO: o `CRON_TZ` vale para TODAS as linhas que venham depois dele no
# ficheiro. Se ja' houver outros crons (a ingestao de faturas, o relatorio
# diario, o Vendus), esta linha tem de ficar **no fim do ficheiro**, ou os
# horarios deles mudam sem ninguem dar por isso.
#
# =============================================================================
# O QUE ACONTECE SE CORRER DUAS VEZES
# =============================================================================
#
# A leitura da caixa acontece sempre (um relatorio que chegue a' tarde tem de
# aparecer no painel), mas **o email so' sai uma vez por semana**: a chave da
# semana ISO e' o `_id` de um documento em `plat_envios`, e a segunda insercao
# rebenta antes de o email chegar a ser enviado. A resposta diz por extenso
# "o email desta semana (2026-W35) ja' foi enviado".
#
# Se o envio falhar (o Resend em baixo), a marca e' desfeita e a proxima
# corrida tenta outra vez — a semana nao fica marcada como enviada por causa
# de um email que nunca saiu.
#
# =============================================================================
# EXPERIMENTAR AGORA, sem esperar por segunda-feira
# =============================================================================
#
# Correr este proprio script a' mao faz o mesmo que o cron fara' (incluindo o
# travao de um email por semana):
#
#   /root/RH/plataformas-semanal-cron.sh
#
# Para ver o email sem gastar o envio da semana, usar antes o botao
# "Enviar agora" em Painel -> Plataformas, no backoffice.
set -u
cd /root/RH || exit 1

# 1800 s: a leitura pode ter varias caixas, dezenas de mensagens e uma chamada
# a' IA por relatorio encontrado. O envio em si demora um instante — o tempo
# todo esta' na leitura.
docker compose exec -T backend python -c '
import json, os, urllib.request as u
pedido = u.Request(
    "http://localhost:8000/api/plataformas/cron/semanal?key=" + os.environ["CRON_KEY"],
    method="POST")
resposta = u.urlopen(pedido, timeout=1800).read().decode()
try:
    dados = json.loads(resposta)
    print("lidos=%s enviado=%s %s" % (
        dados.get("lidos"), dados.get("enviado"),
        dados.get("razao") or dados.get("semana_chave") or ""))
    for aviso in (dados.get("avisos") or [])[:5]:
        print("  aviso: %s" % aviso)
except ValueError:
    print(resposta[:400])
'

# A hora nas DUAS referencias, para o log dizer sozinho se o CRON_TZ pegou.
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) (UTC) = $(TZ=Europe/Lisbon date +%H:%M) em Lisboa — plataformas disparado"
