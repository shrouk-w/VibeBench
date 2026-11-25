import asyncio

from fastapi.testclient import TestClient

from app.agents.opencode import Agent
from app.main import create_app
from app.models.catalog import Model, ModelsDevProvider
from app.sandboxes.docker_provider import Sandbox
from app.settings import Settings

ORIGIN = "http://localhost:8080"


class Catalog:
    def __init__(self, _):
        pass

    async def list(self):
        return [Model("opencode", "test", "OpenCode", "Test", True, False, True)]


class Sandboxes:
    client = None

    def __init__(self, _):
        self.created = []
        self.destroyed = []
        self.orphans_checked = False

    async def cleanup_orphans(self):
        self.orphans_checked = True

    async def create(self, name, env):
        self.created.append((name, env))
        while len(self.created) < 2:
            await asyncio.sleep(0)
        side = name[-1]
        return Sandbox(side, "network-" + side, "127.0.0.1", "127.0.0.1")

    async def destroy(self, sandbox):
        self.destroyed.append(sandbox.container_id)


class Agents:
    def __init__(self, _):
        self.prompts = []
        self.aborts = []

    async def connect(self, sandbox, password, provider, model):
        return Agent("http://127.0.0.1", sandbox.container_id, password, provider, model)

    async def prompt(self, agent, text):
        self.prompts.append((agent.session_id, text))

    async def abort(self, agent):
        self.aborts.append(agent.session_id)

    async def events(self, agent, connected):
        connected.set()
        yield {
            "type": "message.part.delta",
            "properties": {
                "sessionID": agent.session_id,
                "field": "text",
                "delta": agent.password,
            },
        }
        await asyncio.Event().wait()


def test_comparison_lifecycle():
    app = create_app(
        Settings(sandbox_enabled=True, backend_container="mock", egress_container="mock"),
        sandbox_factory=Sandboxes,
        agent_factory=Agents,
        catalog_factory=Catalog,
    )
    spec = {"prompt": "Create a web app", "models": [{"provider": "opencode", "model": "test"}] * 2}
    with TestClient(app) as client:
        assert client.post("/api/comparisons", json=spec).status_code == 403
        response = client.post("/api/comparisons", headers={"Origin": ORIGIN}, json=spec)
        assert response.status_code == 201
        session = response.json()
        path = f"/api/comparisons/{session['id']}"
        auth = {"Authorization": f"Bearer {session['token']}", "Origin": ORIGIN}
        assert client.get(path).status_code == 404
        assert client.post("/api/comparisons", headers=auth, json=spec).status_code == 429
        manager = app.state.manager
        with client.websocket_connect(path + "/events", headers={"Origin": ORIGIN}) as socket:
            socket.send_json({"token": session["token"], "after": 0})
            events = []
            for _ in range(4):
                update = socket.receive_json()
                events.extend(update["events"])
                if len(manager.agents.prompts) == 2:
                    break
            assert len(manager.agents.prompts) == 2
            assert manager.agents.prompts[0][1] == manager.agents.prompts[1][1]
            assert {item[0] for item in manager.agents.prompts} == {"a", "b"}
            assert any(event["text"] == "[redacted]" for event in events)
        assert client.post(path + "/a/stop", headers=auth).status_code == 204
        assert client.get(path, headers=auth).json()["runs"]["a"]["status"] == "stopped"
        assert (
            client.post(
                path + "/a/instructions",
                headers=auth,
                json={
                    "prompt": "Add favorites",
                },
            ).status_code
            == 204
        )
        assert manager.agents.aborts == ["a"]
        assert manager.agents.prompts[-1][1].startswith("Add favorites")
        assert manager.sandboxes.orphans_checked
        assert client.delete(path, headers=auth).status_code == 204
        assert sorted(manager.sandboxes.destroyed) == ["a", "b"]
        assert not manager.previews
        assert client.get(path, headers=auth).status_code == 404


def test_catalog_filters_discovery_and_status():
    providers = {
        "opencode": {
            "name": "OpenCode",
            "models": {
                "available": {"name": "Live", "tool_call": True, "cost": {"input": 0, "output": 0}},
                "stale": {"name": "Old", "tool_call": True, "cost": {"input": 0, "output": 0}},
                "paid": {"name": "Paid", "tool_call": True, "cost": {"input": 1, "output": 1}},
            },
        }
    }
    models = ModelsDevProvider.parse(providers, {"available", "paid"})
    assert [model.id for model in models] == ["available"]
