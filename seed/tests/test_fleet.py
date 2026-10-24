from archive_seed.fleet import SYNTHETIC
from archive_seed.loader import Seeder

API = "/api/catalog"


def ships_by_name(archive):
    found = archive.get(f"{API}/ships", params={"source_system": "seed"}).json()
    return {ship["source_id"]: ship for ship in found}


def names_of(archive, ship_id):
    return archive.get(f"{API}/subjects/{ship_id}/names").json()


def relations_of(archive, subject_id, **params):
    return archive.get(f"{API}/subjects/{subject_id}/relations", params=params).json()


def test_the_fleet_is_created_with_its_firms_ships_and_where_each_came_from(archive):
    report = Seeder(archive).seed_fleet()

    organisations = archive.get(f"{API}/organisations", params={"source_system": "seed"}).json()
    assert sorted(o["name"] for o in organisations) == ["Rederi AB Nordsjö", "Rederi AB Sund", "Älvsborgs Skeppsvarv"]
    assert {o["name"]: (o["organisation_type"], o["place"]) for o in organisations}["Älvsborgs Skeppsvarv"] == ("shipyard", "Göteborg")
    ships = ships_by_name(archive)
    assert sorted(ships) == ["ship-alvdrottningen", "ship-linnea", "ship-nordstjarnan", "ship-svalan"]
    assert (ships["ship-linnea"]["ship_type"], ships["ship-linnea"]["tonnage"]) == ("schooner", 143)
    assert ships["ship-nordstjarnan"]["launched"]["date_text"] == "mars 1889"
    assert report.created["organisations"] == 3 and report.created["ships"] == 4


def test_one_ship_has_three_names_over_its_life_and_is_known_today_by_the_last(archive):
    Seeder(archive).seed_fleet()
    ship = ships_by_name(archive)["ship-nordstjarnan"]

    names = names_of(archive, ship["id"])

    assert [n["name"] for n in names] == ["Nordstjärnan", "Sofia", "Havsörnen"]
    assert [n["date"]["date_from"] if n["date"] else None for n in names[1:]] == ["1903-04-15", "1921-03-01"]
    assert archive.get(f"{API}/ships/{ship['id']}").json()["name"] == "Havsörnen"
    assert all(n["source"] == SYNTHETIC for n in names[1:])


def test_the_barque_was_sold_once_so_it_has_two_owners_one_after_the_other(archive):
    Seeder(archive).seed_fleet()
    ship = ships_by_name(archive)["ship-nordstjarnan"]

    owners = relations_of(archive, ship["id"], predicate="owned_by")

    assert [o["to_name"] for o in owners] == ["Rederi AB Nordsjö", "Rederi AB Sund"]
    assert owners[0]["date"]["date_to"] == owners[1]["date"]["date_from"] == "1903-04-15"
    assert owners[1]["date"]["date_to"] is None
    built = relations_of(archive, ship["id"], predicate="built_by")
    assert [b["to_name"] for b in built] == ["Älvsborgs Skeppsvarv"]


def test_a_rebuilt_hull_is_a_new_ship_linked_back_to_the_old_one_and_each_end_shows_it(archive):
    Seeder(archive).seed_fleet()
    ships = ships_by_name(archive)
    new, old = ships["ship-alvdrottningen"], ships["ship-nordstjarnan"]

    [rebuilt] = relations_of(archive, new["id"], predicate="rebuilt_from")

    assert (rebuilt["from_subject_id"], rebuilt["to_subject_id"]) == (new["id"], old["id"])
    assert rebuilt["date"]["date_text"] == "1933–34" and rebuilt["source"] == SYNTHETIC
    assert [r["from_subject_id"] for r in relations_of(archive, old["id"], predicate="rebuilt_from")] == [new["id"]]
    assert new["id"] != old["id"]


def test_loading_the_fleet_again_changes_nothing(archive):
    first = Seeder(archive).seed_fleet()
    before = {k: archive.get(f"{API}/{k}", params={"source_system": "seed"}).json() for k in ("ships", "organisations")}

    second = Seeder(archive).seed_fleet()

    assert sum(first.created.values()) > 0
    assert sum(second.created.values()) == 0
    assert second.found["ships"] == 4 and second.found["organisations"] == 3
    assert {k: archive.get(f"{API}/{k}", params={"source_system": "seed"}).json() for k in ("ships", "organisations")} == before
    ship = ships_by_name(archive)["ship-nordstjarnan"]
    assert len(names_of(archive, ship["id"])) == 3 and len(relations_of(archive, ship["id"])) == 4
