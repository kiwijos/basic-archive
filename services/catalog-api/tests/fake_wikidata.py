"""A stand-in for the Wikidata API at its HTTP boundary: the two calls catalog-api makes, with answers
shaped like the real service's, and a way to script slow, failing and broken replies."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class FakeWikidata:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.requests: list[dict] = []
        self._script: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlparse(self.path)
                params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                action = params.get("action", "")
                with fake._lock:
                    fake.requests.append({"action": action, "params": params, "headers": dict(self.headers), "path": parsed.path})
                    step = fake._script.get(action, []).pop(0) if fake._script.get(action) else None
                if step and step.get("delay"):
                    time.sleep(step["delay"])
                if step and "status" in step:
                    return self._send(step["status"], step.get("body", "{}"), "application/json")
                if step and "raw" in step:
                    return self._send(200, step["raw"], "text/html")
                if step and "json" in step:
                    return self._send(200, json.dumps(step["json"]), "application/json")
                body = fake._answer(action, params)
                self._send(200, json.dumps(body), "application/json")

            def _send(self, status, body, content_type):
                payload = body.encode() if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/w/api.php"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    # ---- what the test arranges -------------------------------------------------------------------------------------

    def reset(self):
        with self._lock:
            self.entities.clear()
            self.requests.clear()
            self._script.clear()

    def add(self, qid: str, *, en: tuple[str, str] | None = None, sv: tuple[str, str] | None = None) -> None:
        """An entity with a (label, description) per language."""
        self.entities[qid] = {"en": en, "sv": sv}

    def script(self, action: str, *steps: dict) -> None:
        """The next answers to an action, one per request, before it goes back to answering normally.
        A step is {"status": 503}, {"delay": seconds}, {"raw": "<html>"} or {"json": {...}}."""
        with self._lock:
            self._script.setdefault(action, []).extend(steps)

    def asked(self, action: str) -> list[dict]:
        return [request for request in self.requests if request["action"] == action]

    # ---- what the real API would answer -----------------------------------------------------------------------------

    def _answer(self, action: str, params: dict) -> dict:
        if action == "wbsearchentities":
            language = params.get("language", "en")
            needle = params.get("search", "").lower()
            limit = int(params.get("limit", 7))
            found = []
            for qid, languages in self.entities.items():
                label, description = (languages.get(language) or (None, None))
                if label and needle and needle in label.lower():
                    found.append({
                        "id": qid, "title": qid, "concepturi": f"http://www.wikidata.org/entity/{qid}",
                        "label": label, "description": description,
                        "match": {"type": "label", "language": language, "text": label},
                    })
            return {"searchinfo": {"search": params.get("search")}, "search": found[:limit], "success": 1}
        if action == "wbgetentities":
            wanted = params.get("ids", "").split("|")
            out = {}
            for qid in wanted:
                languages = self.entities.get(qid)
                if languages is None:
                    out[qid] = {"id": qid, "missing": ""}
                    continue
                out[qid] = {
                    "id": qid, "type": "item",
                    "labels": {lang: {"language": lang, "value": pair[0]} for lang, pair in languages.items() if pair},
                    "descriptions": {lang: {"language": lang, "value": pair[1]} for lang, pair in languages.items() if pair and pair[1]},
                }
            return {"entities": out, "success": 1}
        return {"error": {"code": "badvalue", "info": f"Unrecognized value for parameter \"action\": {action}."}}
