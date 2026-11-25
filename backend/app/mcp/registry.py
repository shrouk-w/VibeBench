from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Integration:
    id: str
    name: str
    icon: str
    description: str
    authentication: str
    mechanism: str
    infrastructure: bool = False
    available: bool = False
    environments: tuple[str, ...] = ("web",)


class MCPProvider:
    entries = (
        Integration(
            "context7",
            "Context7",
            "book-open",
            "Retrieve library documentation.",
            "Anonymous service limits apply.",
            "remote",
            available=True,
        ),
        Integration(
            "playwright",
            "Playwright",
            "globe",
            "Test the generated application.",
            "None",
            "local",
            available=True,
        ),
        Integration(
            "figma",
            "Figma",
            "figma",
            "Read Figma designs after signing in.",
            "OAuth",
            "remote",
        ),
        Integration(
            "blender", "Blender", "box", "Generate 3D assets.", "None", "local", infrastructure=True
        ),
        Integration(
            "github",
            "GitHub",
            "git-branch",
            "Read repositories and issues using a fine-grained token.",
            "Scoped GitHub credentials",
            "remote",
            available=True,
        ),
    )

    def __init__(self, figma_configured: bool = False):
        self.integrations = tuple(
            replace(
                entry,
                available=figma_configured,
                description=entry.description
                if figma_configured
                else "Requires an approved Figma MCP OAuth client.",
            )
            if entry.id == "figma"
            else entry
            for entry in self.entries
        )

    def validate(self, selected: list[str]) -> None:
        if set(selected) - {entry.id for entry in self.integrations if entry.available}:
            raise ValueError("An MCP integration is unavailable")

    def config(self, selected: list[str], grants: dict[str, str] | None = None) -> dict:
        self.validate(selected)
        config = {
            "context7": {"type": "remote", "url": "https://mcp.context7.com/mcp", "oauth": False},
            "playwright": {
                "type": "local",
                "command": [
                    "playwright-mcp",
                    "--headless",
                    "--isolated",
                    "--no-sandbox",
                    "--executable-path",
                    "/usr/bin/chromium",
                    "--allowed-origins",
                    "http://127.0.0.1:4173;http://localhost:4173",
                ],
            },
        }
        for name, grant in (grants or {}).items():
            config[name] = {
                "type": "remote",
                "url": f"http://vb-broker.invalid/internal/mcp/{name}",
                "headers": {"Authorization": f"Bearer {grant}"},
                "oauth": False,
            }
        return {name: config[name] for name in selected}
