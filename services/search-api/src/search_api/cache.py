import time
from collections import OrderedDict


class TtlCache:
    """A small in-memory cache whose entries expire quickly, so a change in the index shows up within seconds."""

    def __init__(self, ttl_seconds: float, max_entries: int):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, body = entry
        if time.monotonic() >= expires:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return body

    def put(self, key: str, body: bytes) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, body)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)
