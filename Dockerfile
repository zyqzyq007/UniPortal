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
COPY server/ .
RUN npx prisma generate
RUN npm run build

# Stage 3: Production Runner
FROM node:20-alpine AS runner
# Install OpenSSL for Prisma
RUN apk add --no-cache openssl
WORKDIR /app

# Copy Frontend build
COPY --from=frontend-builder /app/frontend/dist ./client

# Copy Backend build and resources
COPY --from=backend-builder /app/server/dist ./server/dist
COPY --from=backend-builder /app/server/package.json ./server/package.json
COPY --from=backend-builder /app/server/package-lock.json ./server/package-lock.json
COPY --from=backend-builder /app/server/prisma ./server/prisma

# Install production dependencies for backend
WORKDIR /app/server
RUN npm ci --omit=dev
RUN npx prisma generate

# Create storage directory for uploads if needed
RUN mkdir -p storage

# Environment variables
ENV PORT=8080
ENV NODE_ENV=production
ENV SERVE_STATIC=true
ENV STATIC_PATH=/app/client
ENV DATABASE_URL="file:./prod.db"
# JWT Secret should be overridden in runtime
ENV JWT_SECRET="default_secret_please_change"

EXPOSE 8080

CMD ["sh", "-c", "npx prisma db push && node dist/index.js"]
