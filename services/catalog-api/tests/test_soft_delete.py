from sqlalchemy import text

API = "/api/catalog"


def test_a_deleted_ship_disappears_from_every_read_but_stays_in_the_database(
    client, staff, database
):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]

    deleted = client.delete(f"{API}/ships/{ship}", headers=staff)

    assert deleted.status_code == 204
    assert client.get(f"{API}/ships/{ship}", headers=staff).status_code == 404
    assert client.get(f"{API}/subjects/{ship}/names", headers=staff).status_code == 404
    assert client.delete(f"{API}/ships/{ship}", headers=staff).status_code == 404
    # Not observable through the API by design, so this is the one direct look at the table.
    with database.connect() as connection:
        row = connection.execute(
            text("SELECT deleted_at FROM subject WHERE id = :id"), {"id": ship}
        ).one()
    assert row.deleted_at is not None


def test_a_deleted_organisation_disappears(client, staff):
    organisation = client.post(
        f"{API}/organisations", json={"name": "Götaverken"}, headers=staff
    ).json()["id"]

    assert client.delete(f"{API}/organisations/{organisation}", headers=staff).status_code == 204
    assert client.get(f"{API}/organisations/{organisation}", headers=staff).status_code == 404


def test_a_deleted_ship_no_longer_shows_in_the_relations_of_its_builder(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]
    yard = client.post(f"{API}/organisations", json={"name": "Götaverken"}, headers=staff).json()["id"]
    client.post(
        f"{API}/relations",
        json={"from_subject_id": ship, "predicate": "built_by", "to_subject_id": yard},
        headers=staff,
    )

    client.delete(f"{API}/ships/{ship}", headers=staff)

    assert client.get(f"{API}/subjects/{yard}/relations", headers=staff).json() == []


def test_a_deleted_relation_disappears_from_both_ends(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]
    yard = client.post(f"{API}/organisations", json={"name": "Götaverken"}, headers=staff).json()["id"]
    relation = client.post(
        f"{API}/relations",
        json={"from_subject_id": ship, "predicate": "built_by", "to_subject_id": yard},
        headers=staff,
    ).json()["id"]

    assert client.delete(f"{API}/relations/{relation}", headers=staff).status_code == 204

    assert client.get(f"{API}/subjects/{ship}/relations", headers=staff).json() == []
    assert client.get(f"{API}/subjects/{yard}/relations", headers=staff).json() == []
    assert client.put(f"{API}/relations/{relation}", json={}, headers=staff).status_code == 404


def test_a_deleted_name_leaves_the_history_and_the_previous_name_is_current(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]
    sofia = client.post(
        f"{API}/subjects/{ship}/names",
        json={"name": "Sofia", "date": {"date_from": "1905-03-01"}},
        headers=staff,
    ).json()

    assert client.delete(f"{API}/names/{sofia['id']}", headers=staff).status_code == 204

    history = client.get(f"{API}/subjects/{ship}/names", headers=staff).json()
    assert [n["name"] for n in history] == ["Vega"]
    assert client.get(f"{API}/ships/{ship}", headers=staff).json()["name"] == "Vega"


def test_a_ship_whose_only_name_is_deleted_has_no_current_name(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]
    [only] = client.get(f"{API}/subjects/{ship}/names", headers=staff).json()

    client.delete(f"{API}/names/{only['id']}", headers=staff)

    assert client.get(f"{API}/ships/{ship}", headers=staff).json()["name"] is None


def test_deleting_requires_a_staff_token(client, staff):
    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]

    assert client.delete(f"{API}/ships/{ship}").status_code == 401
