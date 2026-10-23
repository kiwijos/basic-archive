import json

import pytest
import support
from support import event, wait_until

EXCHANGE = "archive.events"


def publish(broker, body: bytes) -> None:
    broker.basic_publish(EXCHANGE, "record.changed", body, pika_properties())


def pika_properties():
    import pika

    return pika.BasicProperties(content_type="application/json", delivery_mode=2)


@pytest.fixture
def indexer(start_indexer):
    running = start_indexer()
    assert wait_until(running.ready, timeout=30), running.log()
    return running


def test_the_index_settings_are_applied_at_startup(indexer, meili):
    documents = meili.settings("documents")
    assert "verified" in documents["filterableAttributes"]
    assert "ship_names" in documents["searchableAttributes"]
    assert documents["synonyms"]["fartyg"] == ["skepp", "båt"]
    assert "och" in documents["stopWords"]
    assert "name" in meili.settings("subjects")["searchableAttributes"]


def test_a_changed_document_is_fetched_from_the_catalog_and_indexed(indexer, catalog, broker, meili):
    view = catalog.put(support.document(title="Brev från varvet", text="Skeppet Vega lämnade Göteborg"))

    publish(broker, event("document", view["id"]))

    assert wait_until(lambda: view["id"] in meili.documents("documents")), indexer.log()
    indexed = meili.documents("documents")[view["id"]]
    assert indexed["title"] == "Brev från varvet"
    assert indexed["text"] == "Skeppet Vega lämnade Göteborg"
    assert indexed["verified"] is False


def dead_letters(broker) -> int:
    return broker.queue_declare("record.changed.dead", passive=True).method.message_count


def test_a_ship_is_indexed_with_every_name_it_has_carried(indexer, catalog, broker, meili):
    names = [
        {"name": "Vega", "name_type": "given", "date_text": "1889", "date_from": "1889-01-01", "date_to": "1899-12-31", "current": False},
        {"name": "Nordstjernan", "name_type": "given", "date_text": None, "date_from": "1900-01-01", "date_to": None, "current": True},
    ]
    view = catalog.put(support.ship(name="Nordstjernan", names=names, builders=["Götaverken"], places=["Göteborg"], year_from=1889, year_to=1890))

    publish(broker, event("ship", view["id"]))

    assert wait_until(lambda: view["id"] in meili.documents("subjects")), indexer.log()
    indexed = meili.documents("subjects")[view["id"]]
    assert indexed["name"] == "Nordstjernan"
    assert indexed["names"] == ["Vega", "Nordstjernan"]
    assert indexed["name_details"][0]["date_text"] == "1889"
    assert (indexed["builders"], indexed["year_from"], indexed["entity"]) == (["Götaverken"], 1889, "ship")
    assert view["id"] not in meili.documents("documents")


def test_a_delete_event_removes_the_record(indexer, catalog, broker, meili):
    view = catalog.put(support.ship())
    publish(broker, event("ship", view["id"]))
    assert wait_until(lambda: view["id"] in meili.documents("subjects"))

    catalog.remove("ship", view["id"])
    publish(broker, event("ship", view["id"], "delete"))

    assert wait_until(lambda: view["id"] not in meili.documents("subjects")), indexer.log()


def test_an_upsert_for_a_record_the_catalog_no_longer_has_removes_it_too(indexer, catalog, broker, meili):
    view = catalog.put(support.document())
    publish(broker, event("document", view["id"]))
    assert wait_until(lambda: view["id"] in meili.documents("documents"))

    catalog.remove("document", view["id"])
    publish(broker, event("document", view["id"]))

    assert wait_until(lambda: view["id"] not in meili.documents("documents")), indexer.log()


def test_processing_the_same_event_twice_leaves_the_index_unchanged(indexer, catalog, broker, meili):
    view = catalog.put(support.document(text="Vega"))
    other = catalog.put(support.document(text="Freja"))
    publish(broker, event("document", view["id"]))
    publish(broker, event("document", other["id"]))
    assert wait_until(lambda: len(meili.documents("documents")) == 2)
    once = meili.documents("documents")

    for _ in range(3):
        publish(broker, event("document", view["id"]))
    marker = catalog.put(support.document(text="Sist"))
    publish(broker, event("document", marker["id"]))
    assert wait_until(lambda: marker["id"] in meili.documents("documents"))

    after = meili.documents("documents")
    assert {i: after[i] for i in once} == once
    assert len(after) == 3


def test_a_catalog_that_fails_briefly_does_not_lose_the_change(indexer, catalog, broker, meili):
    view = catalog.put(support.document())
    catalog.failures = 2

    publish(broker, event("document", view["id"]))

    assert wait_until(lambda: view["id"] in meili.documents("documents")), indexer.log()
    assert dead_letters(broker) == 0


def test_a_change_that_keeps_failing_is_dead_lettered_and_the_next_one_still_works(
    start_indexer, catalog, broker, meili
):
    indexer = start_indexer(MAX_ATTEMPTS="3")
    assert wait_until(indexer.ready, timeout=30)
    broken = catalog.put(support.document())
    catalog.failures = 100

    publish(broker, event("document", broken["id"]))
    assert wait_until(lambda: dead_letters(broker) == 1), indexer.log()

    catalog.failures = 0
    fine = catalog.put(support.document())
    publish(broker, event("document", fine["id"]))
    assert wait_until(lambda: fine["id"] in meili.documents("documents")), indexer.log()
    assert broken["id"] not in meili.documents("documents")


def test_a_message_that_breaks_the_contract_is_dead_lettered(indexer, broker):
    publish(broker, json.dumps({"entity": "boat", "id": "nope", "op": "upsert"}).encode())
    publish(broker, b"not json at all")

    assert wait_until(lambda: dead_letters(broker) == 2), indexer.log()
    assert indexer.alive()


def test_the_indexer_waits_for_meilisearch_to_be_ready_instead_of_crashing(start_indexer, catalog, broker, meili):
    indexer = start_indexer(MEILI_URL="http://127.0.0.1:1")

    assert not wait_until(indexer.ready, timeout=4)
    assert indexer.alive()
    assert indexer.http.get("/healthz").status_code == 200
    assert indexer.http.get("/readyz").status_code == 503


def test_what_a_landing_page_shows_is_stored_with_the_record(indexer, catalog, broker, meili):
    ship = support.ship(name="Nordstjernan")
    other = support.ship(name="Skrovet")
    relation = {"predicate": "rebuilt_from", "direction": "from", "other_id": other["id"], "other_kind": "ship", "other_name": "Skrovet", "place": None, "date_text": "1899", "date_from": None, "date_to": None, "source": None}
    ship.update(
        relations=[relation],
        documents=[{"id": support.new_id(), "title": "Ritning", "document_type": None, "verified": True}],
        tonnage=1200.5,
        launched={"date_text": "1890", "date_from": None, "date_to": None},
        fate="wrecked",
    )
    ship = catalog.put(ship)
    document = catalog.put(
        support.document(subjects=[{"id": ship["id"], "kind": "ship", "name": "Nordstjernan", "role": "depicted"}])
    )

    publish(broker, event("ship", ship["id"]))
    publish(broker, event("document", document["id"]))

    assert wait_until(lambda: ship["id"] in meili.documents("subjects") and document["id"] in meili.documents("documents")), indexer.log()
    stored = meili.documents("subjects")[ship["id"]]
    assert stored["relations"] == [relation]
    assert stored["documents"] == ship["documents"]
    assert (stored["tonnage"], stored["launched"]["date_text"], stored["fate"]) == (1200.5, "1890", "wrecked")
    page = meili.documents("documents")[document["id"]]
    assert page["subjects"][0]["name"] == "Nordstjernan"
    assert page["images"][0]["rights"] == "reserved" and page["images"][0]["text"]


def test_a_ships_wikidata_matches_are_stored_with_the_record(indexer, catalog, broker, meili):
    reference = {"source": "wikidata", "id": "Q219821", "label": "Vasa", "description": "warship", "url": "https://www.wikidata.org/wiki/Q219821", "retrieved_at": "2026-10-23T21:00:00+00:00"}
    ship = catalog.put(support.ship(name="Vasa", external_refs=[reference]))

    publish(broker, event("ship", ship["id"]))

    assert wait_until(lambda: ship["id"] in meili.documents("subjects")), indexer.log()
    assert meili.documents("subjects")[ship["id"]]["external_refs"] == [reference]
