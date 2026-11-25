# VibeBench implementation status

- [x] 01 Monorepo, pnpm and uv, health endpoints and local development
- [x] 02 In-memory ownership, independent agent state and cancellation
- [ ] 03 Sandbox implementation and production validation. Local Docker isolation and AMD64/ARM64 images verified. Native gVisor validation pending.
- [ ] 04 OpenCode HTTP integration. Two real sessions accepted prompts. Successful upstream generation remains blocked by OpenCode free quota.
- [ ] 05 Model discovery and BYOK broker. Live free catalog and mock credential forwarding verified. Live BYOK and public free-provider terms pending.
- [ ] 06 Preview routing. Both isolated origins, interactivity and WebSocket forwarding verified locally with fixture applications. Production HTTPS pending.
- [ ] 07 Context7, Playwright and read-only GitHub are selectable. Figma OAuth requires an approved client registration. Account-backed authorization tests and native ARM64 browser validation remain open. Blender is deferred.
- [x] 08 Authenticated, reconnectable WebSockets and bounded agent activity
- [x] 09 Responsive comparison workspace with display controls and source viewer
- [x] 10 Bounded ZIP exports from ephemeral workspaces
- [ ] 11 Local abuse controls and origin, credential, and isolation boundaries. Public launch gate remains closed.
- [x] 12 Explicit cleanup, inactivity and lifetime limits, and startup orphan discovery
- [x] 13 Local Compose stack with private sandbox networking
- [ ] 14 Ubuntu ARM64, gVisor and SSH scripts prepared. Native OCI deployment pending.
- [ ] 15 Optional Cloudflare configuration and Turnstile validation prepared. Live DNS, tunnel and edge TLS validation pending.
- [ ] 16 Pytest, mocked UI and Docker browser smoke tests pass. Successful live inference and public infrastructure tests remain open.
- [x] 17 README, screenshot, architecture, threat model, deployment guides and MIT license

## Decisions

- V1 runs web applications only. Future runtimes can add sandbox and preview providers without changing MCP configuration.
- A single FastAPI worker owns transient sessions and labeled Docker resources.
- Caddy provides the wildcard ingress. FastAPI maps preview capabilities to fixed sandbox addresses.
- The sandbox image pins OpenCode at 1.2.27. Runtime dependencies are limited by an HTTPS egress allowlist.
- The Compose stack binds to localhost. Public deployment requires native runsc, target-host network, HTTPS, and Turnstile verification plus a decision on hosted free-model use.

## Validation evidence

- Windows Docker Desktop using Linux AMD64. Both isolated Docker workspaces served fixture apps with interactive HTTP and WebSocket previews. The browser test downloaded a combined ZIP and verified sandbox removal.
- Backend restart removed a labeled orphan container and its network, including networks without attached platform services.
- The sandbox image built for Linux ARM64 and ran `opencode --version` under emulation. This checks the image, not native gVisor or OCI behavior.
- Two real model attempts used distinct OpenCode free models. OpenCode returned a free usage limit instead of completing app generation. The live smoke test stays opt-in and reports this failure.
- A user-run OpenRouter comparison produced an interactive DeepSeek preview. The other agent ran out of temporary space. A Docker test confirmed that newer sandboxes can still write OpenCode sessions after the package cache fills.
- OpenCode connected to Context7 and Playwright inside a Docker sandbox without account credentials. Playwright navigated to a local fixture with Chromium.
- No public deployment or paid resources were provisioned.
