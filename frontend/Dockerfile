FROM node:24.15.0-bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_AGRM_API_BASEURL=/
ARG VITE_AGRM_CSRF_COOKIE_NAME=agrm_csrf
ENV VITE_AGRM_CSRF_COOKIE_NAME=$VITE_AGRM_CSRF_COOKIE_NAME
RUN npm run build
FROM nginx:1.28-alpine
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 8080
