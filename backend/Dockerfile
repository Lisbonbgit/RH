# ===== RH grupo Lisbonb - Backend (FastAPI) =====
FROM python:3.11-slim

# Não gerar .pyc e output sem buffer (logs imediatos)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências de sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python primeiro (melhor cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação
COPY . .

# Pasta de uploads persistente (montada como volume no docker-compose)
RUN mkdir -p /app/uploads

EXPOSE 8000

# Healthcheck usa o endpoint /api/health já existente
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

# Produção: 2 workers uvicorn
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
