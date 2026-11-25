FROM node:22-bookworm-slim
ARG OPENCODE_VERSION=1.2.27
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git python3 python3-venv ripgrep tini \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "opencode-ai@${OPENCODE_VERSION}" pnpm@10.34.9 \
    && opencode --version
WORKDIR /workspace
USER 1000:1000
ENTRYPOINT ["/usr/bin/tini", "--", "opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
