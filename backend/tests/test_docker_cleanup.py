from unittest.mock import Mock

from app.sandboxes.docker_provider import DockerSandboxProvider
from app.settings import Settings


def test_network_cleanup_disconnects_only_attached_platform_services(monkeypatch):
    monkeypatch.setattr("app.sandboxes.docker_provider.docker.from_env", lambda **_: Mock())
    provider = DockerSandboxProvider(
        Settings(backend_container="backend", egress_container="egress")
    )
    network = Mock(attrs={"Containers": {"backend-id": {"Name": "backend"}}})

    provider._remove_network(network)

    network.reload.assert_called_once()
    network.disconnect.assert_called_once_with("backend-id", force=True)
    network.remove.assert_called_once()

    orphan = Mock(attrs={"Containers": {}})
    provider._remove_network(orphan)

    orphan.disconnect.assert_not_called()
    orphan.remove.assert_called_once()
