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

COPY package.json yarn.lock* ./
# Usa yarn (como no Emergent): resolve as dependências antigas (ajv, date-fns)
# sem os conflitos que o npm moderno provoca.
RUN yarn install --network-timeout 600000

COPY . .
RUN yarn build

# Etapa 2: servir com nginx
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
