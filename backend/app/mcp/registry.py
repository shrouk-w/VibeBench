from dataclasses import dataclass


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
    integrations = (
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
            infrastructure=True,
        ),
        Integration("figma", "Figma", "figma", "Read supported Figma designs.", "OAuth", "remote"),
        Integration(
            "blender", "Blender", "box", "Generate 3D assets.", "None", "local", infrastructure=True
        ),
        Integration(
            "github",
            "GitHub",
            "git-branch",
            "Access repositories.",
            "Scoped GitHub credentials",
            "remote",
        ),
    )

    def config(self, selected: list[str]) -> dict:
        if set(selected) - {entry.id for entry in self.integrations if entry.available}:
            raise ValueError("An MCP integration is unavailable")
        return {
            key: {"type": "remote", "url": "https://mcp.context7.com/mcp", "oauth": False}
            for key in selected
        }
