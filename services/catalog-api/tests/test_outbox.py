API = "/api/catalog"


def make_ship(client, staff, name="Vega"):
    return client.post(f"{API}/ships", json={"name": name}, headers=staff).json()["id"]


def make_organisation(client, staff, name="Götaverken"):
    return client.post(f"{API}/organisations", json={"name": name}, headers=staff).json()["id"]


def test_creating_updating_and_deleting_a_ship_each_write_an_event(client, staff, outbox):
    ship = make_ship(client, staff)
    client.put(f"{API}/ships/{ship}", json={"ship_type": "barque"}, headers=staff)
    client.delete(f"{API}/ships/{ship}", headers=staff)

    assert outbox() == [("ship", ship, "upsert"), ("ship", ship, "upsert"), ("ship", ship, "delete")]


def test_creating_updating_and_deleting_an_organisation_each_write_an_event(client, staff, outbox):
    yard = make_organisation(client, staff)
    client.put(f"{API}/organisations/{yard}", json={"place": "Göteborg"}, headers=staff)
    client.delete(f"{API}/organisations/{yard}", headers=staff)

    assert outbox() == [
        ("organisation", yard, "upsert"),
        ("organisation", yard, "upsert"),
        ("organisation", yard, "delete"),
    ]


def test_adding_and_deleting_a_name_change_the_subject(client, staff, outbox):
    ship = make_ship(client, staff)
    sofia = client.post(
        f"{API}/subjects/{ship}/names",
        json={"name": "Sofia", "date": {"date_from": "1905-03-01"}},
        headers=staff,
    ).json()
    client.delete(f"{API}/names/{sofia['id']}", headers=staff)

    assert outbox() == [("ship", ship, "upsert")] * 3


def test_a_relation_change_is_announced_for_both_subjects(client, staff, outbox):
    ship = make_ship(client, staff)
    yard = make_organisation(client, staff)
    outbox_before = len(outbox())

    relation = client.post(
        f"{API}/relations",
        json={"from_subject_id": ship, "predicate": "built_by", "to_subject_id": yard},
        headers=staff,
    ).json()["id"]
    client.put(f"{API}/relations/{relation}", json={"place": "Göteborg"}, headers=staff)
    client.delete(f"{API}/relations/{relation}", headers=staff)

    announced = outbox()[outbox_before:]
    assert len(announced) == 6
    for step in range(3):
        assert sorted(announced[2 * step : 2 * step + 2]) == sorted(
            [("ship", ship, "upsert"), ("organisation", yard, "upsert")]
        )


def test_rejected_requests_write_no_event(client, staff, outbox):
    ship = make_ship(client, staff)
    written = len(outbox())

    client.post(f"{API}/subjects/{ship}/names", json={"name": "Sofia"}, headers=staff)
    client.post(f"{API}/ships", json={"name": " "}, headers=staff)
    client.post(f"{API}/ships", json={"name": "Vega"})
    client.post(
        f"{API}/relations",
        json={"from_subject_id": ship, "predicate": "rebuilt_from", "to_subject_id": ship},
        headers=staff,
    )
    client.delete(f"{API}/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301", headers=staff)

    assert len(outbox()) == written
