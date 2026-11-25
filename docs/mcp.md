# MCP integrations

Select tools under **MCP integrations** before starting a comparison. Both OpenCode agents get the same tools. If a selected MCP server fails its connection check, VibeBench reports the tool name before sending that agent's prompt.

| Integration | How to connect |
| --- | --- |
| [Context7](https://context7.com/docs/enterprise/security/mcp-oauth) | Enable it to query the hosted documentation service. Anonymous requests are subject to the upstream limits. |
| [Playwright](https://github.com/microsoft/playwright-mcp) | Enable it to test the generated application on port 4173 with headless Chromium in each agent sandbox. |
| [GitHub](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md) | Paste a fine-grained PAT in the launch form. The broker enables read-only repository, issue and pull request tools. |
| [Figma](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/) | Available when the administrator configures an approved Figma MCP OAuth client. Select **Connect Figma** and sign in once before both agents start. |
| Blender | Unavailable. |

## GitHub permissions

Create a fine-grained PAT with a short expiration. Choose **Only select repositories** for private repository access. Grant **Contents** read access and add **Issues** or **Pull requests** read access if needed. Paste it into the VibeBench launch form. The raw token stays in the backend and is discarded at session cleanup. [GitHub token setup](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

## Figma authorization

Set `VB_FIGMA_CLIENT_ID` and `VB_FIGMA_CLIENT_SECRET` for an approved Figma MCP OAuth client whose redirect URI is `http://127.0.0.1:19876/callback`. For local Compose, use a browser on the same machine or forward port 19876 and the application port over SSH. The backend completes OAuth with PKCE and passes read-only capabilities into the agent sandboxes. Account and file access are governed by Figma. [Figma client access](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/)

The OpenCode version pinned in the sandbox uses a different callback path that Figma rejected during a live preflight. The separate, approved OAuth client avoids that incompatible flow. [OpenCode Figma OAuth issue](https://github.com/anomalyco/opencode/issues/65863)

## Playwright in existing checkouts

Rebuild the sandbox image after pulling the integration:

```sh
docker compose --profile build build sandbox-image
docker compose up --build -d --wait
```

Chromium runs inside the Docker isolation boundary with an isolated browser profile. The navigation allowlist keeps normal browser use on the local preview. Native gVisor and ARM64 browser validation remain required for public deployment.
