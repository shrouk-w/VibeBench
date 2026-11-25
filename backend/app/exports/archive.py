import asyncio
import io
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import Protocol

from fastapi import HTTPException

EXCLUDED = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".cache",
    ".opencode",
    ".local",
    ".config",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".ssh",
    ".aws",
    ".docker",
    ".kube",
    ".gnupg",
    "coverage",
}


def safe_path(name: str, is_file: bool) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "workspace":
        return None
    parts = path.parts[1:]
    for part in parts:
        lower = part.lower()
        if (
            lower in EXCLUDED
            or part == ".."
            or "\\" in part
            or ":" in part
            or any(ord(char) < 32 for char in part)
            or lower.startswith((".env", "credentials", "id_rsa", "id_ed25519"))
            or lower in {"auth.json", "opencode.json", "opencode.jsonc", "secrets.json"}
            or lower.endswith((".pem", ".key", ".p12", ".pfx"))
        ):
            return None
    return PurePosixPath(*parts) if is_file else None


class ArtifactExporter(Protocol):
    async def collect(self, runs, *, listing=False): ...


class ZipExporter:
    def __init__(self, docker_client, max_mb):
        self.docker_client = docker_client
        self.max_bytes = max_mb * 1024 * 1024
        self.slots = asyncio.Semaphore(2)

    async def collect(self, runs, *, listing=False):
        if any(not run.sandbox for run in runs):
            raise HTTPException(409, "Project workspace is unavailable")
        async with self.slots:
            return await asyncio.to_thread(self._collect, runs, listing)

    def _collect(self, runs, listing):
        output = io.BytesIO()
        paths = []
        exported = 0
        visited = 0
        seen = set()
        try:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for run in runs:
                    source, _ = self.docker_client.api.get_archive(
                        run.sandbox.container_id, "/workspace"
                    )
                    spool = io.BytesIO()
                    try:
                        for chunk in source:
                            if spool.tell() + len(chunk) > max(self.max_bytes * 4, 128 << 20):
                                raise HTTPException(413, "Workspace is too large to read")
                            spool.write(chunk)
                    finally:
                        source.close()
                    spool.seek(0)
                    with tarfile.open(fileobj=spool, mode="r:*") as tar:
                        for item in tar:
                            visited += 1
                            if visited > 50_000:
                                raise HTTPException(413, "Workspace contains too many entries")
                            path = safe_path(item.name, item.isfile())
                            if path is None:
                                continue
                            name = (
                                str(PurePosixPath(run.side, path)) if len(runs) > 1 else str(path)
                            )
                            if name.casefold() in seen:
                                continue
                            seen.add(name.casefold())
                            if len(seen) > 6000:
                                raise HTTPException(413, "Project contains too many source files")
                            if listing:
                                paths.append(name)
                                continue
                            exported += item.size
                            if exported > self.max_bytes:
                                raise HTTPException(413, "Project exceeds export limit")
                            member = tar.extractfile(item)
                            if member is None:
                                continue
                            with member, archive.open(name, "w") as destination:
                                while chunk := member.read(64 * 1024):
                                    destination.write(chunk)
            return sorted(paths) if listing else output.getvalue()
        except (tarfile.TarError, OSError) as exc:
            raise HTTPException(503, "Workspace could not be exported") from exc
