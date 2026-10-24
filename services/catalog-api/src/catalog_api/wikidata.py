import logging
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Archive text is mostly Swedish, so Swedish labels and descriptions win when Wikidata has both.
LANGUAGES = ("sv", "en")
MAX_CANDIDATES = 10
QID = re.compile(r"^Q[1-9][0-9]{0,15}$")


def entity_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}"


@dataclass(frozen=True)
class Candidate:
    id: str
    label: str
    description: str | None

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description, "url": entity_url(self.id)}


class WikidataUnavailable(Exception):
    """Wikidata could not give an answer. The message is written for the person who asked, and the status
    is what catalog-api should answer with: 504 when Wikidata was too slow, 502 for anything else."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


UNEXPECTED = WikidataUnavailable("Wikidata sent an unexpected answer.")


class WikidataClient:
    """The two calls to Wikidata the archive makes: search by name, and read one entity.

    Wikidata is somebody else's service, so every call is bounded: each try has a timeout, a failure that
    may pass (a timeout, no connection, 429, a 5xx) is tried again after a growing pause, anything that would
    not change (any other status, an answer that is not what Wikidata sends) is not, and one operation never
    takes longer than its budget however the tries add up.
    """

    def __init__(
        self,
        api_url: str,
        user_agent: str,
        timeout: float,
        attempts: int = 3,
        backoff: float = 0.5,
        budget: float = 10.0,
    ):
        self._url = api_url
        self._timeout = timeout
        self._attempts = attempts
        self._backoff = backoff
        self._budget = budget
        self._http = httpx.Client(headers={"User-Agent": user_agent, "Accept": "application/json"})

    def close(self) -> None:
        self._http.close()

    def _get(self, params: dict, deadline: float) -> dict:
        failure = WikidataUnavailable("Wikidata did not answer in time. Try again in a moment.", 504)
        for attempt in range(1, self._attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                response = self._http.get(
                    self._url, params={**params, "format": "json"}, timeout=min(self._timeout, remaining)
                )
            except httpx.TimeoutException:
                failure = WikidataUnavailable("Wikidata did not answer in time. Try again in a moment.", 504)
            except httpx.TransportError as error:
                failure = WikidataUnavailable("Wikidata is not available right now. Try again in a moment.")
                logger.warning("Wikidata could not be reached: %s", error)
            else:
                status = response.status_code
                if status == 429:
                    failure = WikidataUnavailable(
                        "Wikidata says there are too many requests (status 429). Try again in a moment."
                    )
                elif status >= 500:
                    failure = WikidataUnavailable(
                        f"Wikidata is not available right now (status {status}). Try again in a moment."
                    )
                elif status != 200:
                    raise WikidataUnavailable(f"Wikidata refused the request (status {status}).")
                else:
                    try:
                        body = response.json()
                    except ValueError:
                        raise UNEXPECTED from None
                    if not isinstance(body, dict) or "error" in body:
                        logger.warning("Wikidata answered with an error: %s", str(body)[:200])
                        raise UNEXPECTED
                    return body
            logger.warning("Wikidata attempt %d of %d failed: %s", attempt, self._attempts, failure.message)
            pause = self._backoff * 2 ** (attempt - 1)
            if attempt == self._attempts:
                break
            if deadline - time.monotonic() <= pause:
                break  # no time left to wait and try again, and trying at once would hammer a struggling service
            time.sleep(pause)
        raise failure

    def _deadline(self) -> float:
        return time.monotonic() + self._budget

    def search(self, name: str) -> list[Candidate]:
        """Items whose label matches, from every language searched, one entry per item."""
        merged: dict[str, Candidate] = {}
        deadline = self._deadline()
        for language in LANGUAGES:
            found = self._get(
                {"action": "wbsearchentities", "search": name, "language": language, "uselang": language, "type": "item", "limit": MAX_CANDIDATES},
                deadline,
            )
            items = found.get("search", [])
            if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get("id"), str) for i in items):
                raise UNEXPECTED
            for item in items:
                known = merged.get(item["id"])
                # Swedish is searched first and its wording wins; English only fills in what Swedish lacks.
                if known is None:
                    merged[item["id"]] = Candidate(item["id"], item.get("label") or item["id"], item.get("description"))
                elif not known.description and item.get("description"):
                    merged[item["id"]] = Candidate(known.id, known.label, item["description"])
        return list(merged.values())[:MAX_CANDIDATES]

    def entity(self, qid: str) -> Candidate | None:
        """One item as Wikidata describes it now, or None when Wikidata has no such item."""
        answer = self._get(
            {"action": "wbgetentities", "ids": qid, "props": "labels|descriptions", "languages": "|".join(LANGUAGES)},
            self._deadline(),
        )
        entities = answer.get("entities")
        if not isinstance(entities, dict):
            raise UNEXPECTED
        item = entities.get(qid)
        if item is None:
            # A merged item is answered under the id it now has, with a note of where it came from.
            item = next(
                (e for e in entities.values() if isinstance(e, dict) and isinstance(e.get("redirects"), dict) and e["redirects"].get("from") == qid),
                None,
            )
        if item is None:
            return None
        if not isinstance(item, dict):
            raise UNEXPECTED
        if "missing" in item:
            return None
        found = item.get("id")
        labels, descriptions = item.get("labels", {}), item.get("descriptions", {})
        if not (isinstance(found, str) and QID.match(found) and isinstance(labels, dict) and isinstance(descriptions, dict)):
            raise UNEXPECTED
        return Candidate(found, self._wording(labels) or found, self._wording(descriptions))

    @staticmethod
    def _wording(values: dict) -> str | None:
        """The text in the first language wanted that has any, or None; anything not shaped like Wikidata's is refused."""
        for language in LANGUAGES:
            entry = values.get(language)
            if entry is None:
                continue
            if not (isinstance(entry, dict) and isinstance(entry.get("value"), str)):
                raise UNEXPECTED
            return entry["value"]
        return None
