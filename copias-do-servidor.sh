#!/bin/bash
# Traz as cópias de segurança do servidor (187.124.4.163) para o OneDrive, que
# as sobe para a nuvem: se o servidor morrer, as cópias não morrem com ele.
# Corre pelo launchd (~/Library/LaunchAgents/com.lisbonb.copias-servidor.plist)
# todos os dias às 10:00 e ao ligar o Mac. Versionado em RH/copias-do-servidor.sh.
#
# NUNCA com --delete: se alguém apagar as cópias no servidor, as daqui ficam.
# Aqui guardam-se 30 dias (o servidor guarda 14).
set -euo pipefail
S=root@187.124.4.163
D="$HOME/Library/CloudStorage/OneDrive-Pessoal/Backups-servidor"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=20"
mkdir -p "$D/bases" "$D/imagens"

rsync -a -e "$SSH" --include='mongo-*.archive.gz' --include='segredos-*.p7m' \
  --include='crontab.txt' --exclude='*' "$S:/root/backups-mongo/" "$D/bases/"
rsync -a -e "$SSH" --include='comanda-*.sql.gz' --exclude='*' "$S:/root/backups/" "$D/bases/"

# As imagens carregadas nas apps (não estão em nenhuma base de dados).
for par in \
  rh:/var/lib/docker/volumes/rh_uploads_data/_data \
  estoque:/var/lib/docker/volumes/estoque_uploads_data/_data \
  menooo:/var/lib/docker/volumes/comanda_comanda-uploads/_data \
  menu-tv:/root/menu-tv/uploads \
  app-lacai:/root/olacai/backend/static/uploads; do
  rsync -a -e "$SSH" "$S:${par#*:}/" "$D/imagens/${par%%:*}/"
done

find "$D/bases" -type f \( -name 'mongo-*' -o -name 'comanda-*' -o -name 'segredos-*' \) \
  -mtime +30 -delete

# O vigia do servidor lê esta data: mais de 3 dias sem cópia para fora = aviso.
$SSH "$S" 'date -u +%FT%TZ > /root/backups-mongo/.ultima-copia-fora'
echo "$(date -u +%FT%TZ) OK $(du -sh "$D" | cut -f1)"
