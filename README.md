# RH grupo Lisbonb

Sistema de gestão de Recursos Humanos (estilo Sesame) para as 3 empresas do grupo.
Inclui gestão de colaboradores, registo de ponto, pedidos de férias/ausências, horários,
documentos, notificações e dashboards.

## Stack

- **Frontend:** React 19 + Tailwind + Shadcn UI
- **Backend:** FastAPI (Python) — API REST com prefixo `/api`
- **Base de dados:** MongoDB (Atlas)
- **Auth:** JWT + bcrypt · **Emails:** Resend

## Estrutura

```
backend/    FastAPI (server.py), requirements, Dockerfile
frontend/   React (src/pages, src/components), Dockerfile + nginx
docker-compose.yml   Orquestração para o VPS
DEPLOY.md   Guia de migração Emergent ➜ Hostinger (passo a passo)
```

## Correr localmente (no seu Mac, para testar)

**Pré-requisitos:** Python 3.11+, Node 20+, uma string de ligação MongoDB (Atlas grátis).

### Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # depois edite o .env
# Gerar o hash da password do admin:
python generate_admin_hash.py "A-Sua-Password"   # cole o hash em ADMIN_PASSWORD_HASH
python server.py              # arranca em http://localhost:8000
```

### Frontend
```bash
cd frontend
cp .env.example .env          # REACT_APP_BACKEND_URL=http://localhost:8000
npm install                   # (ou: yarn)
npm start                     # abre http://localhost:3000
```

## Pôr em produção (Hostinger VPS)

Ver **[DEPLOY.md](DEPLOY.md)** — guia completo: MongoDB Atlas, VPS, Docker, domínio e HTTPS.
Resumo: `docker compose up -d --build`.

## Variáveis de ambiente

Backend (`backend/.env`) e Frontend (`frontend/.env`) — ver os respetivos `.env.example`.
