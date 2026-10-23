from conftest import subject

API = "/api/search"


def names(response) -> list[str]:
    return [hit["name"] for hit in response.json()["hits"]]


def test_a_misspelled_ship_name_still_finds_the_ship(client, meili):
    meili.add("subjects", subject("Nordstjernan"), subject("Freja"))

    assert names(client.get(f"{API}/subjects", params={"q": "Nordstjrnan"})) == ["Nordstjernan"]
    assert names(client.get(f"{API}/subjects", params={"q": "Frejja"})) == ["Freja"]


def test_a_search_by_an_old_name_finds_the_ship_and_says_which_name_matched(client, meili):
    ship = subject(names=[("Vega", False), ("Nordstjernan", True)])
    meili.add("subjects", ship, subject("Freja"))

    [hit] = client.get(f"{API}/subjects", params={"q": "Vega"}).json()["hits"]

    assert hit["id"] == ship["id"]
    assert hit["name"] == "Nordstjernan"
    assert hit["matched_name"] == "Vega"
    assert hit["highlights"]["names"] == [{"text": "Vega", "match": True}]


def test_a_search_by_the_current_name_reports_that_name_and_a_search_on_something_else_reports_none(client, meili):
    ship = subject(names=[("Vega", False), ("Nordstjernan", True)], builders=["Götaverken"])
    meili.add("subjects", ship)

    [by_name] = client.get(f"{API}/subjects", params={"q": "Nordstjernan"}).json()["hits"]
    [by_builder] = client.get(f"{API}/subjects", params={"q": "Götaverken"}).json()["hits"]

    assert by_name["matched_name"] == "Nordstjernan"
    assert by_builder["matched_name"] is None


def test_every_name_a_ship_carried_is_listed_with_its_dates_in_the_result(client, meili):
    ship = subject(names=[("Vega", False), ("Nordstjernan", True)])
    ship["name_details"][0].update(date_text="1889-1899")
    meili.add("subjects", ship)

    [hit] = client.get(f"{API}/subjects", params={"q": "Nordstjernan"}).json()["hits"]

    assert [(n["name"], n["date_text"], n["current"]) for n in hit["names"]] == [
        ("Vega", "1889-1899", False),
        ("Nordstjernan", None, True),
    ]
    assert (hit["entity"], hit["ship_type"]) == ("ship", "barque")
