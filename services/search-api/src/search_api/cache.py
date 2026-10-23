import time
from collections import OrderedDict


class TtlCache:
    """A small in-memory cache whose entries expire quickly, so a change in the index shows up within seconds.

    It holds at most `max_entries` answers and `max_bytes` of body in total, dropping the least
    recently used first, and never keeps a single answer larger than the whole budget.
    """

    def __init__(self, ttl_seconds: float, max_entries: int, max_bytes: int):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._bytes = 0
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, body = entry
        if time.monotonic() >= expires:
            self._drop(key)
            return None
        self._entries.move_to_end(key)
        return body

    def put(self, key: str, body: bytes) -> None:
        if len(body) > self._max_bytes:
            return
        if key in self._entries:
            self._drop(key)
        self._entries[key] = (time.monotonic() + self._ttl, body)
        self._bytes += len(body)
        while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
            self._drop(next(iter(self._entries)))

    def _drop(self, key: str) -> None:
        _, body = self._entries.pop(key)
        self._bytes -= len(body)
