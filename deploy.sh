#!/usr/bin/env bash
# ============================================================================
# Deploy do "Gestão Lisbonb" (RH + Financeiro + Marketing)
# REGRA DE OURO: a produção corre SEMPRE o `main`. Nada de branches no servidor.
# Uso (no servidor):  cd ~/RH && ./deploy.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# 1) Não fazer deploy com alterações por gravar no servidor (evita perder trabalho)
if [ -n "$(git status --porcelain)" ]; then
  echo "✋ Há alterações por gravar no servidor — deploy CANCELADO."
  echo "   Vê 'git status'. NUNCA se editam ficheiros diretamente no servidor."
  exit 1
fi

# 2) Garantir que estamos no main e atualizado (sem merges/branches acidentais)
git fetch origin
git checkout main
git pull --ff-only origin main

# 3) Build + arranque
docker compose up -d --build

echo "✅ Deploy do 'main' concluído. A produção corre o main."
