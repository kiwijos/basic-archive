import time
from collections import OrderedDict


class RateLimiter:
    """At most `limit` requests per client in each window. Counts live in memory, per pod.

    The table never holds more than `max_clients` addresses: when it is full the one seen longest ago
    is forgotten, so a flood of distinct addresses can cost memory only up to that bound.
    """

    def __init__(self, limit: int, window_seconds: float, max_clients: int):
        self._limit = limit
        self._window = window_seconds
        self._max = max_clients
        self._clients: OrderedDict[str, tuple[float, int]] = OrderedDict()

    def check(self, client: str) -> int | None:
        """None when the request may go ahead, else the seconds until the client may try again."""
        now = time.monotonic()
        started, count = self._clients.get(client, (now, 0))
        if now - started >= self._window:
            started, count = now, 0
        if count >= self._limit:
            return max(1, int(started + self._window - now) + 1)
        self._clients[client] = (started, count + 1)
        self._clients.move_to_end(client)
        while len(self._clients) > self._max:
            self._clients.popitem(last=False)
        return None
