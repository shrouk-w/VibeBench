# The sandbox cannot route outside its internal bridge except through this CONNECT proxy.
import asyncio
import ipaddress
import os
import re
import socket
from contextlib import suppress

HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
DEFAULT_HOSTS = {
    "opencode.ai",
    "models.dev",
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    "mcp.context7.com",
}
ALLOWED = DEFAULT_HOSTS | set(os.environ.get("VB_EXTRA_EGRESS_HOSTS", "").split())
MAX_CONNECTIONS = 80
open_connections = 0


async def resolve(host):
    addresses = await asyncio.get_running_loop().getaddrinfo(
        host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM
    )
    public = []
    for address in addresses:
        ip = ipaddress.IPv4Address(address[4][0])
        if not ip.is_global or ip.is_multicast:
            raise ValueError("Remote address is not globally routable")
        public.append(str(ip))
    return tuple(dict.fromkeys(public))


async def relay(reader, writer):
    while chunk := await asyncio.wait_for(reader.read(64 * 1024), timeout=90):
        writer.write(chunk)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()


async def handle(reader, writer):
    global open_connections
    if open_connections >= MAX_CONNECTIONS:
        writer.close()
        return
    open_connections += 1
    remote_writer = None
    started = False
    try:
        async with asyncio.timeout(10):
            headers = await reader.readuntil(b"\r\n\r\n")
            method, authority, version = headers.split(b"\r\n", 1)[0].decode("ascii").split()
            host, _, port = authority.lower().rpartition(":")
            if (
                method != "CONNECT"
                or version not in {"HTTP/1.0", "HTTP/1.1"}
                or port != "443"
                or not HOSTNAME.fullmatch(host)
                or host not in ALLOWED
            ):
                raise ValueError("Destination outside the allowlist")
            for address in await resolve(host):
                try:
                    remote_reader, remote_writer = await asyncio.open_connection(address, 443)
                    break
                except OSError:
                    continue
            if remote_writer is None:
                raise OSError("Cannot connect to destination")
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        started = True
        async with asyncio.timeout(180):
            async with asyncio.TaskGroup() as group:
                group.create_task(relay(reader, remote_writer))
                group.create_task(relay(remote_reader, writer))
    except (
        TimeoutError,
        OSError,
        ValueError,
        asyncio.LimitOverrunError,
        asyncio.IncompleteReadError,
        ExceptionGroup,
    ):
        if not started:
            with suppress(OSError):
                writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await writer.drain()
    finally:
        open_connections -= 1
        if remote_writer:
            remote_writer.close()
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", 3128, limit=8192)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
