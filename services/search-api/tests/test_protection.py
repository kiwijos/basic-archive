import time

from conftest import document

API = "/api/search"


def test_repeated_queries_are_answered_from_the_cache_and_other_queries_are_not(client, meili):
    meili.add("documents", document(text="Vega"))

    first = client.get(f"{API}/documents", params={"q": "Vega"})
    second = client.get(f"{API}/documents", params={"q": "Vega"})
    other = client.get(f"{API}/documents", params={"q": "Freja"})

    assert (first.headers["X-Cache"], second.headers["X-Cache"], other.headers["X-Cache"]) == ("MISS", "HIT", "MISS")
    assert second.json() == first.json()
    assert "max-age" in second.headers["Cache-Control"]


def test_parameter_order_does_not_matter_to_the_cache(client, meili):
    client.get(f"{API}/documents?q=Vega&verified_only=true")

    assert client.get(f"{API}/documents?verified_only=true&q=Vega").headers["X-Cache"] == "HIT"


def test_a_cached_answer_expires_so_a_change_shows_up_within_seconds(new_client, meili):
    client = new_client(cache_ttl_seconds=0.3)
    unchecked = document(title="Brev", text="Vega", verified=False)
    meili.add("documents", unchecked)
    assert client.get(f"{API}/documents", params={"q": "Vega"}).json()["hits"][0]["verified"] is False

    meili.add("documents", {**unchecked, "verified": True})
    assert client.get(f"{API}/documents", params={"q": "Vega"}).headers["X-Cache"] == "HIT"
    time.sleep(0.4)

    again = client.get(f"{API}/documents", params={"q": "Vega"})
    assert (again.headers["X-Cache"], again.json()["hits"][0]["verified"]) == ("MISS", True)


def test_a_failed_search_is_never_cached(new_client, meili):
    broken = new_client(meili_url="http://127.0.0.1:1")

    first = broken.get(f"{API}/documents", params={"q": "Vega"})
    second = broken.get(f"{API}/documents", params={"q": "Vega"})

    assert (first.status_code, second.status_code) == (503, 503)
    assert "X-Cache" not in second.headers or second.headers["X-Cache"] == "MISS"


def test_a_client_that_asks_too_often_is_limited_and_others_are_not(new_client, meili):
    client = new_client(rate_limit_per_minute=3)
    mine = {"X-Forwarded-For": "10.0.0.1"}

    codes = [client.get(f"{API}/documents", params={"q": f"q{n}"}, headers=mine).status_code for n in range(5)]
    limited = client.get(f"{API}/documents", headers=mine)

    assert codes == [200, 200, 200, 429, 429]
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.json()["detail"]
    assert client.get(f"{API}/documents", headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200


def test_cached_answers_count_towards_the_limit(new_client, meili):
    client = new_client(rate_limit_per_minute=2)

    codes = [client.get(f"{API}/documents", params={"q": "same"}).status_code for _ in range(3)]

    assert codes == [200, 200, 429]


def test_the_limit_is_per_client_address_taken_from_the_proxy_and_cannot_be_dodged_by_forging_the_header(new_client, meili):
    client = new_client(rate_limit_per_minute=2)

    codes = [
        client.get(f"{API}/documents", headers={"X-Forwarded-For": f"forged-{n}, 203.0.113.9"}).status_code
        for n in range(3)
    ]

    assert codes == [200, 200, 429]


def test_the_limit_resets_after_its_window(new_client, meili):
    client = new_client(rate_limit_per_minute=1, rate_limit_window_seconds=0.3)
    assert client.get(f"{API}/documents").status_code == 200
    assert client.get(f"{API}/documents").status_code == 429

    time.sleep(0.4)

    assert client.get(f"{API}/documents").status_code == 200


def test_health_checks_are_never_limited_and_readiness_follows_meilisearch(new_client, meili):
    client = new_client(rate_limit_per_minute=1)
    assert [client.get("/healthz").status_code for _ in range(5)] == [200] * 5
    assert client.get("/readyz").status_code == 200

    down = new_client(meili_url="http://127.0.0.1:1")
    assert down.get("/healthz").status_code == 200
    assert down.get("/readyz").status_code == 503
    assert down.get(f"{API}/documents").json() == {"detail": "Search is not available right now"}


def test_the_limiter_forgets_the_oldest_client_when_its_table_is_full_instead_of_growing(new_client, meili):
    client = new_client(rate_limit_per_minute=1, rate_limit_max_clients=3)

    def status(address):
        return client.get(f"{API}/documents", headers={"X-Forwarded-For": address}).status_code

    assert [status(f"10.0.0.{n}") for n in (1, 2, 3)] == [200, 200, 200]
    assert status("10.0.0.3") == 429
    assert status("10.0.0.4") == 200  # a fourth client pushes the oldest, 10.0.0.1, out of the table
    assert status("10.0.0.3") == 429  # the others are still counted
    assert status("10.0.0.1") == 200  # the forgotten one starts afresh


def test_the_cache_is_bounded_by_size_and_a_body_larger_than_the_budget_is_not_kept(new_client, meili):
    probe = new_client()
    size = len(probe.get(f"{API}/documents", params={"q": "q1"}).content)

    tiny = new_client(cache_max_bytes=size - 1)
    assert [tiny.get(f"{API}/documents", params={"q": "q1"}).headers["X-Cache"] for _ in range(2)] == ["MISS", "MISS"]

    two = new_client(cache_max_bytes=size * 2 + size // 2)
    for query in ("q1", "q2", "q3"):
        two.get(f"{API}/documents", params={"q": query})
    assert two.get(f"{API}/documents", params={"q": "q3"}).headers["X-Cache"] == "HIT"
    assert two.get(f"{API}/documents", params={"q": "q1"}).headers["X-Cache"] == "MISS"  # evicted to stay in budget
