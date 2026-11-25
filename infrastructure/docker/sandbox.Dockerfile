FROM node:22-bookworm-slim
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git python3 python3-venv ripgrep tini \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g pnpm@10.34.9 \
    && npm cache clean --force \
    && case "$TARGETARCH" in \
      amd64) variant=x64; digest=6fe3820b145857f7ff507d2826058b7acf1fce8258def1498468dd43809e69e8 ;; \
      arm64) variant=arm64; digest=bcd91a3ebe9480ffb1702e5c71168d451150421acc99c6d1abf5edc5e2cb39f5 ;; \
      *) exit 1 ;; \
    esac \
    && curl -fsSL --retry 3 "https://github.com/anomalyco/opencode/releases/download/v1.2.27/opencode-linux-$variant.tar.gz" -o /tmp/opencode.tar.gz \
    && echo "$digest  /tmp/opencode.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin opencode \
    && rm /tmp/opencode.tar.gz \
    && opencode --version
WORKDIR /workspace
USER 1000:1000
ENTRYPOINT ["/usr/bin/tini", "--", "opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
