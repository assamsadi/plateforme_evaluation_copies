# Dockerfile frontend — build Next.js, exécuté via `next start` (pas
# output: "standalone" : son traçage de fichiers ne suit pas correctement la
# structure symlinkée du store pnpm ici — testé, échoue au runtime avec
# "Cannot find module '@swc/helpers/...'" malgré un build réussi. `next
# start` + node_modules complet est plus gros mais fiable avec pnpm.

FROM node:24-slim AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
# --ignore-scripts : "prepare": "husky" plante en Docker (pas de .git dans
# ce contexte de build minimal) — les binaires natifs (@next/swc, parcel-
# watcher) arrivent via optionalDependencies platform-spécifiques, pas via
# script, donc pas affectés par ce flag.
RUN corepack prepare pnpm@11.22.0 --activate \
    && pnpm install --frozen-lockfile --ignore-scripts

FROM node:24-slim AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.22.0 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* sont inlinés dans le bundle client au moment du build (pas
# lisibles/modifiables ensuite au runtime) — d'où ARG + export en ENV avant
# `pnpm build`, et non un simple `environment:` dans docker-compose.yml.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=$NEXT_PUBLIC_GOOGLE_CLIENT_ID
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_OPTIONS="--max-old-space-size=2048"
ENV NEXT_CPU_COUNT=2

RUN pnpm build

FROM node:24-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "-p", "3000"]
