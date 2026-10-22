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
