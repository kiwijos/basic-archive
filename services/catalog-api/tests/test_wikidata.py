import pytest

API = "/api/catalog"
VASA = "Q219821"


def make_ship(client, staff, name="Vasa", **extra):
    return client.post(f"{API}/ships", json={"name": name, **extra}, headers=staff).json()["id"]


def candidates(client, staff, ship, **params):
    return client.get(f"{API}/ships/{ship}/wikidata-candidates", params=params, headers=staff)


@pytest.fixture
def known(wikidata):
    """Two things called Vasa and one other ship, as Wikidata would hold them."""
    wikidata.add(VASA, en=("Vasa", "17th century Swedish warship"), sv=("Vasa", "svenskt regalskepp från 1600-talet"))
    wikidata.add("Q1234", en=("Vasa", "city in Finland"))
    wikidata.add("Q777", en=("Wasa", "Swedish ferry"), sv=("Wasa", None))
    return wikidata


def test_asking_for_candidates_lists_them_with_descriptions_and_stores_nothing(client, staff, known, outbox):
    ship = make_ship(client, staff, "Vasa")
    events_before = len(outbox())

    answer = candidates(client, staff, ship)

    assert answer.status_code == 200
    found = {c["id"]: c for c in answer.json()["candidates"]}
    assert set(found) == {VASA, "Q1234"}
    assert found[VASA] == {
        "id": VASA,
        "label": "Vasa",
        "description": "svenskt regalskepp från 1600-talet",  # Swedish first, this is a Swedish archive
        "url": f"https://www.wikidata.org/wiki/{VASA}",
    }
    assert found["Q1234"]["description"] == "city in Finland"  # only English has it
    # Asking changes nothing: the ship has no references and no event was queued.
    assert client.get(f"{API}/ships/{ship}", headers=staff).json()["external_refs"] == []
    assert len(outbox()) == events_before


def choose(client, staff, ship, qid=VASA):
    return client.put(f"{API}/ships/{ship}/wikidata/{qid}", headers=staff)


def refs(client, staff, ship):
    return client.get(f"{API}/ships/{ship}", headers=staff).json()["external_refs"]


def test_choosing_a_candidate_stores_where_it_came_from_what_it_is_and_when_it_was_fetched(client, staff, known, outbox):
    from datetime import UTC, datetime, timedelta

    ship = make_ship(client, staff, "Vasa")
    before = len(outbox())

    answer = choose(client, staff, ship)

    assert answer.status_code == 200
    [stored] = refs(client, staff, ship)
    assert stored["source"] == "wikidata"
    assert stored["id"] == VASA
    assert stored["label"] == "Vasa"
    assert stored["description"] == "svenskt regalskepp från 1600-talet"
    assert stored["url"] == f"https://www.wikidata.org/wiki/{VASA}"
    assert stored["chosen_by"] == "alice"
    fetched = datetime.fromisoformat(stored["retrieved_at"])
    assert abs(datetime.now(UTC) - fetched) < timedelta(seconds=30)
    assert answer.json() == stored
    assert [e for e in outbox()[before:] if e[0] == "ship" and e[1] == ship] == [("ship", ship, "upsert")]


def test_what_is_stored_is_what_wikidata_says_not_what_the_client_sends(client, staff, known):
    ship = make_ship(client, staff)

    client.put(f"{API}/ships/{ship}/wikidata/{VASA}", json={"label": "Hacked", "description": "x"}, headers=staff)

    assert refs(client, staff, ship)[0]["label"] == "Vasa"
    assert known.asked("wbgetentities")[0]["params"]["ids"] == VASA


def test_choosing_the_same_entity_again_refreshes_it_instead_of_adding_a_second_copy(client, staff, known):
    ship = make_ship(client, staff)
    choose(client, staff, ship)
    first = refs(client, staff, ship)[0]["retrieved_at"]
    known.add(VASA, en=("Vasa", "changed description"))

    choose(client, staff, ship)

    [stored] = refs(client, staff, ship)
    assert stored["description"] == "changed description"
    assert stored["retrieved_at"] >= first


def test_a_ship_can_hold_more_than_one_match_and_each_ship_has_its_own(client, staff, known):
    one, two = make_ship(client, staff, "Vasa"), make_ship(client, staff, "Wasa")

    choose(client, staff, one, VASA)
    choose(client, staff, one, "Q777")

    assert [r["id"] for r in refs(client, staff, one)] == [VASA, "Q777"]  # in the order they were chosen
    assert refs(client, staff, two) == []


def test_only_staff_may_ask_or_choose_and_only_for_ships_that_exist(client, staff, known):
    ship = make_ship(client, staff)
    nobody = {}
    worker = {"Authorization": "Bearer worker-token"}
    unknown = "7d444840-9dc0-11d1-b245-5ffdce74fad2"

    for headers in (nobody, worker):
        assert client.get(f"{API}/ships/{ship}/wikidata-candidates", headers=headers).status_code == 401
        assert client.put(f"{API}/ships/{ship}/wikidata/{VASA}", headers=headers).status_code == 401
    assert candidates(client, staff, unknown).status_code == 404
    assert choose(client, staff, unknown).status_code == 404
    assert refs(client, staff, ship) == []


def test_an_identifier_that_is_not_a_wikidata_item_is_refused_without_asking_wikidata(client, staff, known):
    ship = make_ship(client, staff)

    for bad in ("Q0", "q42", "P31", "Q12x", "42", "Q" + "9" * 30):
        assert choose(client, staff, ship, bad).status_code == 422, bad
    assert known.asked("wbgetentities") == []


def test_an_item_wikidata_does_not_have_cannot_be_chosen(client, staff, known):
    ship = make_ship(client, staff)

    answer = choose(client, staff, ship, "Q999999")

    assert answer.status_code == 404
    assert "Q999999" in answer.json()["detail"]
    assert refs(client, staff, ship) == []


# ---- Wikidata is slow, failing or broken: a clear message, bounded effort, and editing carries on --------------------


def failing(wikidata, action, *steps):
    wikidata.script(action, *steps)


def test_a_wikidata_that_answers_slowly_gives_a_timeout_message_after_the_attempts_allowed(new_client, staff, known):
    client = new_client(wikidata_timeout_seconds=0.2, wikidata_attempts=3)
    ship = make_ship(client, staff)
    failing(known, "wbsearchentities", *[{"delay": 0.6}] * 3)

    answer = candidates(client, staff, ship)

    assert answer.status_code == 504
    assert "did not answer in time" in answer.json()["detail"]
    assert len(known.asked("wbsearchentities")) == 3


def test_a_failure_that_passes_is_retried_and_the_person_never_sees_it(client, staff, known):
    ship = make_ship(client, staff)
    failing(known, "wbsearchentities", {"status": 503}, {"status": 429})

    answer = candidates(client, staff, ship)

    assert answer.status_code == 200
    assert {c["id"] for c in answer.json()["candidates"]} == {VASA, "Q1234"}
    assert len(known.asked("wbsearchentities")) == 4  # two failed tries, then both languages


def test_repeated_server_errors_end_in_a_clear_message_after_exactly_the_attempts_allowed(client, staff, known):
    ship = make_ship(client, staff)
    failing(known, "wbsearchentities", *[{"status": 503}] * 3)

    answer = candidates(client, staff, ship)

    assert answer.status_code == 502
    assert "not available right now" in answer.json()["detail"]
    assert "503" in answer.json()["detail"]
    assert len(known.asked("wbsearchentities")) == 3


def test_being_told_to_slow_down_is_retried_and_then_reported_as_such(client, staff, known):
    ship = make_ship(client, staff)
    failing(known, "wbsearchentities", *[{"status": 429}] * 3)

    answer = candidates(client, staff, ship)

    assert answer.status_code == 502
    assert "too many requests" in answer.json()["detail"].lower()
    assert len(known.asked("wbsearchentities")) == 3


def test_a_refusal_that_would_not_change_is_not_retried(client, staff, known):
    ship = make_ship(client, staff)
    failing(known, "wbsearchentities", {"status": 403, "body": "forbidden"})

    answer = candidates(client, staff, ship)

    assert answer.status_code == 502
    assert "403" in answer.json()["detail"]
    assert len(known.asked("wbsearchentities")) == 1


def test_an_answer_that_is_not_what_wikidata_sends_is_reported_without_retrying(client, staff, known):
    ship = make_ship(client, staff)

    failing(known, "wbsearchentities", {"raw": "<html>Maintenance</html>"})
    html = candidates(client, staff, ship)
    failing(known, "wbsearchentities", {"json": {"error": {"code": "internal_api_error", "info": "boom"}}})
    error = candidates(client, staff, ship)
    failing(known, "wbsearchentities", {"json": {"search": "not a list"}})
    shaped = candidates(client, staff, ship)

    for answer in (html, error, shaped):
        assert answer.status_code == 502
        assert "unexpected" in answer.json()["detail"].lower()
    assert len(known.asked("wbsearchentities")) == 3


def test_a_wikidata_that_cannot_be_reached_is_reported_as_unavailable(new_client, staff, known):
    client = new_client(wikidata_api_url="http://127.0.0.1:1/w/api.php")
    ship = make_ship(client, staff)

    answer = candidates(client, staff, ship)

    assert answer.status_code == 502
    assert "not available right now" in answer.json()["detail"]


def test_the_total_effort_is_bounded_by_the_budget_even_for_the_last_try(new_client, staff, known):
    import time

    # Each try may take 0.5 s, the whole operation 0.7 s: the second try must be cut short at 0.2 s.
    client = new_client(wikidata_timeout_seconds=0.5, wikidata_attempts=20, wikidata_budget_seconds=0.7)
    ship = make_ship(client, staff)
    failing(known, "wbsearchentities", *[{"delay": 1.0}] * 20)

    started = time.monotonic()
    answer = candidates(client, staff, ship)
    took = time.monotonic() - started

    assert answer.status_code == 504
    assert took < 0.95, f"took {took:.2f} s against a budget of 0.7 s"
    assert len(known.asked("wbsearchentities")) <= 3


def test_when_wikidata_fails_choosing_stores_nothing_and_the_ship_stays_editable(client, staff, known, outbox):
    ship = make_ship(client, staff)
    failing(known, "wbgetentities", *[{"status": 500}] * 3)
    before = len(outbox())

    chosen = choose(client, staff, ship)

    assert chosen.status_code == 502
    assert refs(client, staff, ship) == []
    assert len(outbox()) == before
    # Everything else about the Ship works as if Wikidata did not exist.
    assert client.put(f"{API}/ships/{ship}", json={"ship_type": "warship"}, headers=staff).status_code == 200
    assert client.post(f"{API}/subjects/{ship}/names", json={"name": "Wasa", "date": {"date_from": "1700-01-01"}}, headers=staff).status_code == 201
    assert client.get(f"{API}/ships/{ship}", headers=staff).json()["ship_type"] == "warship"


def test_a_name_wikidata_has_nothing_for_gives_an_empty_list_not_an_error(client, staff, known):
    ship = make_ship(client, staff, "Ett skepp som ingen hört talas om")

    answer = candidates(client, staff, ship)

    assert answer.status_code == 200
    assert answer.json()["candidates"] == []


def test_the_person_can_search_for_something_other_than_the_ships_current_name(client, staff, known):
    ship = make_ship(client, staff, "Nordstjernan")

    answer = candidates(client, staff, ship, q="Wasa")

    assert [c["id"] for c in answer.json()["candidates"]] == ["Q777"]
    assert answer.json()["query"] == "Wasa"
    assert candidates(client, staff, ship, q="").status_code == 422
    assert candidates(client, staff, ship, q="x" * 201).status_code == 422


def test_every_request_to_wikidata_says_who_is_asking(client, staff, known):
    ship = make_ship(client, staff)
    candidates(client, staff, ship)

    agent = known.asked("wbsearchentities")[0]["headers"]["User-Agent"]

    assert "ShipArchiveLite" in agent and "github.com/kiwijos/basic-archive" in agent


# ---- a wrong choice can be undone, with no help from Wikidata -------------------------------------------------------


def test_a_wrong_choice_can_be_removed_even_while_wikidata_is_down(new_client, staff, known, outbox):
    working = new_client()
    ship = make_ship(working, staff)
    choose(working, staff, ship, VASA)
    choose(working, staff, ship, "Q777")
    # The same archive, a moment later, with nothing answering at Wikidata's address.
    down = new_client(wikidata_api_url="http://127.0.0.1:1/w/api.php")
    before = len(outbox())

    removed = down.delete(f"{API}/ships/{ship}/wikidata/{VASA}", headers=staff)

    assert removed.status_code == 204
    assert [r["id"] for r in refs(down, staff, ship)] == ["Q777"]
    assert ("ship", ship, "upsert") in outbox()[before:]
    assert choose(down, staff, ship, VASA).status_code == 502  # choosing needs Wikidata; removing does not


def test_removing_what_is_not_stored_says_so_and_only_staff_may_remove(client, staff, known, outbox):
    ship = make_ship(client, staff)
    choose(client, staff, ship, "Q777")
    before = len(outbox())

    assert client.delete(f"{API}/ships/{ship}/wikidata/{VASA}", headers=staff).status_code == 404
    assert client.delete(f"{API}/ships/{ship}/wikidata/{VASA}").status_code == 401
    assert client.delete(f"{API}/ships/{ship}/wikidata/not-an-id", headers=staff).status_code == 422
    assert [r["id"] for r in refs(client, staff, ship)] == ["Q777"]
    assert len(outbox()) == before


# ---- found in review ------------------------------------------------------------------------------------------------


def test_there_must_be_a_name_to_look_for_and_wikidata_is_not_asked_without_one(client, staff, known):
    ship = make_ship(client, staff, "Vasa")
    [only_name] = client.get(f"{API}/subjects/{ship}/names", headers=staff).json()
    client.delete(f"{API}/names/{only_name['id']}", headers=staff)

    nameless = candidates(client, staff, ship)
    blank = candidates(client, staff, make_ship(client, staff, "Freja"), q="   ")

    assert nameless.status_code == 422 and "no name" in nameless.json()["detail"].lower()
    assert blank.status_code == 422 and "type a name" in blank.json()["detail"].lower()
    assert known.asked("wbsearchentities") == []
    # Typing a name works even for a ship that has none.
    assert candidates(client, staff, ship, q="Wasa").status_code == 200


def test_a_hit_missing_a_description_in_one_language_gets_it_from_the_other_and_the_list_is_capped(client, staff, known):
    ship = make_ship(client, staff, "Wasa")
    for n in range(14):
        known.add(f"Q{5000 + n}", en=(f"Wasa {n}", f"description {n}"))

    ferry = candidates(client, staff, ship, q="Wasa").json()["candidates"]

    assert len(ferry) == 10
    assert next(c for c in ferry if c["id"] == "Q777")["description"] == "Swedish ferry"  # Swedish had none, English did
    assert len({c["id"] for c in ferry}) == 10


def test_a_label_wikidata_lacks_in_both_languages_falls_back_to_the_identifier(client, staff, wikidata):
    wikidata.add("Q4242", en=None, sv=None)
    wikidata.entities["Q4242"] = {"de": ("Nur Deutsch", "kein Schwedisch")}
    ship = make_ship(client, staff, "Nur Deutsch")

    chosen = choose(client, staff, ship, "Q4242")

    assert chosen.status_code == 200
    assert chosen.json()["label"] == "Q4242" and chosen.json()["description"] is None


def test_an_item_that_was_merged_into_another_is_stored_under_the_one_wikidata_now_uses(client, staff, known):
    known.redirect("Q5", VASA)
    ship = make_ship(client, staff)

    chosen = choose(client, staff, ship, "Q5")

    assert chosen.status_code == 200
    assert chosen.json()["id"] == VASA and chosen.json()["url"].endswith(VASA)
    assert [r["id"] for r in refs(client, staff, ship)] == [VASA]


def test_an_item_with_a_shape_wikidata_does_not_send_is_an_unexpected_answer_not_a_crash(client, staff, known):
    ship = make_ship(client, staff)
    odd = [
        {"entities": {VASA: "just a string"}},
        {"entities": {VASA: {"id": VASA, "labels": {"sv": "not an object"}}}},
        {"entities": {VASA: {"id": VASA, "labels": {"sv": {"value": 42}}}}},
        {"entities": {VASA: {"id": VASA, "labels": [], "descriptions": "x"}}},
        {"entities": []},
    ]

    for body in odd:
        known.script("wbgetentities", {"json": body})
        answer = choose(client, staff, ship)
        assert answer.status_code == 502, body
        assert "unexpected" in answer.json()["detail"].lower()
    assert refs(client, staff, ship) == []


@pytest.mark.parametrize("action", ["candidates", "choose"])
def test_no_database_connection_is_held_while_waiting_for_wikidata(new_client, staff, known, action):
    import threading
    import time

    client = new_client(wikidata_timeout_seconds=2.0)
    ship = make_ship(client, staff)
    ask = {"candidates": lambda: candidates(client, staff, ship), "choose": lambda: choose(client, staff, ship)}[action]
    known.script({"candidates": "wbsearchentities", "choose": "wbgetentities"}[action], {"delay": 0.8})
    holder = threading.Thread(target=ask)
    holder.start()
    time.sleep(0.4)

    checked_out = client.app.state.engine.pool.checkedout()
    holder.join()

    assert checked_out == 0, "a slow Wikidata would tie up the pool the rest of the archive uses"


def test_two_choices_made_at_the_same_moment_are_both_kept(client, staff, known):
    from concurrent.futures import ThreadPoolExecutor

    ship = make_ship(client, staff)
    known.script("wbgetentities", {"delay": 0.3}, {"delay": 0.3})

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda qid: choose(client, staff, ship, qid).status_code, [VASA, "Q777"]))

    assert results == [200, 200]
    assert sorted(r["id"] for r in refs(client, staff, ship)) == sorted([VASA, "Q777"])


def test_a_failed_try_does_not_fire_the_next_one_at_once_when_there_is_no_time_left_to_wait(new_client, staff, known):
    client = new_client(wikidata_attempts=5, wikidata_backoff_seconds=1.0, wikidata_budget_seconds=0.5)
    ship = make_ship(client, staff)
    known.script("wbsearchentities", *[{"status": 503}] * 5)

    import time

    started = time.monotonic()
    answer = candidates(client, staff, ship)
    took = time.monotonic() - started

    assert answer.status_code == 502
    assert len(known.asked("wbsearchentities")) == 1, "hammering a service that just said it is struggling"
    assert took < 0.4, f"slept {took:.2f} s past a 0.5 s budget"


def test_a_deleted_ship_and_an_organisation_are_not_ships_for_wikidata(client, staff, known):
    ship = make_ship(client, staff)
    organisation = client.post(f"{API}/organisations", json={"name": "Götaverken"}, headers=staff).json()["id"]
    client.delete(f"{API}/ships/{ship}", headers=staff)

    for subject in (ship, organisation):
        assert candidates(client, staff, subject).status_code == 404
        assert choose(client, staff, subject).status_code == 404
        assert client.delete(f"{API}/ships/{subject}/wikidata/{VASA}", headers=staff).status_code == 404
    assert known.asked("wbgetentities") == []
