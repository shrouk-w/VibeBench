# Architecture

The Next.js frontend sends the prompt and two model selections to FastAPI. The session manager assigns independent runs and acquires a Docker sandbox for each. OpenCode serves its native HTTP API inside each sandbox and receives the same application prompt with shared preview instructions. A bounded in-memory activity stream feeds the WebSocket. Agent cancellation leaves the sandbox and its application running until session cleanup.

Each sandbox has a temporary workspace and its own bridge. The backend reaches it on fixed application and agent ports. Caddy fronts the browser API and sends capability-based preview hosts to the preview provider. The preview provider maps those hosts to registered sandbox destinations. Future execution environments can supply independent sandbox and preview providers. MCP configuration belongs to the agent and applies independently of the preview type.

## References

- [OpenCode v1.2.27 source and releases](https://github.com/anomalyco/opencode/tree/v1.2.27)
- [Models.dev](https://models.dev/)
- [Docker SDK for Python](https://docker-py.readthedocs.io/en/stable/)
- [gVisor installation](https://gvisor.dev/docs/user_guide/install/)
- [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- [OCI Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) currently documents 1,500 A1 OCPU hours and 9,000 GB-hours per month, equivalent to 2 OCPUs and 12 GB RAM for Always Free tenancies.
- [Cloudflare Universal SSL](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/) covers the apex and first-level subdomains on full DNS setups. Use first-level preview hosts such as `vb-<capability>.example.com`.
- [Turnstile token verification](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)
