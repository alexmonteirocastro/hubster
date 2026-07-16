# syntax=docker/dockerfile:1

FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

ARG VITE_CHAT_REQUEST_TIMEOUT_MS=90000
ENV VITE_CHAT_REQUEST_TIMEOUT_MS=$VITE_CHAT_REQUEST_TIMEOUT_MS

# Production defaults — local Compose overrides via docker-compose.override.yml.
# Process ENV wins over .env.production so Compose can keep sources + Ollama-aware copy.
ARG VITE_SHOW_SOURCES=false
ENV VITE_SHOW_SOURCES=$VITE_SHOW_SOURCES

ARG VITE_LOADING_MESSAGE="Searching and thinking — this can take a few moments, thanks for your patience."
ENV VITE_LOADING_MESSAGE=$VITE_LOADING_MESSAGE

RUN npm run build

FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
