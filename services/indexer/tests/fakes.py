"""A stand-in for catalog-api's indexing endpoints, the one thing the indexer talks to over HTTP."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "indexer-token"
MAX_PAGE = 100


class FakeCatalog:
    def __init__(self):
        self.views: dict[tuple[str, str], dict] = {}
        self.requests: list[str] = []
        self.failures = 0  # the next this-many view requests answer 503
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body):
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                with fake.lock:
                    fake.requests.append(self.path)
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"detail": "A valid service token is required"})
                single = re.fullmatch(r"/api/catalog/index/(document|ship|organisation)/([0-9a-f-]+)", self.path)
                listing = re.fullmatch(r"/api/catalog/index/(document|ship|organisation)(?:\?(.*))?", self.path)
                if single:
                    with fake.lock:
                        if fake.failures > 0:
                            fake.failures -= 1
                            return self._send(503, {"detail": "unavailable"})
                        view = fake.views.get((single[1], single[2]))
                    return self._send(404, {"detail": "not found"}) if view is None else self._send(200, view)
                if listing:
                    query = dict(part.split("=", 1) for part in (listing[2] or "").split("&") if part)
                    limit = min(int(query.get("limit", 50)), MAX_PAGE)
                    after = query.get("after")
                    with fake.lock:
                        ids = sorted(i for (kind, i) in fake.views if kind == listing[1])
                        items = [fake.views[(listing[1], i)] for i in ids if after is None or i > after]
                    page = items[:limit]
                    return self._send(
                        200, {"items": page, "next_after": page[-1]["id"] if len(items) > limit else None}
                    )
                self._send(404, {"detail": "not found"})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def put(self, view: dict) -> dict:
        with self.lock:
            self.views[(view["entity"], view["id"])] = view
        return view

    def remove(self, entity: str, record_id: str) -> None:
        with self.lock:
            self.views.pop((entity, record_id), None)
