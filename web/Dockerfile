# syntax=docker/dockerfile:1
FROM ghcr.io/pnpm/pnpm:12.11.2 AS build

WORKDIR /app

# Use the workspace lockfile, including its pnpm and Node runtime pins.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY web/package.json ./web/package.json
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm --filter web... install --frozen-lockfile --store-dir=/pnpm/store

COPY web ./web
RUN pnpm --filter web build

FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime

COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/web/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
