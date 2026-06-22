# ===== RH grupo Lisbonb - Frontend (React) =====
# Etapa 1: build dos ficheiros estáticos
FROM node:20-alpine AS build

WORKDIR /app

# O frontend e o backend são servidos no mesmo domínio através do nginx,
# por isso o URL do backend fica vazio -> os pedidos vão para /api (mesma origem).
ARG REACT_APP_BACKEND_URL=""
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
# Evita que avisos do ESLint façam o build falhar
ENV CI=false

COPY package.json yarn.lock* package-lock.json* ./
# --legacy-peer-deps: o projeto usa date-fns 4 com react-day-picker 8,
# que pede uma versão mais antiga de date-fns (conflito de peer dependency).
RUN if [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
    else npm install --legacy-peer-deps; fi

COPY . .
RUN if [ -f yarn.lock ]; then yarn build; else npm run build; fi

# Etapa 2: servir com nginx
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
