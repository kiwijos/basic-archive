import time

MAX_TRACKED = 10_000


class RateLimiter:
    """At most `limit` requests per client in each window. Counts live in memory, per pod."""

    def __init__(self, limit: int, window_seconds: float):
        self._limit = limit
        self._window = window_seconds
        self._clients: dict[str, tuple[float, int]] = {}

    def check(self, client: str) -> int | None:
        """None when the request may go ahead, else the seconds until the client may try again."""
        now = time.monotonic()
        started, count = self._clients.get(client, (now, 0))
        if now - started >= self._window:
            started, count = now, 0
        if count >= self._limit:
            return max(1, int(started + self._window - now) + 1)
        if len(self._clients) >= MAX_TRACKED:
            self._clients = {c: v for c, v in self._clients.items() if now - v[0] < self._window}
        self._clients[client] = (started, count + 1)
        return None
