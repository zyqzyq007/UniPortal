# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Build Backend
FROM node:20-alpine AS backend-builder
WORKDIR /app/server
COPY server/package.json server/package-lock.json ./
RUN npm ci
COPY server/prisma ./prisma
RUN npx prisma generate
COPY server/ .
RUN npm run build

# Stage 3: Production Runner
FROM node:20-alpine AS runner
RUN apk add --no-cache openssl
WORKDIR /app

COPY --from=frontend-builder /app/frontend/dist ./client
COPY --from=backend-builder /app/server/dist ./server/dist
COPY --from=backend-builder /app/server/package.json ./server/package.json
COPY --from=backend-builder /app/server/package-lock.json ./server/package-lock.json
COPY --from=backend-builder /app/server/prisma ./server/prisma

WORKDIR /app/server
RUN npm ci --omit=dev
RUN npx prisma generate

RUN mkdir -p storage data temp_uploads

ENV PORT=8080
ENV NODE_ENV=production
ENV SERVE_STATIC=true
ENV STATIC_PATH=/app/client
ENV DATABASE_URL="file:../data/prod.db"
ENV JWT_SECRET="default_secret_please_change"

EXPOSE 8080

CMD ["sh", "-c", "npx prisma db push --schema ./prisma/schema.prisma && node dist/index.js"]