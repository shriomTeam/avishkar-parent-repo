# Build context: monorepo root (docker build -f apps/web/Dockerfile .).
#
# Next.js bakes these two into the build (rewrites and the browser's call WebSocket), so the API address has to
# be known when the image is built:
#   --build-arg BACKEND_INTERNAL_URL=https://<api>  --build-arg NEXT_PUBLIC_API_URL=https://<api>
FROM node:22-slim AS build
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
WORKDIR /repo
COPY . .
RUN pnpm install --frozen-lockfile
ARG BACKEND_INTERNAL_URL
ARG NEXT_PUBLIC_API_URL
ENV BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @clinic/web build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=8080
# The standalone output keeps the monorepo layout, so the server lives at apps/web/server.js.
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
USER node
CMD ["node", "apps/web/server.js"]
