# VibeBench tasks

- [ ] 01 Repository, health checks and local development
- [ ] 02 In-memory sessions and ownership
- [ ] 03 Docker sandboxes and production isolation
- [ ] 04 OpenCode server integration
- [ ] 05 Model discovery and credential isolation
- [ ] 06 Interactive previews
- [ ] 07 MCP registry
- [ ] 08 Live activity
- [ ] 09 Comparison interface
- [ ] 10 ZIP exports
- [ ] 11 Security and abuse prevention
- [ ] 12 Resource cleanup
- [ ] 13 Local Compose stack
- [ ] 14 ARM64 deployment
- [ ] 15 Cloudflare networking
- [ ] 16 Unit and end-to-end tests
- [ ] 17 Documentation and license

## Decisions

- Web applications are the only execution environment in V1.
- The backend owns ephemeral session state. One worker owns the Docker resources.
- The production launch gate stays closed until isolation and abuse controls are verified.
