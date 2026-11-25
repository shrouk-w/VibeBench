import asyncio
import io
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import Protocol

from docker.errors import DockerException
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
            or part.endswith((".", " "))
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
    async def collect(self, runs, *, listing=False, source_file=None): ...


class ZipExporter:
    def __init__(self, docker_client, max_mb):
        self.docker_client = docker_client
        self.max_bytes = max_mb * 1024 * 1024
        self.slots = asyncio.Semaphore(2)

    async def collect(self, runs, *, listing=False, source_file=None):
        if any(not run.sandbox for run in runs):
            raise HTTPException(409, "Project workspace is unavailable")
        async with self.slots:
            return await asyncio.to_thread(self._collect, runs, listing, source_file)

    def _snapshot(self, run):
        api = self.docker_client.api
        # Docker's archive endpoint may see the directory beneath a running tmpfs mount.
        cmd = ["/usr/bin/tar", "--format=posix", "--one-file-system", "-cf", "-", "-C", "/"]
        cmd.extend(f"--exclude={name}" for name in sorted(EXCLUDED))
        cmd.extend(("--exclude=.env*", "--", "workspace"))
        execution = api.exec_create(run.sandbox.container_id, cmd, user="1000:1000")["Id"]
        stream = api.exec_start(execution, stream=True, demux=True)
        spool = io.BytesIO()
        try:
            for stdout, _ in stream:
                if not stdout:
                    continue
                if spool.tell() + len(stdout) > min(self.max_bytes * 4, 128 << 20):
                    raise HTTPException(413, "Workspace is too large to read")
                spool.write(stdout)
        finally:
            stream.close()
        if api.exec_inspect(execution)["ExitCode"] not in {0, 1}:
            raise HTTPException(503, "Sandbox workspace could not be read")
        spool.seek(0)
        return spool

    def _collect(self, runs, listing, source_file):
        output = io.BytesIO()
        paths = []
        exported = 0
        visited = 0
        seen = set()
        try:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for run in runs:
                    with (
                        self._snapshot(run) as spool,
                        tarfile.open(fileobj=spool, mode="r:") as tar,
                    ):
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
                            if source_file is not None:
                                if name != source_file:
                                    continue
                                if item.size > 256 * 1024:
                                    raise HTTPException(413, "File is too large to preview")
                                with tar.extractfile(item) as member:
                                    content = member.read()
                                if b"\x00" in content:
                                    raise HTTPException(415, "File is binary")
                                try:
                                    return content.decode("utf-8")
                                except UnicodeDecodeError:
                                    raise HTTPException(415, "File is binary") from None
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
            if source_file is not None:
                raise HTTPException(404, "Source file not found")
            return sorted(paths) if listing else output.getvalue()
        except (DockerException, tarfile.TarError, OSError) as exc:
            raise HTTPException(503, "Workspace could not be exported") from exc
