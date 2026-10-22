import pytest

API = "/api/catalog"


@pytest.fixture
def archive(client, staff):
    """Create Ships and Organisations by name; returns their ids."""

    class Archive:
        def ship(self, name):
            return client.post(f"{API}/ships", json={"name": name}, headers=staff).json()["id"]

        def organisation(self, name):
            return client.post(
                f"{API}/organisations", json={"name": name}, headers=staff
            ).json()["id"]

        def relate(self, from_id, predicate, to_id, **extra):
            return client.post(
                f"{API}/relations",
                json={"from_subject_id": from_id, "predicate": predicate, "to_subject_id": to_id, **extra},
                headers=staff,
            )

        def relations(self, subject_id, **params):
            response = client.get(f"{API}/subjects/{subject_id}/relations", params=params, headers=staff)
            assert response.status_code == 200
            return response.json()

    return Archive()


def test_a_ship_sold_once_has_an_ordered_owner_history(client, staff, archive):
    vega = archive.ship("Vega")
    first_owner = archive.organisation("Rederi A")
    second_owner = archive.organisation("Rederi B")

    first = archive.relate(
        vega, "owned_by", first_owner, date={"date_text": "May 1890", "date_from": "1890-05-01"}
    )
    assert first.status_code == 201
    archive.relate(vega, "owned_by", second_owner, date={"date_from": "1923-04-01"})
    sold = client.put(
        f"{API}/relations/{first.json()['id']}",
        json={"date": {"date_text": "May 1890", "date_from": "1890-05-01", "date_to": "1923-04-01"}},
        headers=staff,
    )
    assert sold.status_code == 200

    owners = archive.relations(vega, predicate="owned_by")
    assert [(r["to_name"], r["date"]["date_from"], r["date"]["date_to"]) for r in owners] == [
        ("Rederi A", "1890-05-01", "1923-04-01"),
        ("Rederi B", "1923-04-01", None),
    ]


def test_a_ship_has_a_builder_with_place_and_source(archive):
    vega = archive.ship("Vega")
    yard = archive.organisation("Götaverken")

    built = archive.relate(
        vega, "built_by", yard, place="Göteborg", source="Skeppsregister 1891", confidence=0.8
    )

    assert built.status_code == 201
    [relation] = archive.relations(vega, predicate="built_by")
    assert relation["from_name"] == "Vega"
    assert relation["to_name"] == "Götaverken"
    assert relation["place"] == "Göteborg"
    assert relation["source"] == "Skeppsregister 1891"
    assert relation["confidence"] == 0.8


def test_a_rebuilt_hull_is_a_new_ship_linked_to_the_old_one(archive):
    old_hull = archive.ship("Gustaf")
    rebuilt = archive.ship("Nordstjernan")

    linked = archive.relate(rebuilt, "rebuilt_from", old_hull, date={"date_text": "1921"})

    assert linked.status_code == 201
    assert rebuilt != old_hull
    from_new = archive.relations(rebuilt)
    from_old = archive.relations(old_hull)
    assert from_new == from_old
    assert (from_new[0]["from_name"], from_new[0]["predicate"], from_new[0]["to_name"]) == (
        "Nordstjernan",
        "rebuilt_from",
        "Gustaf",
    )


@pytest.mark.parametrize(
    ("from_kind", "predicate", "to_kind"),
    [
        ("organisation", "owned_by", "organisation"),
        ("ship", "owned_by", "ship"),
        ("ship", "built_by", "ship"),
        ("ship", "rebuilt_from", "organisation"),
        ("organisation", "rebuilt_from", "ship"),
    ],
)
def test_a_relation_must_connect_the_right_kinds_of_subject(archive, from_kind, predicate, to_kind):
    make = {"ship": archive.ship, "organisation": archive.organisation}

    response = archive.relate(make[from_kind]("A"), predicate, make[to_kind]("B"))

    assert response.status_code == 422


def test_a_subject_cannot_be_related_to_itself(archive):
    vega = archive.ship("Vega")

    assert archive.relate(vega, "rebuilt_from", vega).status_code == 422


def test_a_relation_with_an_inverted_date_range_is_rejected(archive):
    vega = archive.ship("Vega")
    yard = archive.organisation("Götaverken")

    response = archive.relate(
        vega, "owned_by", yard, date={"date_from": "1923-04-01", "date_to": "1890-05-01"}
    )

    assert response.status_code == 422


def test_a_relation_to_an_unknown_subject_is_rejected(archive):
    vega = archive.ship("Vega")

    response = archive.relate(vega, "built_by", "3f2504e0-4f89-41d3-9a0c-0305e82c3301")

    assert response.status_code == 422


def test_confidence_is_between_zero_and_one(archive):
    vega = archive.ship("Vega")
    yard = archive.organisation("Götaverken")

    assert archive.relate(vega, "built_by", yard, confidence=1.5).status_code == 422


def test_relations_require_a_staff_token(client, archive):
    vega = archive.ship("Vega")
    yard = archive.organisation("Götaverken")

    response = client.post(
        f"{API}/relations",
        json={"from_subject_id": vega, "predicate": "built_by", "to_subject_id": yard},
    )

    assert response.status_code == 401
