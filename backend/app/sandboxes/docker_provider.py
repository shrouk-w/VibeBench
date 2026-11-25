import asyncio
import ipaddress
from dataclasses import dataclass
from typing import Protocol

import docker
from docker.errors import NotFound

from app.settings import Settings

LABEL = "dev.vibebench.namespace"


@dataclass(frozen=True)
class Sandbox:
    container_id: str
    network_id: str
    address: str
    backend_address: str

    def url(self, port: int) -> str:
        return f"http://{self.address}:{port}"


class SandboxProvider(Protocol):
    async def create(self, name: str, configuration: dict[str, str]) -> Sandbox: ...
    async def inspect(self, sandbox: Sandbox) -> str: ...
    async def stop(self, sandbox: Sandbox) -> None: ...
    async def destroy(self, sandbox: Sandbox) -> None: ...


class DockerSandboxProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = docker.from_env(timeout=12)
        self.labels = {LABEL: settings.docker_namespace}

    async def create(self, name: str, configuration: dict[str, str]) -> Sandbox:
        return await asyncio.to_thread(self._create, name, configuration)

    def _create(self, name: str, configuration: dict[str, str]) -> Sandbox:
        settings = self.settings
        network = self.client.networks.create(
            name,
            driver="bridge",
            internal=True,
            enable_ipv6=False,
            labels=self.labels,
        )
        container = None
        try:
            backend_address = self._connect(network, settings.backend_container)
            proxy_address = self._connect(network, settings.egress_container)
            proxy = f"http://{proxy_address}:3128"
            no_proxy = f"localhost,127.0.0.1,{backend_address}"
            environment = {
                **configuration,
                "HOME": "/tmp/vb-home",
                "XDG_DATA_HOME": "/vb-state/data",
                "XDG_STATE_HOME": "/vb-state/state",
                "XDG_CONFIG_HOME": "/vb-state/config",
                "XDG_CACHE_HOME": "/vb-cache/xdg",
                "NPM_CONFIG_CACHE": "/vb-cache/npm",
                "PNPM_HOME": "/vb-cache/pnpm",
                "npm_config_store_dir": "/vb-cache/pnpm/store",
                "PIP_CACHE_DIR": "/vb-cache/pip",
                "BUN_INSTALL_CACHE_DIR": "/vb-cache/bun",
                "HTTPS_PROXY": proxy,
                "https_proxy": proxy,
                "HTTP_PROXY": proxy,
                "http_proxy": proxy,
                "NO_PROXY": no_proxy,
                "no_proxy": no_proxy,
            }
            config = environment.get("OPENCODE_CONFIG_CONTENT")
            if config:
                environment["OPENCODE_CONFIG_CONTENT"] = config.replace(
                    "http://vb-broker.invalid", f"http://{backend_address}:8000"
                )
            container = self.client.containers.run(
                settings.sandbox_image,
                detach=True,
                name=name,
                network=network.name,
                labels=self.labels,
                runtime=settings.sandbox_runtime,
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit=f"{settings.sandbox_memory_mb}m",
                memswap_limit=f"{settings.sandbox_memory_mb}m",
                nano_cpus=int(settings.sandbox_cpus * 1_000_000_000),
                pids_limit=settings.sandbox_pids,
                tmpfs={
                    "/workspace": (
                        f"rw,nodev,nosuid,size={settings.workspace_mb}m,uid=1000,gid=1000"
                    ),
                    "/tmp": "rw,nodev,nosuid,size=192m,mode=1777",
                    "/vb-state": (
                        f"rw,nodev,nosuid,size={settings.agent_state_mb}m,uid=1000,gid=1000,mode=0700"
                    ),
                    "/vb-cache": (
                        f"rw,nodev,nosuid,size={settings.sandbox_cache_mb}m,uid=1000,gid=1000,mode=0700"
                    ),
                },
                log_config={"type": "none"},
                environment=environment,
            )
            container.reload()
            address = str(
                ipaddress.IPv4Address(
                    container.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]
                )
            )
            return Sandbox(container.id, network.id, address, backend_address)
        except Exception:
            if container:
                container.remove(force=True, v=True)
            self._remove_network(network)
            raise

    async def destroy(self, sandbox: Sandbox) -> None:
        await asyncio.to_thread(self._destroy, sandbox)

    async def inspect(self, sandbox: Sandbox) -> str:
        container = await asyncio.to_thread(self.client.containers.get, sandbox.container_id)
        return container.status

    async def stop(self, sandbox: Sandbox) -> None:
        container = await asyncio.to_thread(self.client.containers.get, sandbox.container_id)
        await asyncio.to_thread(container.stop, timeout=5)

    def _destroy(self, sandbox: Sandbox) -> None:
        try:
            self.client.containers.get(sandbox.container_id).remove(force=True, v=True)
        except NotFound:
            pass
        try:
            self._remove_network(self.client.networks.get(sandbox.network_id))
        except NotFound:
            pass

    def _remove_network(self, network):
        network.reload()
        managed_services = {self.settings.backend_container, self.settings.egress_container}
        for endpoint, connection in (network.attrs.get("Containers") or {}).items():
            if connection.get("Name") not in managed_services:
                continue
            try:
                network.disconnect(endpoint, force=True)
            except NotFound:
                continue
        network.remove()

    def _connect(self, network, name):
        container = self.client.containers.get(name)
        network.connect(container)
        network.reload()
        return str(
            ipaddress.IPv4Address(
                network.attrs["Containers"][container.id]["IPv4Address"].split("/", 1)[0]
            )
        )

    async def cleanup_orphans(self) -> None:
        await asyncio.to_thread(self._cleanup_orphans)

    def _cleanup_orphans(self):
        filters = {"label": [f"{LABEL}={self.settings.docker_namespace}"]}
        for container in self.client.containers.list(all=True, filters=filters):
            try:
                container.remove(force=True, v=True)
            except NotFound:
                continue
        for network in self.client.networks.list(filters=filters):
            try:
                self._remove_network(network)
            except NotFound:
                continue
