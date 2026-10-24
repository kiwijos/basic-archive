import pytest
from support import API, upload
from test_verified import correct, read_by_machine

INDEXER = {"Authorization": "Bearer indexer-token"}
WORKER = {"Authorization": "Bearer worker-token"}


def document_view(client, document_id, headers=INDEXER):
    return client.get(f"{API}/index/document/{document_id}", headers=headers)


def test_only_the_indexer_may_read_the_indexing_view(client, staff):
    document = upload(client, staff).json()["id"]

    assert document_view(client, document, headers={}).status_code == 401
    assert document_view(client, document, headers=staff).status_code == 401
    assert document_view(client, document, headers=WORKER).status_code == 403
    assert document_view(client, document).status_code == 200


def test_a_documents_text_is_its_images_current_text_in_page_order_and_it_is_verified_only_when_all_are(
    client, staff
):
    from test_pages import JPEG, add_page

    document = upload(client, staff, title="Brev från varvet").json()
    first = document["images"][0]["id"]
    second = add_page(client, staff, document["id"], JPEG).json()["images"][1]["id"]
    read_by_machine(client, first, "maskinläst ett")
    read_by_machine(client, second, "maskinläst två")

    unchecked = document_view(client, document["id"]).json()
    assert unchecked["text"] == "maskinläst ett\n\nmaskinläst två"
    assert (unchecked["verified"], unchecked["verified_images"], unchecked["image_count"]) == (False, 0, 2)

    correct(client, staff, first, "rättat ett")
    half = document_view(client, document["id"]).json()
    assert half["text"] == "rättat ett\n\nmaskinläst två"
    assert half["verified"] is False

    correct(client, staff, second, "rättat två")
    whole = document_view(client, document["id"]).json()
    assert whole["text"] == "rättat ett\n\nrättat två"
    assert whole["verified"] is True
    assert whole["title"] == "Brev från varvet"
    assert [image["page_no"] for image in whole["images"]] == [1, 2]
    assert whole["images"][0]["id"] == first


def test_an_unknown_document_has_no_view(client):
    assert document_view(client, "7d444840-9dc0-11d1-b245-5ffdce74fad2").status_code == 404


def subject_view(client, kind, subject_id, headers=INDEXER):
    return client.get(f"{API}/index/{kind}/{subject_id}", headers=headers)


@pytest.fixture
def yard(client, staff):
    """A ship Vega, renamed Nordstjernan, built by Götaverken in Göteborg in 1889-1890."""

    def post(path, body):
        response = client.post(f"{API}{path}", json=body, headers=staff)
        assert response.status_code == 201, response.text
        return response.json()

    ship = post("/ships", {"name": "Vega", "ship_type": "barque", "launched": {"date_text": "1890"}})
    organisation = post("/organisations", {"name": "Götaverken", "place": "Göteborg"})
    post(f"/subjects/{ship['id']}/names", {"name": "Nordstjernan", "date": {"date_from": "1900-01-01"}})
    post(
        "/relations",
        {
            "from_subject_id": ship["id"],
            "predicate": "built_by",
            "to_subject_id": organisation["id"],
            "date": {"date_text": "1889-90", "date_from": "1889-06-01", "date_to": "1890-03-01"},
        },
    )
    return {"ship": ship["id"], "organisation": organisation["id"]}


def test_a_ships_view_holds_all_its_names_and_the_facts_derived_from_its_relations(client, yard):
    view = subject_view(client, "ship", yard["ship"]).json()

    assert view["entity"] == "ship"
    assert view["name"] == "Nordstjernan"
    assert sorted(name["name"] for name in view["names"]) == ["Nordstjernan", "Vega"]
    assert view["ship_type"] == "barque"
    assert view["builders"] == ["Götaverken"]
    assert view["places"] == ["Göteborg"]
    assert (view["year_from"], view["year_to"]) == (1889, 1890)


def test_a_ship_without_a_dated_builder_relation_falls_back_to_its_launch_year(client, staff):
    ship = client.post(
        f"{API}/ships",
        json={"name": "Freja", "launched": {"date_from": "1875-01-01", "date_to": "1875-12-31"}},
        headers=staff,
    ).json()["id"]

    view = subject_view(client, "ship", ship).json()

    assert (view["year_from"], view["year_to"]) == (1875, 1875)
    assert view["builders"] == []


def test_an_organisations_view_holds_its_names_type_and_place(client, yard):
    view = subject_view(client, "organisation", yard["organisation"]).json()

    assert view["entity"] == "organisation"
    assert view["name"] == "Götaverken"
    assert view["places"] == ["Göteborg"]


def test_a_deleted_or_mistyped_subject_has_no_view(client, staff, yard):
    assert subject_view(client, "organisation", yard["ship"]).status_code == 404
    client.delete(f"{API}/ships/{yard['ship']}", headers=staff)
    assert subject_view(client, "ship", yard["ship"]).status_code == 404


def link(client, staff, document, subject):
    response = client.put(f"{API}/documents/{document}/subjects/{subject}", json={"role": "depicted"}, headers=staff)
    assert response.status_code == 200, response.text


def test_a_documents_view_carries_its_own_facts_and_the_facts_of_the_ships_it_is_linked_to(
    client, staff, yard
):
    document = upload(
        client,
        staff,
        title="Ritning",
        document_type="blueprint",
        date_text="ca 1889",
        date_from="1889-01-01",
        date_to="1889-12-31",
        physical_location="Sjöhistoriska",
    ).json()["id"]
    link(client, staff, document, yard["ship"])

    view = document_view(client, document).json()

    assert view["document_type"] == "blueprint"
    assert view["date_text"] == "ca 1889"
    assert (view["year_from"], view["year_to"]) == (1889, 1889)
    assert view["physical_location"] == "Sjöhistoriska"
    assert sorted(view["ship_names"]) == ["Nordstjernan", "Vega"]
    assert view["ship_types"] == ["barque"]
    assert view["builders"] == ["Götaverken"]
    assert view["places"] == ["Göteborg"]


def test_a_document_linked_to_no_ship_has_empty_ship_facts(client, staff):
    document = upload(client, staff).json()["id"]

    view = document_view(client, document).json()

    assert (view["ship_names"], view["ship_types"], view["builders"], view["places"]) == ([], [], [], [])
    assert (view["year_from"], view["year_to"]) == (None, None)


def test_changing_a_ship_or_its_builder_announces_the_documents_that_show_their_facts(
    client, staff, yard, outbox
):
    document = upload(client, staff).json()["id"]
    link(client, staff, document, yard["ship"])
    before = len(outbox())

    client.post(f"{API}/subjects/{yard['ship']}/names", json={"name": "Freja", "date": {"date_from": "1920-01-01"}}, headers=staff)
    renamed = outbox()[before:]
    assert ("document", document, "upsert") in renamed

    before = len(outbox())
    client.put(f"{API}/organisations/{yard['organisation']}", json={"place": "Lindholmen"}, headers=staff)
    rebuilt = outbox()[before:]
    assert ("ship", yard["ship"], "upsert") in rebuilt
    assert ("document", document, "upsert") in rebuilt

    before = len(outbox())
    client.delete(f"{API}/ships/{yard['ship']}", headers=staff)
    assert ("document", document, "upsert") in outbox()[before:]


def list_view(client, kind, headers=INDEXER, **params):
    response = client.get(f"{API}/index/{kind}", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_listing_pages_through_every_live_record_for_a_reindex(client, staff):
    ids = [upload(client, staff, title=f"Brev {n}").json()["id"] for n in range(5)]
    gone = client.post(f"{API}/ships", json={"name": "Borta"}, headers=staff).json()["id"]
    client.delete(f"{API}/ships/{gone}", headers=staff)

    seen, after = [], None
    while True:
        page = list_view(client, "document", limit=2, **({"after": after} if after else {}))
        assert len(page["items"]) <= 2
        seen += [item["id"] for item in page["items"]]
        after = page["next_after"]
        if after is None:
            break

    assert sorted(seen) == sorted(ids)
    assert list_view(client, "ship") == {"items": [], "next_after": None}


def test_the_listing_caps_its_page_size_and_is_for_the_indexer_only(client, staff):
    assert client.get(f"{API}/index/document", params={"limit": 101}, headers=INDEXER).status_code == 422
    assert client.get(f"{API}/index/document", headers=staff).status_code == 401
    assert client.get(f"{API}/index/document", headers=WORKER).status_code == 403


def test_every_view_follows_the_indexing_contract(client, staff, yard):
    from catalog_api.contracts import validate

    document = upload(client, staff, date_from="1889-01-01").json()["id"]
    link(client, staff, document, yard["ship"])

    for view in (
        document_view(client, document).json(),
        subject_view(client, "ship", yard["ship"]).json(),
        subject_view(client, "organisation", yard["organisation"]).json(),
        *list_view(client, "ship")["items"],
    ):
        validate("index.view", view)


def test_a_ship_renamed_back_to_an_earlier_name_has_exactly_one_current_name(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Vega", "launched": None}, headers=staff).json()["id"]
    client.post(f"{API}/subjects/{ship}/names", json={"name": "Nordstjernan", "date": {"date_from": "1900-01-01", "date_to": "1910-01-01"}}, headers=staff)
    back = client.post(f"{API}/subjects/{ship}/names", json={"name": "Vega", "date": {"date_from": "1910-01-02"}}, headers=staff)
    assert back.status_code == 201, back.text

    view = subject_view(client, "ship", ship).json()

    assert [(n["name"], n["current"]) for n in view["names"] if n["current"]] == [("Vega", True)]
    assert sum(n["current"] for n in view["names"]) == 1


def test_a_document_stops_showing_the_facts_of_a_ship_that_was_deleted(client, staff, yard):
    document = upload(client, staff).json()["id"]
    link(client, staff, document, yard["ship"])
    assert document_view(client, document).json()["ship_names"]

    client.delete(f"{API}/ships/{yard['ship']}", headers=staff)

    view = document_view(client, document).json()
    assert (view["ship_names"], view["ship_types"], view["builders"], view["places"]) == ([], [], [], [])


def test_a_ship_with_only_a_written_date_has_no_years(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Freja", "launched": {"date_text": "omkring förra seklet"}}, headers=staff).json()["id"]

    view = subject_view(client, "ship", ship).json()

    assert (view["year_from"], view["year_to"]) == (None, None)


def test_a_documents_view_carries_what_its_landing_page_shows_for_each_image(client, staff):
    from test_pages import JPEG, add_page

    document = upload(client, staff, title="Kontrakt", rights="CC BY").json()
    first = document["images"][0]["id"]
    second = add_page(client, staff, document["id"], JPEG, rights="reserved").json()["images"][1]["id"]
    read_by_machine(client, first, "maskinläst ett")
    correct(client, staff, second, "rättat två")

    images = document_view(client, document["id"]).json()["images"]

    assert [(i["page_no"], i["rights"], i["verified"], i["text_source"], i["text"]) for i in images] == [
        (1, "CC BY", False, "machine", "maskinläst ett"),
        (2, "reserved", True, "human", "rättat två"),
    ]
    assert images[0]["id"] == first and images[1]["mime"] == "image/jpeg"


def test_a_documents_view_lists_the_live_subjects_it_is_linked_to(client, staff, yard):
    document = upload(client, staff).json()["id"]
    link(client, staff, document, yard["ship"])
    link(client, staff, document, yard["organisation"])

    subjects = document_view(client, document).json()["subjects"]

    assert sorted((s["kind"], s["name"], s["id"]) for s in subjects) == sorted(
        [("ship", "Nordstjernan", yard["ship"]), ("organisation", "Götaverken", yard["organisation"])]
    )
    client.delete(f"{API}/ships/{yard['ship']}", headers=staff)
    assert [s["kind"] for s in document_view(client, document).json()["subjects"]] == ["organisation"]


def test_a_ships_view_carries_its_facts_relations_in_both_directions_and_its_documents(client, staff, yard):
    old_hull = client.post(f"{API}/ships", json={"name": "Skrovet"}, headers=staff).json()["id"]
    client.post(f"{API}/relations", json={"from_subject_id": yard["ship"], "predicate": "rebuilt_from", "to_subject_id": old_hull, "date": {"date_text": "1899"}}, headers=staff)
    client.put(f"{API}/ships/{yard['ship']}", json={"ship_type": "barque", "tonnage": 1200, "fate": "wrecked", "fate_date": {"date_text": "1923"}, "launched": {"date_text": "1890"}}, headers=staff)
    document = upload(client, staff, title="Ritning").json()
    correct(client, staff, document["images"][0]["id"], "text")
    link(client, staff, document["id"], yard["ship"])

    view = subject_view(client, "ship", yard["ship"]).json()
    old = subject_view(client, "ship", old_hull).json()

    relations = {(r["predicate"], r["direction"], r["other_name"], r["other_kind"]) for r in view["relations"]}
    assert relations == {("built_by", "from", "Götaverken", "organisation"), ("rebuilt_from", "from", "Skrovet", "ship")}
    assert [(r["predicate"], r["direction"], r["other_name"]) for r in old["relations"]] == [("rebuilt_from", "to", "Nordstjernan")]
    rebuilt = next(r for r in view["relations"] if r["predicate"] == "rebuilt_from")
    assert (rebuilt["other_id"], rebuilt["date_text"]) == (old_hull, "1899")
    assert (view["tonnage"], view["fate"], view["fate_date"]["date_text"], view["launched"]["date_text"]) == (1200, "wrecked", "1923", "1890")
    assert view["documents"] == [{"id": document["id"], "title": "Ritning", "document_type": None, "verified": True}]
    assert subject_view(client, "organisation", yard["organisation"]).json()["relations"][0]["direction"] == "to"


def test_a_deleted_subject_leaves_the_relations_and_documents_of_the_others(client, staff, yard):
    document = upload(client, staff).json()["id"]
    link(client, staff, document, yard["ship"])
    client.delete(f"{API}/organisations/{yard['organisation']}", headers=staff)

    view = subject_view(client, "ship", yard["ship"]).json()

    assert view["relations"] == []
    assert [d["id"] for d in view["documents"]] == [document]


def test_what_a_landing_page_shows_is_announced_again_when_it_changes(client, staff, yard, outbox):
    other = client.post(f"{API}/ships", json={"name": "Skrovet"}, headers=staff).json()["id"]
    client.post(f"{API}/relations", json={"from_subject_id": yard["ship"], "predicate": "rebuilt_from", "to_subject_id": other}, headers=staff)
    document = upload(client, staff).json()
    link(client, staff, document["id"], yard["ship"])

    before = len(outbox())
    client.post(f"{API}/subjects/{yard['ship']}/names", json={"name": "Freja", "date": {"date_from": "1930-01-01"}}, headers=staff)
    assert ("ship", other, "upsert") in outbox()[before:]  # it names this ship in its relations

    before = len(outbox())
    correct(client, staff, document["images"][0]["id"], "text")
    assert ("ship", yard["ship"], "upsert") in outbox()[before:]  # it lists the Document and whether it is verified


def count_queries(client, path):
    """How many SQL statements serving this request takes."""
    from sqlalchemy import event

    engine = client.app.state.engine
    statements = []
    listener = lambda *args, **kwargs: statements.append(1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert client.get(f"{API}{path}", headers=INDEXER).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    return len(statements)


def many_documents_about(client, staff, ship, count):
    ids = []
    for n in range(count):
        document = upload(client, staff, title=f"Brev {n}").json()
        link(client, staff, document["id"], ship)
        ids.append(document["id"])
    return ids


def test_building_a_view_does_not_cost_more_for_each_document_a_ship_has(client, staff, yard):
    few = many_documents_about(client, staff, yard["ship"], 2)
    document_few = count_queries(client, f"/index/document/{few[0]}")
    ship_few = count_queries(client, f"/index/ship/{yard['ship']}")

    many_documents_about(client, staff, yard["ship"], 8)

    assert count_queries(client, f"/index/document/{few[0]}") == document_few
    assert count_queries(client, f"/index/ship/{yard['ship']}") == ship_few


def test_building_a_ships_view_does_not_cost_more_for_each_relation_it_has(client, staff, yard):
    before = count_queries(client, f"/index/ship/{yard['ship']}")
    for n in range(6):
        other = client.post(f"{API}/ships", json={"name": f"Syster {n}"}, headers=staff).json()["id"]
        client.post(f"{API}/relations", json={"from_subject_id": other, "predicate": "rebuilt_from", "to_subject_id": yard["ship"]}, headers=staff)

    assert count_queries(client, f"/index/ship/{yard['ship']}") == before


def test_a_ships_view_carries_its_chosen_wikidata_matches_and_follows_the_contract(client, staff, yard, wikidata, outbox):
    from catalog_api.contracts import validate

    wikidata.add("Q219821", en=("Vasa", "17th century Swedish warship"))
    assert subject_view(client, "ship", yard["ship"]).json()["external_refs"] == []

    assert client.put(f"{API}/ships/{yard['ship']}/wikidata/Q219821", headers=staff).status_code == 200
    view = subject_view(client, "ship", yard["ship"]).json()

    [reference] = view["external_refs"]
    assert (reference["source"], reference["id"], reference["label"]) == ("wikidata", "Q219821", "Vasa")
    assert reference["url"] == "https://www.wikidata.org/wiki/Q219821"
    assert reference["retrieved_at"]
    assert "chosen_by" not in reference  # who chose is for staff, not for the index
    validate("index.view", view)
    assert subject_view(client, "organisation", yard["organisation"]).json()["external_refs"] == []

    client.delete(f"{API}/ships/{yard['ship']}/wikidata/Q219821", headers=staff)
    assert subject_view(client, "ship", yard["ship"]).json()["external_refs"] == []
