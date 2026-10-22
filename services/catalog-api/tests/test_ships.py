def test_creating_a_ship_without_a_token_is_refused(client):
    response = client.post("/api/catalog/ships", json={"name": "Vega"})

    assert response.status_code == 401


def test_a_ship_created_with_a_staff_token_records_the_author(client):
    response = client.post(
        "/api/catalog/ships",
        json={"name": "Vega"},
        headers={"Authorization": "Bearer bob-token"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Vega"
    assert body["created_by"] == "bob"
    assert body["id"]


def test_a_created_ship_can_be_read_back_by_a_new_app_instance(client, new_client):
    staff = {"Authorization": "Bearer alice-token"}
    created = client.post("/api/catalog/ships", json={"name": "Vega"}, headers=staff).json()

    response = new_client().get(f"/api/catalog/ships/{created['id']}", headers=staff)

    assert response.status_code == 200
    assert response.json() == created


def test_reading_a_ship_requires_a_staff_token(client):
    response = client.get("/api/catalog/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301")

    assert response.status_code == 401


def test_reading_an_unknown_ship_is_not_found(client):
    response = client.get(
        "/api/catalog/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        headers={"Authorization": "Bearer alice-token"},
    )

    assert response.status_code == 404


def test_a_ship_needs_a_name(client):
    response = client.post(
        "/api/catalog/ships",
        json={"name": "   "},
        headers={"Authorization": "Bearer alice-token"},
    )

    assert response.status_code == 422


def test_a_ship_records_its_type_tonnage_and_fate_as_last_recorded(client, staff):
    facts = {
        "name": "Vega",
        "ship_type": "barque",
        "tonnage": 357.5,
        "fate": "wrecked off Hanö",
        "fate_date": {"date_text": "autumn 1913", "date_from": "1913-09-01", "date_to": "1913-11-30"},
    }

    created = client.post("/api/catalog/ships", json=facts, headers=staff).json()

    read_back = client.get(f"/api/catalog/ships/{created['id']}", headers=staff).json()
    assert read_back["ship_type"] == "barque"
    assert read_back["tonnage"] == 357.5
    assert read_back["fate"] == "wrecked off Hanö"
    assert read_back["fate_date"]["date_text"] == "autumn 1913"


def test_a_ships_facts_can_be_updated_without_touching_its_name(client, staff):
    created = client.post(
        "/api/catalog/ships", json={"name": "Vega", "tonnage": 300}, headers=staff
    ).json()

    updated = client.put(
        f"/api/catalog/ships/{created['id']}",
        json={"ship_type": "steamer", "tonnage": 410},
        headers=staff,
    )

    assert updated.status_code == 200
    assert updated.json()["name"] == "Vega"
    assert updated.json()["ship_type"] == "steamer"
    assert updated.json()["tonnage"] == 410
    assert client.get(f"/api/catalog/ships/{created['id']}", headers=staff).json() == updated.json()


def test_updating_an_unknown_ship_is_not_found(client, staff):
    response = client.put(
        "/api/catalog/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        json={"ship_type": "steamer"},
        headers=staff,
    )

    assert response.status_code == 404
