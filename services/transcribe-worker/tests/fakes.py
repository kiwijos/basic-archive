"""Stand-ins for what transcribe-worker talks to over HTTP: catalog-api and the image download."""

import json
import re
import socket
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class CuttableProxy:
    """A TCP pass-through to the broker that a test can cut and restore, to simulate losing it."""

    def __init__(self, upstream_host: str, upstream_port: int):
        self._upstream = (upstream_host, upstream_port)
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self._connections: list[socket.socket] = []
        self._refusing = False
        self._lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def port(self) -> int:
        return self._listener.getsockname()[1]

    def cut(self) -> None:
        """Drop every open connection and refuse new ones."""
        with self._lock:
            self._refusing = True
            for connection in self._connections:
                self._close(connection)
            self._connections.clear()

    def restore(self) -> None:
        with self._lock:
            self._refusing = False

    def stop(self) -> None:
        self.cut()
        self._listener.close()

    @staticmethod
    def _close(connection: socket.socket) -> None:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                refusing = self._refusing
            if refusing:
                self._close(client)
                continue
            try:
                upstream = socket.create_connection(self._upstream, timeout=5)
            except OSError:
                self._close(client)
                continue
            with self._lock:
                self._connections += [client, upstream]
            for source, target in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(source, target), daemon=True).start()

    def _pipe(self, source: socket.socket, target: socket.socket) -> None:
        try:
            while chunk := source.recv(65536):
                target.sendall(chunk)
        except OSError:
            pass
        finally:
            self._close(source)
            self._close(target)


class FakeCatalog:
    """Answers the few catalog-api calls the worker makes, and records what it was sent."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.review_status: dict[str, str] = {}
        self.unknown: set[str] = set()
        self.result_status = 201
        self.failure_status = 200
        self.results: list[dict] = []
        self.failures: list[dict] = []
        self.downloads: Counter = Counter()
        self.status_checks: Counter = Counter()
        self.tokens: set[str] = set()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        catalog = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=None, content_type="application/json"):
                payload = body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _body(self):
                return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

            def do_GET(self):
                if match := re.fullmatch(r"/files/([\w-]+)", self.path):
                    image_id = match.group(1)
                    catalog.downloads[image_id] += 1
                    if image_id in catalog.files:
                        return self._send(200, catalog.files[image_id], "application/octet-stream")
                    return self._send(404, {"detail": "gone"})
                catalog.tokens.add(self.headers.get("Authorization", ""))
                if match := re.fullmatch(r"/api/catalog/images/([\w-]+)/download-url", self.path):
                    image_id = match.group(1)
                    return self._send(200, {"url": f"{catalog.url}/files/{image_id}", "expires_in": 300})
                if match := re.fullmatch(r"/api/catalog/images/([\w-]+)", self.path):
                    image_id = match.group(1)
                    catalog.status_checks[image_id] += 1
                    if image_id in catalog.unknown:
                        return self._send(404, {"detail": "Image not found"})
                    return self._send(200, {"id": image_id, "review_status": catalog.review_status.get(image_id, "pending")})
                self._send(404)

            def do_POST(self):
                catalog.tokens.add(self.headers.get("Authorization", ""))
                body = self._body()
                if match := re.fullmatch(r"/api/catalog/images/([\w-]+)/transcriptions", self.path):
                    catalog.results.append({"image_id": match.group(1), **body})
                    return self._send(catalog.result_status, {"id": "t-1"})
                if match := re.fullmatch(r"/api/catalog/images/([\w-]+)/ocr-failure", self.path):
                    catalog.failures.append({"image_id": match.group(1), **body})
                    return self._send(catalog.failure_status, {"review_status": "failed"})
                self._send(404)

        return Handler
