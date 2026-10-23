import pytest
from conftest import document, subject

API = "/api/search"


@pytest.fixture
def archive(meili):
    docs = {
        "barque": document(title="Barkens ritning", text="rigg", ship_types=["barque"], builders=["Götaverken"], places=["Göteborg"], year_from=1889, year_to=1890),
        "steamer": document(title="Ångarens brev", text="rigg", ship_types=["steamer"], builders=["Motala Verkstad"], places=["Norrköping"], year_from=1905, year_to=1906),
        "undated": document(title="Odaterat", text="rigg"),
    }
    meili.add("documents", *docs.values())
    ships = {
        "vega": subject("Vega", ship_type="barque", builders=["Götaverken"], places=["Göteborg"], year_from=1889, year_to=1890),
        "freja": subject("Freja", ship_type="steamer", builders=["Motala Verkstad"], places=["Norrköping"], year_from=1905, year_to=1905),
        "yard": subject("Götaverken", entity="organisation", ship_type=None, organisation_type="yard", places=["Göteborg"]),
    }
    meili.add("subjects", *ships.values())
    return docs, ships


def titles(client, **params):
    return sorted(hit["title"] for hit in client.get(f"{API}/documents", params=params).json()["hits"])


def subject_names(client, **params):
    return sorted(hit["name"] for hit in client.get(f"{API}/subjects", params=params).json()["hits"])


def test_documents_filter_by_ship_type_builder_and_place(client, archive):
    assert titles(client, ship_type="barque") == ["Barkens ritning"]
    assert titles(client, builder="Motala Verkstad") == ["Ångarens brev"]
    assert titles(client, place="Göteborg") == ["Barkens ritning"]
    assert titles(client, ship_type="barque", place="Norrköping") == []


def test_several_values_for_one_filter_match_any_of_them_and_different_filters_must_all_match(client, archive):
    assert titles(client, ship_type=["barque", "steamer"]) == ["Barkens ritning", "Ångarens brev"]
    assert titles(client, ship_type=["barque", "steamer"], place="Göteborg") == ["Barkens ritning"]


def test_the_year_range_keeps_documents_whose_dates_overlap_it(client, archive):
    assert titles(client, year_from=1880, year_to=1895) == ["Barkens ritning"]
    assert titles(client, year_from=1890, year_to=1905) == ["Barkens ritning", "Ångarens brev"]
    assert titles(client, year_from=1900) == ["Ångarens brev"]
    assert titles(client, year_to=1889) == ["Barkens ritning"]
    assert titles(client, year_from=1950, year_to=1960) == []


def test_subjects_filter_by_kind_type_builder_place_and_year(client, archive):
    assert subject_names(client, kind="organisation") == ["Götaverken"]
    assert subject_names(client, ship_type="steamer") == ["Freja"]
    assert subject_names(client, builder="Götaverken") == ["Vega"]
    assert subject_names(client, place="Göteborg") == ["Götaverken", "Vega"]
    assert subject_names(client, year_from=1900, year_to=1910) == ["Freja"]


def test_a_filter_value_is_data_and_cannot_change_the_filter(client, archive):
    trick = 'x" OR verified = false OR builders = "y'

    assert titles(client, builder=trick) == []
    assert subject_names(client, place='"] OR entity = "ship') == []


def test_nonsense_filters_are_refused_not_crashed_on(client, archive):
    assert client.get(f"{API}/documents", params={"year_from": "abc"}).status_code == 422
    assert client.get(f"{API}/documents", params={"year_from": 0}).status_code == 422
    assert client.get(f"{API}/documents", params={"year_from": 1900, "year_to": 1800}).status_code == 422
    assert client.get(f"{API}/subjects", params={"kind": "boat"}).status_code == 422
    assert client.get(f"{API}/documents", params={"q": "x" * 201}).status_code == 422


def test_facets_count_the_matching_documents_and_subjects(client, archive):
    found = client.get(f"{API}/documents").json()
    assert found["facets"]["ship_types"] == {"barque": 1, "steamer": 1}
    assert found["facets"]["builders"] == {"Götaverken": 1, "Motala Verkstad": 1}
    assert found["facets"]["verified"] == {"false": 3}

    narrowed = client.get(f"{API}/documents", params={"place": "Göteborg"}).json()
    assert narrowed["facets"]["ship_types"] == {"barque": 1}

    ships = client.get(f"{API}/subjects").json()
    assert ships["facets"]["entity"] == {"ship": 2, "organisation": 1}


def test_the_facets_endpoint_gives_the_distributions_without_the_hits(client, archive):
    answer = client.get(f"{API}/facets", params={"scope": "documents", "ship_type": "barque"}).json()

    assert answer["facets"]["places"] == {"Göteborg": 1}
    assert "hits" not in answer
    assert client.get(f"{API}/facets", params={"scope": "nonsense"}).status_code == 422
