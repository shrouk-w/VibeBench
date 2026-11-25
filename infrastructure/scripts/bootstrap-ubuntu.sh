#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
  printf '%s\n' 'Run this script with sudo.' >&2
  exit 1
fi
. /etc/os-release
arch=$(dpkg --print-architecture)
if [[ $ID != ubuntu || $arch != arm64 && $arch != amd64 ]]; then
  printf '%s\n' 'Use Ubuntu ARM64 or AMD64.' >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl gnupg git openssl
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $arch
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

curl -fsSL https://gvisor.dev/archive.key | gpg --batch --yes --dearmor -o /etc/apt/keyrings/gvisor.gpg
chmod 0644 /etc/apt/keyrings/gvisor.gpg
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/gvisor.gpg] https://storage.googleapis.com/gvisor/releases release main\n' "$arch" > /etc/apt/sources.list.d/gvisor.list
apt-get update
apt-get install -y runsc
systemctl enable --now docker
if ! docker info --format '{{json .Runtimes}}' | grep -q '"runsc"'; then
  runsc install
  systemctl reload docker
fi
docker run --rm --runtime=runsc hello-world
