from conftest import document, new_id, subject

API = "/api/search"


def relation(predicate, direction, other, **extra):
    return {"predicate": predicate, "direction": direction, "other_id": other["id"], "other_kind": other["entity"],
            "other_name": other["name"], "place": None, "date_text": None, "date_from": None, "date_to": None, "source": None, **extra}


def test_a_document_has_a_landing_record_with_its_rights_text_verified_state_and_subjects(new_client, meili):
    client = new_client(iiif_base_url="/iiif/3")
    ship = subject("Nordstjernan")
    page_one, page_two = new_id(), new_id()
    record = document(
        title="Kontrakt", document_type="contract", description="Köpebrev", physical_location="Arkivet", date_text="ca 1890",
        year_from=1889, year_to=1891, verified=False, verified_images=1, image_count=2,
        images=[
            {"id": page_one, "page_no": 1, "mime": "image/png", "rights": "CC BY", "verified": True, "text_source": "human", "text": "Rättad text"},
            {"id": page_two, "page_no": 2, "mime": "image/jpeg", "rights": "reserved", "verified": False, "text_source": "machine", "text": "Maskinläst text"},
        ],
        subjects=[{"id": ship["id"], "kind": "ship", "name": "Nordstjernan", "role": "depicted"}],
    )
    meili.add("documents", record, document(title="Annat"))

    page = client.get(f"{API}/documents/{record['id']}").json()

    assert (page["title"], page["document_type"], page["description"], page["physical_location"], page["date_text"]) == ("Kontrakt", "contract", "Köpebrev", "Arkivet", "ca 1890")
    assert (page["verified"], page["verified_images"], page["image_count"]) == (False, 1, 2)
    assert [(i["page_no"], i["rights"], i["verified"], i["text_source"], i["text"]) for i in page["images"]] == [
        (1, "CC BY", True, "human", "Rättad text"),
        (2, "reserved", False, "machine", "Maskinläst text"),
    ]
    assert page["images"][0]["iiif_info"] == f"/iiif/3/{page_one}/info.json"
    assert page["subjects"] == [{"id": ship["id"], "kind": "ship", "name": "Nordstjernan", "role": "depicted"}]


def test_a_ship_has_a_landing_record_with_names_over_time_relations_and_documents(client, meili):
    skrovet = subject("Skrovet")
    yard = subject("Götaverken", entity="organisation", ship_type=None)
    ship = subject(names=[("Vega", False), ("Nordstjernan", True)], tonnage=1200.5, fate="wrecked",
                   launched={"date_text": "1890", "date_from": None, "date_to": None}, fate_date={"date_text": "1923", "date_from": None, "date_to": None})
    ship["name_details"][0].update(date_text="1889-1899", date_from="1889-01-01", date_to="1899-12-31")
    ship["relations"] = [relation("rebuilt_from", "from", skrovet, date_text="1899"), relation("built_by", "from", yard, place="Göteborg")]
    ship["documents"] = [{"id": new_id(), "title": "Ritning", "document_type": "blueprint", "verified": True}]
    meili.add("subjects", ship, skrovet, yard)

    page = client.get(f"{API}/subjects/{ship['id']}").json()

    assert (page["entity"], page["name"], page["ship_type"], page["tonnage"], page["fate"]) == ("ship", "Nordstjernan", "barque", 1200.5, "wrecked")
    assert [(n["name"], n["date_text"], n["current"]) for n in page["names"]] == [("Vega", "1889-1899", False), ("Nordstjernan", None, True)]
    assert [(r["predicate"], r["direction"], r["other_name"], r["other_id"]) for r in page["relations"]] == [
        ("rebuilt_from", "from", "Skrovet", skrovet["id"]),
        ("built_by", "from", "Götaverken", yard["id"]),
    ]
    assert page["documents"] == ship["documents"]
    assert page["launched"]["date_text"] == "1890" and page["fate_date"]["date_text"] == "1923"


def test_an_unknown_record_has_no_landing_page_and_a_filter_cannot_be_smuggled_in_the_id(client, meili):
    meili.add("documents", document())
    meili.add("subjects", subject())

    assert client.get(f"{API}/documents/{new_id()}").status_code == 404
    assert client.get(f"{API}/subjects/{new_id()}").status_code == 404
    assert client.get(f"{API}/documents/not-an-id").status_code in (404, 422)
    assert client.get(f"{API}/documents/x%22%20OR%20verified%20%3D%20false").status_code in (404, 422)


def test_a_ship_is_not_served_as_a_document_and_the_other_way_round(client, meili):
    ship, doc = subject(), document()
    meili.add("subjects", ship)
    meili.add("documents", doc)

    assert client.get(f"{API}/documents/{ship['id']}").status_code == 404
    assert client.get(f"{API}/subjects/{doc['id']}").status_code == 404


def test_search_results_do_not_carry_the_page_texts_or_relations_of_the_landing_record(client, meili):
    meili.add("documents", document(text="Vega"))
    meili.add("subjects", subject("Vega"))

    [doc] = client.get(f"{API}/documents", params={"q": "Vega"}).json()["hits"]
    [ship] = client.get(f"{API}/subjects", params={"q": "Vega"}).json()["hits"]

    assert "images" not in doc and "relations" not in ship and "documents" not in ship
    assert doc["pages"] and doc["thumbnail"]


def test_a_ships_landing_record_carries_its_wikidata_matches_and_search_results_do_not(client, meili):
    reference = {"source": "wikidata", "id": "Q219821", "label": "Vasa", "description": "warship", "url": "https://www.wikidata.org/wiki/Q219821", "retrieved_at": "2026-10-23T21:00:00+00:00"}
    ship = subject("Vasa", external_refs=[reference])
    meili.add("subjects", ship)

    page = client.get(f"{API}/subjects/{ship['id']}").json()
    [hit] = client.get(f"{API}/subjects", params={"q": "Vasa"}).json()["hits"]

    assert page["external_refs"] == [reference]
    assert "external_refs" not in hit
