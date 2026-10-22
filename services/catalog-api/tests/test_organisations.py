def test_an_organisation_is_created_and_read_back(client, staff):
    created = client.post(
        "/api/catalog/organisations",
        json={"name": "Götaverken", "organisation_type": "shipyard", "place": "Göteborg"},
        headers=staff,
    )

    assert created.status_code == 201
    read_back = client.get(f"/api/catalog/organisations/{created.json()['id']}", headers=staff)
    assert read_back.json() == created.json()
    assert read_back.json()["name"] == "Götaverken"
    assert read_back.json()["organisation_type"] == "shipyard"
    assert read_back.json()["created_by"] == "alice"


def test_an_organisations_facts_can_be_updated(client, staff):
    created = client.post(
        "/api/catalog/organisations", json={"name": "Götaverken"}, headers=staff
    ).json()

    updated = client.put(
        f"/api/catalog/organisations/{created['id']}",
        json={"organisation_type": "shipyard", "place": "Göteborg"},
        headers=staff,
    )

    assert updated.status_code == 200
    assert updated.json()["place"] == "Göteborg"
    assert updated.json()["name"] == "Götaverken"


def test_an_organisation_is_renamed_like_a_ship(client, staff):
    created = client.post(
        "/api/catalog/organisations", json={"name": "Motala Verkstad"}, headers=staff
    ).json()

    client.post(
        f"/api/catalog/subjects/{created['id']}/names",
        json={"name": "Motala Verkstads AB", "date": {"date_from": "1897-01-01"}},
        headers=staff,
    )

    read_back = client.get(f"/api/catalog/organisations/{created['id']}", headers=staff)
    assert read_back.json()["name"] == "Motala Verkstads AB"


def test_ships_and_organisations_are_not_mistaken_for_each_other(client, staff):
    ship = client.post("/api/catalog/ships", json={"name": "Vega"}, headers=staff).json()
    organisation = client.post(
        "/api/catalog/organisations", json={"name": "Götaverken"}, headers=staff
    ).json()

    assert client.get(f"/api/catalog/organisations/{ship['id']}", headers=staff).status_code == 404
    assert client.get(f"/api/catalog/ships/{organisation['id']}", headers=staff).status_code == 404
    assert client.put(
        f"/api/catalog/ships/{organisation['id']}", json={"ship_type": "x"}, headers=staff
    ).status_code == 404


def test_organisations_require_a_staff_token_and_a_name(client, staff):
    assert client.post("/api/catalog/organisations", json={"name": "X"}).status_code == 401
    assert client.post(
        "/api/catalog/organisations", json={"name": " "}, headers=staff
    ).status_code == 422
