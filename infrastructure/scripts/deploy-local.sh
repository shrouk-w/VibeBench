#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")/../.."
umask 077
if [[ ! -f .env ]]; then
  secret=$(openssl rand -hex 32)
  sed -e "s/^VB_GATEWAY_SECRET=$/VB_GATEWAY_SECRET=$secret/" \
      -e 's/^VB_SANDBOX_RUNTIME=runc$/VB_SANDBOX_RUNTIME=runsc/' .env.example > .env
fi
if ! grep -qx 'VB_PUBLIC=false' .env || ! grep -qx 'VB_SANDBOX_RUNTIME=runsc' .env; then
  printf '%s\n' 'Deployment requires VB_PUBLIC=false and VB_SANDBOX_RUNTIME=runsc.' >&2
  exit 1
fi
docker info --format '{{json .Runtimes}}' | grep -q '"runsc"'
docker compose config --quiet
docker compose --profile build build sandbox-image
docker compose build backend frontend egress
docker compose up -d --wait
port=$(sed -n 's/^VB_PREVIEW_PORT=//p' .env)
curl -fsS "http://localhost:${port:-8080}/api/health/ready"
