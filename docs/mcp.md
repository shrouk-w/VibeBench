# MCP integrations

The registry applies the same enabled tools to both OpenCode agents. It accepts registered identifiers and generates OpenCode configuration using predefined endpoints. Integration availability is independent of the execution environment.

| Integration | Mechanism and authentication | Status |
| --- | --- | --- |
| [Context7](https://context7.com/docs/enterprise/security/mcp-oauth) | Fixed remote endpoint. Anonymous calls depend on the upstream service settings. | Configured. Live tool use remains unverified. |
| [Playwright](https://github.com/microsoft/playwright-mcp) | Local server with headless Chromium or a per-sandbox remote service. | Pending browser image, isolation and ARM64 resource testing. |
| [Figma](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/) | Remote OAuth with registration for supported clients. | Pending client access and session-scoped authorization. |
| [Blender](https://github.com/ahujasid/blender-mcp) | A community MCP process connects to a running Blender add-on. Its setup tool can enable the add-on through headless Blender. | Pending a headless runtime test and resource sizing. |
| [GitHub](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md) | The official remote server supports OAuth. Use repository-scoped credentials and a read-only toolset by default. | Pending credential brokering and end-to-end permission tests. |
