import asyncio

from transcribe_worker.worker import Status

REASONS = {200: "OK", 404: "Not Found", 503: "Service Unavailable"}


async def serve_health(status: Status, port: int) -> asyncio.Server:
    """Tiny HTTP endpoint for Kubernetes: /healthz while the process is up, /readyz while the broker is."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = await reader.readline()
        while (await reader.readline()) not in (b"\r\n", b"\n", b""):
            pass
        parts = request_line.split()
        path = parts[1].decode() if len(parts) > 1 else "/"
        if path == "/healthz":
            code = 200
        elif path == "/readyz":
            code = 200 if status.connected else 503
        else:
            code = 404
        body = b'{"status": "ok"}' if code == 200 else b'{"status": "unavailable"}'
        writer.write(
            f"HTTP/1.1 {code} {REASONS[code]}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
        )
        await writer.drain()
        writer.close()

    return await asyncio.start_server(handle, "0.0.0.0", port)
