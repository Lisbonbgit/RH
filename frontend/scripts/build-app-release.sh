#!/usr/bin/env bash
#
# Build da APP nativa (Android AAB de release) de forma segura e repetível.
#
# Uso:   cd frontend && ./scripts/build-app-release.sh
#
# Faz: yarn build -> VERIFICA que o backend absoluto ficou no bundle (trava de
# segurança) -> cap sync -> gradle bundleRelease (assinado). Se o URL do backend
# NÃO estiver no bundle, ABORTA (impede enviar uma versão que não fala com o
# servidor). Lembra-te de subir versionCode/versionName no android/app/build.gradle
# ANTES de correr, senão a Play Store recusa o upload.

set -euo pipefail

# Diretório do frontend (onde este script vive é frontend/scripts).
cd "$(dirname "$0")/.."

BACKEND_URL="https://rh.lisbonb.com"

# node/yarn não estão no PATH por omissão nesta máquina.
export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"
# JDK do Android Studio (não há java no PATH).
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"

echo "==> 1/4 build web (CI=false)"
CI=false yarn build

echo "==> 2/4 TRAVA: confirmar backend absoluto no bundle"
if ! grep -rq "$BACKEND_URL" build/static/js/*.js; then
  echo "ERRO: '$BACKEND_URL' NÃO está no bundle." >&2
  echo "      Falta o REACT_APP_BACKEND_URL absoluto (ver frontend/.env.production)." >&2
  echo "      Build ABORTADO para não enviar uma app que não chega ao backend." >&2
  exit 1
fi
echo "    OK: backend '$BACKEND_URL' presente no bundle."

echo "==> 3/4 cap sync android"
npx cap sync android

echo "==> 4/4 gradle bundleRelease (AAB assinado)"
( cd android && ./gradlew bundleRelease )

AAB="android/app/build/outputs/bundle/release/app-release.aab"
VER=$(grep -E "versionName|versionCode" android/app/build.gradle | tr -s ' ' | sed 's/^ *//')
echo ""
echo "PRONTO. AAB: $(pwd)/$AAB"
echo "Versão:"
echo "$VER"
echo "-> Carregar este .aab na Play Console (Teste interno -> Criar nova versão)."
