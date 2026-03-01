FROM oven/bun:1-alpine AS install

WORKDIR /app
COPY package.json ./
RUN bun install --production

FROM oven/bun:1-alpine

# Install kubectl for Job management
RUN apk add --no-cache curl \
  && ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') \
  && curl -Lo /usr/local/bin/kubectl \
    "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/${ARCH}/kubectl" \
  && chmod +x /usr/local/bin/kubectl \
  && apk del curl

WORKDIR /app
COPY --from=install /app/node_modules ./node_modules
COPY package.json ./
COPY src ./src

USER bun
EXPOSE 3002

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:3002/healthz || exit 1

CMD ["bun", "run", "src/index.ts"]
