#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )) || [[ $# != 1 ]]; then
  printf '%s\n' 'Usage: sudo bash firewall-ubuntu.sh ADMIN_CIDR' >&2
  exit 1
fi

# Use with the VM console available. The CIDR must include the current SSH client.
sshd_config=$(sshd -T | awk '$1 == "port" {print $2; exit}')
admin_cidr=$1
apt-get update
apt-get install -y ufw
ufw allow from "$admin_cidr" to any port "$sshd_config" proto tcp
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status
