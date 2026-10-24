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
TIMEOUT = 5


def main() -> int:
    url, rate, stop_file = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    headers = {}
    if len(sys.argv) > 4:
        name, _, value = open(sys.argv[4]).read().strip().partition(":")
        headers[name] = value.strip()
    outcomes: collections.Counter = collections.Counter()
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
            with lock:
                outcomes[result] += 1
            time.sleep(max(0.0, interval - (time.monotonic() - started)))

    threads = [threading.Thread(target=work) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    failed = {kind: count for kind, count in outcomes.items() if kind != "ok"}
    print(f"{sum(outcomes.values())} requests, {outcomes['ok']} ok" + (f", FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
