#!/usr/bin/env bash
#
# Assistente para ativar/atualizar os emails (Resend) sem mexer no resto.
# Atualiza RESEND_API_KEY, SENDER_EMAIL e FRONTEND_URL no backend/.env.
#
# Uso (dentro da pasta RH):   bash update-emails.sh
#
set -e
cd "$(dirname "$0")"
ENV="backend/.env"

if [ ! -f "$ENV" ]; then
  echo "backend/.env não existe. Corra primeiro: bash setup.sh"
  exit 1
fi

echo ""
echo "=== Ativar emails (Resend) ==="
read -rp "1) Chave da Resend (RESEND_API_KEY, começa por re_): " RESEND_API_KEY
read -rp "2) Email remetente (ex.: nao-responder@lisbonb.com): " SENDER_EMAIL
read -rp "3) Endereço do site [https://rh.lisbonb.com]: " FRONTEND_URL
FRONTEND_URL=${FRONTEND_URL:-https://rh.lisbonb.com}

# Substitui (ou acrescenta) uma chave no .env, mantendo o resto intacto
update_key() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV"; then
    grep -v "^${key}=" "$ENV" > "${ENV}.tmp" && mv "${ENV}.tmp" "$ENV"
  fi
  printf "%s=%s\n" "$key" "$val" >> "$ENV"
}

update_key RESEND_API_KEY "$RESEND_API_KEY"
update_key SENDER_EMAIL "$SENDER_EMAIL"
update_key FRONTEND_URL "$FRONTEND_URL"

echo ""
echo "✅ Emails configurados em $ENV"
echo "   Remetente : $SENDER_EMAIL"
echo "   Site      : $FRONTEND_URL"
echo ""
echo "Agora reinicie o backend:"
echo "  docker compose up -d --force-recreate backend"
echo ""
