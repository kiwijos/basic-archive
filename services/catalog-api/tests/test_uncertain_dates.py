def test_a_ship_keeps_an_uncertain_launch_date_as_written(client, staff):
    launched = {"date_text": "ca 1890", "date_from": "1889-01-01", "date_to": "1891-12-31"}

    created = client.post(
        "/api/catalog/ships", json={"name": "Vega", "launched": launched}, headers=staff
    )

    assert created.status_code == 201
    assert created.json()["launched"] == launched
    read_back = client.get(f"/api/catalog/ships/{created.json()['id']}", headers=staff)
    assert read_back.json()["launched"] == launched


def test_an_uncertain_date_whose_range_is_inverted_is_rejected(client, staff):
    inverted = {"date_text": "ca 1890", "date_from": "1891-12-31", "date_to": "1889-01-01"}

    response = client.post(
        "/api/catalog/ships", json={"name": "Vega", "launched": inverted}, headers=staff
    )

    assert response.status_code == 422


def test_an_uncertain_date_may_be_only_text(client, staff):
    response = client.post(
        "/api/catalog/ships",
        json={"name": "Vega", "launched": {"date_text": "sometime before the war"}},
        headers=staff,
    )

    assert response.status_code == 201
    assert response.json()["launched"] == {
        "date_text": "sometime before the war",
        "date_from": None,
        "date_to": None,
    }
