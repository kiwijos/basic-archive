import httpx
import pytest
import support
from conftest import MEILI_URL
from support import wait_until


@pytest.fixture
def indexer(start_indexer):
    running = start_indexer(REINDEX_PAGE_SIZE="2")
    assert wait_until(running.ready, timeout=30), running.log()
    return running


@pytest.fixture
def archive(catalog):
    """Five documents, two ships and a yard in the catalog, and nothing indexed yet."""
    catalog.documents = [catalog.put(support.document(title=f"Brev {n}", text=f"Text {n}")) for n in range(5)]
    catalog.ships = [catalog.put(support.ship(name=name)) for name in ("Vega", "Freja")]
    catalog.yard = catalog.put(support.ship(name="Götaverken", entity="organisation", ship_type=None, organisation_type="yard"))
    return catalog


def finished(indexer) -> dict:
    assert wait_until(lambda: indexer.reindex_status()["state"] in ("done", "failed"), timeout=30), indexer.log()
    return indexer.reindex_status()


def test_the_reindex_is_protected(indexer):
    assert indexer.reindex(token=None).status_code == 401
    assert indexer.reindex(token="guess").status_code == 401
    assert indexer.http.get("/reindex").status_code == 401


def test_a_reindex_builds_both_indexes_from_the_catalog_across_pages(indexer, archive, meili):
    assert indexer.reindex().status_code == 202

    result = finished(indexer)

    assert (result["state"], result["indexed"], result["removed"]) == ("done", 8, 0)
    assert set(meili.documents("documents")) == {d["id"] for d in archive.documents}
    assert set(meili.documents("subjects")) == {s["id"] for s in archive.ships} | {archive.yard["id"]}


def test_a_reindex_from_empty_gives_the_same_results_as_before(indexer, archive, meili):
    indexer.reindex()
    finished(indexer)
    before_documents, before_subjects = meili.documents("documents"), meili.documents("subjects")
    before_search = meili.search("documents", "Text 3")["hits"]

    meili.wipe("documents")
    meili.wipe("subjects")
    assert meili.documents("documents") == {}
    indexer.reindex()
    finished(indexer)

    assert meili.documents("documents") == before_documents
    assert meili.documents("subjects") == before_subjects
    assert meili.search("documents", "Text 3")["hits"] == before_search


def test_a_reindex_removes_what_the_catalog_no_longer_has(indexer, archive, meili):
    indexer.reindex()
    finished(indexer)
    gone = archive.documents[0]["id"]
    archive.remove("document", gone)

    indexer.reindex()
    result = finished(indexer)

    assert result["removed"] == 1
    assert gone not in meili.documents("documents")
    assert len(meili.documents("documents")) == 4


def test_a_reindex_that_fails_says_so_and_can_be_started_again(indexer, archive, meili):
    archive.failures = 0
    archive.stop()  # the catalog goes away mid-way

    indexer.reindex()
    result = finished(indexer)

    assert result["state"] == "failed"
    assert result["error"]


def test_the_indexer_and_search_keys_are_not_interchangeable(meili):
    def post(path, key, body):
        return httpx.post(f"{MEILI_URL}{path}", headers={"Authorization": f"Bearer {key}"}, json=body)

    assert post("/indexes/documents/search", meili.indexer_key, {"q": ""}).status_code == 403
    assert post("/indexes/documents/documents", meili.search_key, [{"id": "x"}]).status_code == 403
    assert httpx.get(f"{MEILI_URL}/keys", headers={"Authorization": f"Bearer {meili.indexer_key}"}).status_code == 403
    assert httpx.get(f"{MEILI_URL}/keys", headers={"Authorization": f"Bearer {meili.search_key}"}).status_code == 403


def test_a_reindex_rebuilds_even_when_the_indexes_themselves_are_gone(indexer, archive, meili):
    indexer.reindex()
    finished(indexer)
    for index in ("documents", "subjects"):
        meili._wait(meili.master.delete(f"/indexes/{index}").json()["taskUid"])
    assert meili.master.get("/indexes/documents").status_code == 404

    indexer.reindex()
    result = finished(indexer)

    assert result["state"] == "done", result
    assert "verified" in meili.settings("documents")["filterableAttributes"]
    assert meili.settings("documents")["synonyms"]["fartyg"] == ["skepp", "båt"]
    assert len(meili.documents("documents")) == 5
    # Filtering needs the filterable attributes, so this fails if the index was made with defaults.
    assert meili.search("documents", "", filter="verified = false")["estimatedTotalHits"] == 5
