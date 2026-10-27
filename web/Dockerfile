FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# SITE_URL нужен уже при сборке: статические страницы кладут в HTML абсолютные canonical/og:url (B25).
# docker-compose передаёт сюда значение из .env.
ARG SITE_URL=http://localhost:8080
ENV NEXT_TELEMETRY_DISABLED=1 SITE_URL=$SITE_URL
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ARG SITE_URL=http://localhost:8080
# HOSTNAME=0.0.0.0: иначе standalone-сервер Next слушает только адрес по имени контейнера
# (первая сеть compose), и общий Caddy из сети tuc_edge получает «connection refused».
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0 SITE_URL=$SITE_URL
COPY --from=build /app/.next/standalone ./
# public/ (фото работ и т.п.) standalone-сборка сама не копирует
COPY --from=build /app/public ./public
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
