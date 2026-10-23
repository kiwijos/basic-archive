import time

from sqlalchemy import text
from support import API, PNG, receive, upload

FAST = {"relay_enabled": True, "relay_interval_seconds": 0.05}


def create_ships(client, staff, count):
    return [
        client.post(f"{API}/ships", json={"name": f"Ship {n}"}, headers=staff).json()["id"]
        for n in range(count)
    ]


def unpublished(database):
    with database.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM outbox WHERE published_at IS NULL")
        ).scalar()


def test_a_change_reaches_its_queue_and_is_marked_published(new_client, staff, broker, database):
    client = new_client(**FAST)

    ship = client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).json()["id"]

    [(message, properties)] = receive(broker, "record.changed", expected=1)
    assert message == {"entity": "ship", "id": ship, "op": "upsert"}
    assert properties.delivery_mode == 2  # persistent: it survives a broker restart
    assert properties.content_type == "application/json"
    deadline = time.monotonic() + 5
    while unpublished(database) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert unpublished(database) == 0


def test_an_upload_publishes_its_ocr_job_to_the_ocr_queue(new_client, staff, broker):
    client = new_client(**FAST)

    document = upload(client, staff).json()

    [(job, _)] = receive(broker, "ocr.requested", expected=1)
    assert job == {"image_id": document["images"][0]["id"], "attempt": 1}


def test_events_written_while_the_broker_is_down_are_published_by_the_next_instance(
    new_client, staff, broker, database
):
    # A pod that cannot reach the broker still serves requests; the events wait in the outbox.
    cut_off = new_client(**FAST, rabbitmq_url="amqp://guest:guest@localhost:1/%2F")
    ships = create_ships(cut_off, staff, 3)
    time.sleep(0.5)
    assert unpublished(database) == 3
    assert receive(broker, "record.changed", expected=0, timeout=0.3) == []

    # Its replacement, on a working connection, loses nothing.
    new_client(**FAST)

    messages = receive(broker, "record.changed", expected=3)
    assert sorted(message["id"] for message, _ in messages) == sorted(ships)


def test_two_instances_never_publish_the_same_event_twice(new_client, staff, broker):
    first = new_client(**FAST)
    new_client(**FAST)

    ships = create_ships(first, staff, 40)

    messages = receive(broker, "record.changed", expected=40, settle=1.5)
    ids = [message["id"] for message, _ in messages]
    assert sorted(ids) == sorted(ships)


def test_an_instance_without_the_relay_publishes_nothing(new_client, staff, broker, database):
    client = new_client()

    create_ships(client, staff, 2)
    time.sleep(0.4)

    assert receive(broker, "record.changed", expected=0, timeout=0.2) == []
    assert unpublished(database) == 2
