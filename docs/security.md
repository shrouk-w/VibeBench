# Threat model

VibeBench handles prompts, anonymous browsers, generated code and dependencies as untrusted inputs. Anyone with a live preview URL can view that application. Preview URLs contain high-entropy capabilities and expire with their session. Treat them as private links.

| Boundary | Implemented locally |
| --- | --- |
| Browser API | Random ownership tokens, bearer auth, expected mutation and WebSocket origin, request size limits and bounded session creation rates |
| Sandboxes | Unprivileged user, dropped capabilities, read-only root filesystem, bounded tmpfs, memory, CPU and process counts, one internal IPv4 bridge per sandbox, zero published sandbox ports |
| Egress | Separate HTTPS CONNECT proxy, explicit destination allowlist, numeric public IP validation before connecting, time and connection limits |
| Credentials | Session-memory BYOK, fixed upstream endpoints, per-agent grants scoped to the selected model and source IP, bounded calls, response redaction and grant revocation |
| Preview | Separate capability host per agent, sandboxed iframe, isolated origin, no platform headers or browser cookies forwarded to generated applications |
| Export | Bounded workspace reads, regular files only, traversal and symlink rejection, common secret locations excluded |
| Lifecycle | In-memory activity, ephemeral workspaces, expiration and label-based orphan cleanup |

The Docker socket is mounted only in the trusted control plane. A compromise of that service would expose host-level Docker control. The preview proxy currently strips application cookies, which limits generated apps that depend on cookie-backed sessions. HTTPS CONNECT destinations can share public infrastructure, and programmatic egress can send arbitrary data to allowed services. A generated app can use its scoped broker capability while its agent runs, subject to server restrictions. Provider-side key and spend limits offer an independent boundary. Export exclusions cover known names and paths, and application files can still contain secrets supplied in a prompt.

Public deployment remains gated pending native runsc testing, network probes on the deployment host and HTTPS and Turnstile verification. OpenCode documents free chat models for use within OpenCode. Its hosted service terms restrict automated extraction of output, and they provide no clear permission for VibeBench's public multi-user use. Resolve those terms before enabling hosted free models publicly. The local environment uses runc by default. [OpenCode Console models](https://opencode.ai/docs/console/models) · [OpenCode Terms of Use](https://opencode.ai/legal/terms-of-service)
