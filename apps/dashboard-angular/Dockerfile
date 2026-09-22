FROM node:24.15.0-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d AS build

WORKDIR /app

COPY apps/dashboard-angular/package.json apps/dashboard-angular/package-lock.json ./
RUN npm ci

COPY apps/dashboard-angular/ ./
RUN npm run build

FROM caddy:2.11.4-alpine

COPY apps/dashboard-angular/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist/dashboard-angular/browser /srv

EXPOSE 80

