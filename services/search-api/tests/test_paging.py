from conftest import document

API = "/api/search"


def test_the_page_size_is_capped_and_pages_do_not_overlap(client, meili):
    meili.add("documents", *[document(title=f"Brev {n:03d}", text="rigg") for n in range(120)])

    huge = client.get(f"{API}/documents", params={"page_size": 5000}).json()
    assert huge["page_size"] == 50
    assert len(huge["hits"]) == 50
    assert (huge["total"], huge["total_pages"], huge["page"]) == (120, 3, 1)

    first = client.get(f"{API}/documents", params={"page_size": 50, "page": 1}).json()
    second = client.get(f"{API}/documents", params={"page_size": 50, "page": 2}).json()
    last = client.get(f"{API}/documents", params={"page_size": 50, "page": 3}).json()
    ids = [hit["id"] for page in (first, second, last) for hit in page["hits"]]
    assert len(ids) == 120 and len(set(ids)) == 120


def test_the_default_page_size_applies_and_bad_paging_is_refused(client, meili):
    meili.add("documents", *[document(text="rigg") for _ in range(30)])

    assert len(client.get(f"{API}/documents").json()["hits"]) == 20
    assert client.get(f"{API}/documents", params={"page": 0}).status_code == 422
    assert client.get(f"{API}/documents", params={"page_size": 0}).status_code == 422
    assert client.get(f"{API}/documents", params={"page": 1001}).status_code == 422
    beyond = client.get(f"{API}/documents", params={"page": 1000})
    assert (beyond.status_code, beyond.json()["hits"]) == (200, [])


def test_equally_relevant_hits_come_back_in_the_same_order_however_the_index_was_filled(client, meili):
    docs = [document(title="Samma brev", text="rigg") for _ in range(8)]

    meili.add("documents", *docs)
    first = [hit["id"] for hit in client.get(f"{API}/documents", params={"q": "rigg", "n": 1}).json()["hits"]]
    meili.http.delete("/indexes/documents/documents")
    meili.add("documents", *reversed(docs))
    second = [hit["id"] for hit in client.get(f"{API}/documents", params={"q": "rigg", "n": 2}).json()["hits"]]

    assert first == second
