# Ubuntu ARM64 deployment

OCI documents 1,500 A1 OCPU hours and 9,000 GB-hours per month for Always Free tenancies, equivalent to 2 OCPUs and 12 GB of RAM. Confirm the entitlement and regional capacity in the console before choosing an Ubuntu 24.04 ARM64 VM. Start with one comparison per host. No cloud resources are created by these scripts.

Use a dedicated VM. Allow inbound SSH only from your administration address in the OCI network security group. The Compose stack binds Caddy to loopback. Docker controls its own forwarding rules, so an Ubuntu host firewall alone is insufficient for Docker-published ports. Keep the rest of the platform off the public internet. [OCI Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) · [Docker packet filtering](https://docs.docker.com/engine/network/packet-filtering-firewalls/)

On a fresh VM with console access, `sudo bash infrastructure/scripts/firewall-ubuntu.sh ADMIN_CIDR` configures the host SSH rule. The CIDR must include your active SSH client.

```sh
ssh ubuntu@SERVER_IP
git clone https://github.com/shrouk-w/VibeBench.git
cd VibeBench
sudo bash infrastructure/scripts/bootstrap-ubuntu.sh
sudo bash infrastructure/scripts/deploy-local.sh
```

The bootstrap configures the official Docker and gVisor package sources and smoke-tests runsc. The deployment script builds the images, creates the first local configuration with a random gateway secret, starts Compose and checks FastAPI readiness. For updates, end active sessions, pull with `git pull --ff-only` and run the deployment script again. For a private browser smoke test, use an SSH forward from your workstation.

```sh
ssh -N -L 8080:127.0.0.1:8080 ubuntu@SERVER_IP
```

A browser resolving `*.localhost` to loopback can open previews through the same forward. Session cleanup runs on backend restart. Ubuntu ARM64 deployment and runsc integration still require testing on a target VM.

## Cloudflare preparation

A locally managed tunnel configuration template is in `infrastructure/cloudflare/config.example.yml`. The optional Compose `tunnel` profile expects `infrastructure/cloudflare/config.yml` and `credentials.json` in that same directory. Keep both files private. In a full DNS setup, first-level names such as `bench.example.com` and `vb-<capability>.example.com` fit Universal SSL coverage. A dedicated registered zone avoids a wildcard overlapping unrelated services. Verify the wildcard DNS record, certificate coverage and catch-all behavior before using the tunnel. The application rejects public mode pending production verification.

Turnstile uses a public build-time `NEXT_PUBLIC_TURNSTILE_SITE_KEY` and server-only `VB_TURNSTILE_SECRET`. Set `VB_TURNSTILE_HOSTNAME` to the widget hostname. FastAPI validates the success flag, hostname and action `comparison`. Rebuild the frontend after changing the site key. [Tunnel ingress](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/) · [Wildcard DNS](https://developers.cloudflare.com/dns/manage-dns-records/reference/wildcard-dns-records/) · [Universal SSL](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/) · [Turnstile](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)
