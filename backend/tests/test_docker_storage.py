from unittest.mock import Mock

from app.sandboxes.docker_provider import DockerSandboxProvider
from app.settings import Settings


def test_agent_state_and_package_caches_have_separate_mounts(monkeypatch):
    docker_client = Mock()
    monkeypatch.setattr("app.sandboxes.docker_provider.docker.from_env", lambda **_: docker_client)
    provider = DockerSandboxProvider(Settings(sandbox_cache_mb=300, agent_state_mb=96))
    monkeypatch.setattr(provider, "_connect", lambda *_: "172.22.0.2")
    docker_client.networks.create.return_value.name = "test-network"
    docker_client.containers.run.return_value.attrs = {
        "NetworkSettings": {"Networks": {"test-network": {"IPAddress": "172.22.0.3"}}}
    }

    provider._create("test-sandbox", {})

    options = docker_client.containers.run.call_args.kwargs
    assert "size=96m" in options["tmpfs"]["/vb-state"]
    assert "size=300m" in options["tmpfs"]["/vb-cache"]
    assert options["environment"]["XDG_DATA_HOME"].startswith("/vb-state/")
    for key in (
        "NPM_CONFIG_CACHE",
        "npm_config_store_dir",
        "PIP_CACHE_DIR",
        "BUN_INSTALL_CACHE_DIR",
    ):
        assert options["environment"][key].startswith("/vb-cache/")
