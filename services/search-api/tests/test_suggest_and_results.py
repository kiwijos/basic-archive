from conftest import document, subject

API = "/api/search"


def test_suggestions_complete_a_name_as_it_is_typed_including_old_names(client, meili):
    ship = subject(names=[("Vega", False), ("Nordstjernan", True)])
    meili.add("subjects", ship, subject("Freja"))
    meili.add("documents", document(title="Nordisk karta", text="x"))

    current = client.get(f"{API}/suggest", params={"q": "Nord"}).json()["suggestions"]
    assert {"type": "ship", "id": ship["id"], "text": "Nordstjernan", "matched_name": "Nordstjernan"} in current
    assert any(s["type"] == "document" and s["text"] == "Nordisk karta" for s in current)

    old = client.get(f"{API}/suggest", params={"q": "Veg"}).json()["suggestions"]
    assert [(s["text"], s["matched_name"]) for s in old] == [("Nordstjernan", "Vega")]


def test_suggestions_are_few_and_an_empty_query_has_none(client, meili):
    meili.add("subjects", *[subject(f"Skepp {n}") for n in range(30)])

    assert len(client.get(f"{API}/suggest", params={"q": "Skepp"}).json()["suggestions"]) <= 8
    assert client.get(f"{API}/suggest", params={"q": ""}).json() == {"suggestions": []}


def test_a_hit_highlights_its_matches_as_parts_and_never_returns_markup_or_the_whole_text(client, meili):
    long_text = "inledning " * 200 + "Vega lämnade Göteborg " + "avslutning " * 200
    meili.add("documents", document(title="Skeppet Vega", text=long_text))

    [hit] = client.get(f"{API}/documents", params={"q": "Vega"}).json()["hits"]

    assert {"text": "Vega", "match": True} in hit["highlights"]["title"]
    snippet = "".join(part["text"] for part in hit["highlights"]["text"])
    assert "Vega" in snippet and len(snippet) < 400
    assert any(part["match"] and part["text"] == "Vega" for part in hit["highlights"]["text"])
    assert "text" not in hit
    assert "\ue000" not in str(hit) and "<em>" not in str(hit)


def test_archive_text_that_looks_like_html_comes_back_as_plain_text(client, meili):
    meili.add("documents", document(title="<script>alert(1)</script> Vega", text="x"))

    [hit] = client.get(f"{API}/documents", params={"q": "Vega"}).json()["hits"]

    assert "".join(p["text"] for p in hit["highlights"]["title"]) == "<script>alert(1)</script> Vega"


def test_a_hit_links_to_the_iiif_images_of_its_pages(new_client, meili):
    client = new_client(iiif_base_url="https://archive.example/iiif/3")
    first, second = document()["images"][0]["id"], "5b1d0f0e-0000-4000-8000-000000000002"
    meili.add("documents", document(text="Vega", images=[{"id": first, "page_no": 1}, {"id": second, "page_no": 2}]))

    [hit] = client.get(f"{API}/documents", params={"q": "Vega"}).json()["hits"]

    assert [(page["page_no"], page["iiif_info"]) for page in hit["pages"]] == [
        (1, f"https://archive.example/iiif/3/{first}/info.json"),
        (2, f"https://archive.example/iiif/3/{second}/info.json"),
    ]
    assert hit["thumbnail"] == f"https://archive.example/iiif/3/{first}/full/!400,400/0/default.jpg"


def test_a_document_with_no_images_has_no_thumbnail(client, meili):
    meili.add("documents", document(text="Vega", images=[], image_count=0))

    [hit] = client.get(f"{API}/documents", params={"q": "Vega"}).json()["hits"]

    assert (hit["thumbnail"], hit["pages"]) == (None, [])
