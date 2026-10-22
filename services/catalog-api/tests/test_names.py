import pytest


@pytest.fixture
def vega(client, staff):
    return client.post("/api/catalog/ships", json={"name": "Vega"}, headers=staff).json()["id"]


def rename(client, staff, subject_id, name, date_from=None, **extra):
    body = {"name": name, "date": {"date_from": date_from}, **extra}
    return client.post(f"/api/catalog/subjects/{subject_id}/names", json=body, headers=staff)


def test_a_ship_renamed_twice_keeps_one_ship_and_its_name_history(client, staff, vega):
    assert rename(client, staff, vega, "Sofia", "1905-03-01").status_code == 201
    assert rename(client, staff, vega, "Nordstjernan", "1921-06-01").status_code == 201

    ship = client.get(f"/api/catalog/ships/{vega}", headers=staff).json()
    assert ship["id"] == vega
    assert ship["name"] == "Nordstjernan"

    history = client.get(f"/api/catalog/subjects/{vega}/names", headers=staff).json()
    assert [(n["name"], n["date"]) for n in history] == [
        ("Vega", {"date_text": None, "date_from": None, "date_to": "1905-03-01"}),
        ("Sofia", {"date_text": None, "date_from": "1905-03-01", "date_to": "1921-06-01"}),
        ("Nordstjernan", {"date_text": None, "date_from": "1921-06-01", "date_to": None}),
    ]


def test_a_rename_must_say_when_it_happened(client, staff, vega):
    response = client.post(
        f"/api/catalog/subjects/{vega}/names", json={"name": "Sofia"}, headers=staff
    )

    assert response.status_code == 422
    assert "date" in response.json()["detail"]


def test_a_rename_cannot_start_before_the_name_it_replaces(client, staff, vega):
    rename(client, staff, vega, "Sofia", "1905-03-01")

    response = rename(client, staff, vega, "Nordstjernan", "1900-01-01")

    assert response.status_code == 422


def test_a_past_name_with_an_end_date_does_not_change_the_current_name(client, staff, vega):
    earlier = {"name": "Gustaf", "date": {"date_text": "before 1890", "date_to": "1890-01-01"}}

    response = client.post(f"/api/catalog/subjects/{vega}/names", json=earlier, headers=staff)

    assert response.status_code == 201
    assert client.get(f"/api/catalog/ships/{vega}", headers=staff).json()["name"] == "Vega"
    names = client.get(f"/api/catalog/subjects/{vega}/names", headers=staff).json()
    assert [n["name"] for n in names] == ["Gustaf", "Vega"]


def test_names_belong_to_an_existing_subject_and_need_text(client, staff, vega):
    unknown = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    assert rename(client, staff, unknown, "Sofia", "1905-03-01").status_code == 404
    assert rename(client, staff, vega, "  ", "1905-03-01").status_code == 422
    assert client.get(f"/api/catalog/subjects/{unknown}/names", headers=staff).status_code == 404


def test_names_require_a_staff_token(client, vega):
    response = client.post(f"/api/catalog/subjects/{vega}/names", json={"name": "Sofia"})

    assert response.status_code == 401


def test_an_alias_neither_ends_nor_replaces_the_current_name(client, staff, vega):
    alias = client.post(
        f"/api/catalog/subjects/{vega}/names",
        json={"name": "Wiking", "name_type": "alias", "date": {"date_from": "1900-01-01"}},
        headers=staff,
    )

    assert alias.status_code == 201
    assert client.get(f"/api/catalog/ships/{vega}", headers=staff).json()["name"] == "Vega"
    history = client.get(f"/api/catalog/subjects/{vega}/names", headers=staff).json()
    assert {n["name"]: n["date"]["date_to"] if n["date"] else None for n in history} == {
        "Vega": None,
        "Wiking": None,
    }


def test_an_undated_alias_is_accepted_alongside_an_existing_name(client, staff, vega):
    alias = client.post(
        f"/api/catalog/subjects/{vega}/names",
        json={"name": "Wiking", "name_type": "alias"},
        headers=staff,
    )

    assert alias.status_code == 201


def test_a_name_whose_period_overlaps_another_name_is_rejected(client, staff, vega):
    earlier = {"name": "Gustaf", "date": {"date_from": "1900-01-01", "date_to": "1910-01-01"}}
    assert client.post(
        f"/api/catalog/subjects/{vega}/names", json=earlier, headers=staff
    ).status_code == 201

    overlapping = rename(client, staff, vega, "Sofia", "1905-01-01")
    adjacent = rename(client, staff, vega, "Sofia", "1910-01-01")

    assert overlapping.status_code == 422
    assert adjacent.status_code == 201
