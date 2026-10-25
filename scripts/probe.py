"""Sends requests at a steady rate until told to stop, and reports every one that did not get a 2xx answer.

probe.py URL RATE STOP_FILE [HEADER_FILE]

Each request opens its own connection, as separate visitors would. Exits 1 if any request failed, 0 if none did,
and prints how many were sent. The header file, if given, holds one header line (a staff token, kept off the command line).
"""

import collections
import os
import sys
import threading
import time
import urllib.error
import urllib.request

WORKERS = 4
TIMEOUT = 30  # long enough to tell a request that was merely slow from one that never got an answer
SLOW = 2.0


def main() -> int:
    url, rate, stop_file = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    headers = {}
    if len(sys.argv) > 4:
        name, _, value = open(sys.argv[4]).read().strip().partition(":")
        headers[name] = value.strip()
    outcomes: collections.Counter = collections.Counter()
    failures: list[tuple[float, str]] = []  # seconds since the start, and what happened
    slow: list[tuple[float, float]] = []  # seconds since the start, and how long a successful request took
    begun = time.monotonic()
    lock = threading.Lock()
    interval = WORKERS / rate

    def work() -> None:
        while not os.path.exists(stop_file):
            started = time.monotonic()
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    response.read()
                    result = "ok" if 200 <= response.status < 300 else f"status {response.status}"
            except urllib.error.HTTPError as error:
                result = f"status {error.code}"
            except Exception as error:  # noqa: BLE001 - a refused or reset connection is a failure to count, not to crash on
                result = f"error {type(error).__name__}"
            took = time.monotonic() - started
            with lock:
                outcomes[result] += 1
                if result != "ok":
                    failures.append((time.monotonic() - begun, result))
                elif took > SLOW:
                    slow.append((time.monotonic() - begun, took))
            time.sleep(max(0.0, interval - (time.monotonic() - started)))

    threads = [threading.Thread(target=work) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    failed = {kind: count for kind, count in outcomes.items() if kind != "ok"}
    print(f"{sum(outcomes.values())} requests, {outcomes['ok']} ok" + (f", FAILED: {failed}" if failed else ""))
    if slow:
        print(f"  {len(slow)} answered, but slowly (over {SLOW:g} s); the slowest took {max(t for _, t in slow):.1f} s, at " + ", ".join(f"{at:.1f}s" for at, _ in sorted(slow)[:6]))
    if failures:
        print("  failures at: " + ", ".join(f"{at:.1f}s {what}" for at, what in sorted(failures)[:12]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
