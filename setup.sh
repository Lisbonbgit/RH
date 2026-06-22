#!/usr/bin/env bash
#
# Assistente de configuração do RH grupo Lisbonb.
# Cria o ficheiro backend/.env de forma guiada (gera JWT e hash do admin).
#
# Uso (dentro da pasta RH):   bash setup.sh
#
set -e
cd "$(dirname "$0")"

echo ""
echo "=============================================="
echo "  Configuração do RH grupo Lisbonb"
echo "=============================================="
echo "Responda às perguntas. O que estiver entre [ ] é o valor por defeito"
echo "(carregue Enter para aceitar)."
echo ""

read -rp "1) Cole o MONGO_URL completo do Atlas (com a password): " MONGO_URL
if [ -z "$MONGO_URL" ]; then echo "MONGO_URL é obrigatório."; exit 1; fi

read -rp "2) Nome da base de dados [rh_lisbonb]: " DB_NAME
DB_NAME=${DB_NAME:-rh_lisbonb}

read -rp "3) Email do administrador (para entrar no sistema): " ADMIN_EMAIL
if [ -z "$ADMIN_EMAIL" ]; then echo "O email do administrador é obrigatório."; exit 1; fi

read -rsp "4) Password do administrador (não aparece nada ao escrever): " ADMIN_PW
echo ""
if [ ${#ADMIN_PW} -lt 8 ]; then echo "Use pelo menos 8 caracteres."; exit 1; fi

read -rp "5) Endereço do site [http://187.124.4.163]: " FRONTEND_URL
FRONTEND_URL=${FRONTEND_URL:-http://187.124.4.163}

read -rp "6) Chave da Resend para emails (opcional, Enter para saltar): " RESEND_API_KEY
read -rp "7) Email remetente [onboarding@resend.dev]: " SENDER_EMAIL
SENDER_EMAIL=${SENDER_EMAIL:-onboarding@resend.dev}

echo ""
echo "A gerar segredos de segurança..."

# Chave JWT aleatória
JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')

# Hash bcrypt da password do admin (gerado num contentor Python)
echo "A processar a password do administrador (pode demorar uns segundos)..."
ADMIN_HASH=$(docker run --rm -e PW="$ADMIN_PW" python:3.11-slim sh -c \
  "pip install -q bcrypt >/dev/null 2>&1 && python -c 'import bcrypt,os; print(bcrypt.hashpw(os.environ[\"PW\"].encode(), bcrypt.gensalt()).decode())'")

if [ -z "$ADMIN_HASH" ]; then
  echo "Falha ao gerar o hash da password. Verifique se o Docker está a funcionar."
  exit 1
fi

# Escrever o .env SEM aspas: o docker-compose env_file inclui as aspas como
# parte do valor (não as remove), o que partia o MONGO_URL. env_file também
# não faz interpolação, por isso o '$' do hash bcrypt fica seguro sem aspas.
{
  printf "MONGO_URL=%s\n" "$MONGO_URL"
  printf "DB_NAME=%s\n" "$DB_NAME"
  printf "JWT_SECRET=%s\n" "$JWT_SECRET"
  printf "ADMIN_EMAIL=%s\n" "$ADMIN_EMAIL"
  printf "ADMIN_PASSWORD_HASH=%s\n" "$ADMIN_HASH"
  printf "CORS_ORIGINS=%s\n" "*"
  printf "FRONTEND_URL=%s\n" "$FRONTEND_URL"
  printf "RESEND_API_KEY=%s\n" "$RESEND_API_KEY"
  printf "SENDER_EMAIL=%s\n" "$SENDER_EMAIL"
  printf "PORT=%s\n" "8000"
} > backend/.env

echo ""
echo "=============================================="
echo "  ✅ Configuração criada em backend/.env"
echo "=============================================="
echo "  Base de dados : $DB_NAME"
echo "  Admin         : $ADMIN_EMAIL"
echo "  Site          : $FRONTEND_URL"
echo ""
echo "Próximo passo: arrancar o sistema com"
echo "  docker compose up -d --build"
echo ""
