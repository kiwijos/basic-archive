import json
import time
import uuid

import pika
from support import LINES, job, scan, wait_until

EXPECTED = " ".join(" ".join(LINES).split())


def publish(broker, body: bytes, routing_key="ocr.requested"):
    broker.basic_publish(
        "archive.events",
        routing_key,
        body,
        pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent),
    )


def waiting(broker, queue: str) -> int:
    return broker.queue_declare(queue, passive=True).method.message_count


def test_a_worker_that_loses_the_broker_goes_unready_and_then_resumes_taking_jobs(
    catalog, broker, proxy, start_worker
):
    worker = start_worker(RABBITMQ_URL=f"amqp://guest:guest@127.0.0.1:{proxy.port}/%2F")
    assert wait_until(lambda: worker.health("/readyz") == 200), worker.log()

    proxy.cut()
    assert wait_until(lambda: worker.health("/readyz") == 503, timeout=10), worker.log()
    proxy.restore()

    assert wait_until(lambda: worker.health("/readyz") == 200, timeout=30), worker.log()
    image_id = str(uuid.uuid4())
    catalog.files[image_id] = scan()
    publish(broker, job(image_id))
    assert wait_until(lambda: len(catalog.results) == 1, timeout=30), worker.log()
    assert worker.alive()


def test_a_job_is_read_and_its_result_posted_to_catalog_api(catalog, broker, start_worker):
    worker = start_worker()
    image_id = str(uuid.uuid4())
    catalog.files[image_id] = scan()

    publish(broker, job(image_id))

    assert wait_until(lambda: len(catalog.results) == 1), worker.log()
    [result] = catalog.results
    assert result["image_id"] == image_id
    assert result["source"] == "machine"
    assert " ".join(result["text"].split()) == EXPECTED
    assert result["engine"] == "tesseract"
    assert result["engine_version"][0].isdigit()
    assert result["language"] == "swe+eng"
    assert 0.8 < result["confidence"] <= 1
    assert catalog.tokens == {"Bearer worker-token"}
    assert wait_until(lambda: waiting(broker, "ocr.requested") == 0)
    assert waiting(broker, "ocr.requested.dead") == 0


def test_a_running_worker_reports_that_it_is_alive_and_ready(start_worker):
    worker = start_worker()

    assert wait_until(lambda: worker.health("/readyz") == 200), worker.log()
    assert worker.health("/healthz") == 200
    assert worker.alive()


def dead_letters(broker, queue="ocr.requested.dead"):
    messages = []
    while True:
        method, _, body = broker.basic_get(queue, auto_ack=True)
        if method is None:
            return messages
        messages.append(body)


def test_a_corrupt_image_is_retried_then_failed_and_dead_lettered_and_the_worker_lives_on(
    catalog, broker, start_worker
):
    worker = start_worker()
    broken, good = str(uuid.uuid4()), str(uuid.uuid4())
    catalog.files[broken] = b"\x89PNG\r\n\x1a\n this is not really a png"
    catalog.files[good] = scan()

    publish(broker, job(broken))

    assert wait_until(lambda: len(catalog.failures) == 1), worker.log()
    assert catalog.downloads[broken] == 3  # three bounded attempts, no more
    assert catalog.results == []
    assert wait_until(lambda: waiting(broker, "ocr.requested.dead") == 1)
    assert [json.loads(body) for body in dead_letters(broker)] == [{"image_id": broken, "attempt": 3}]
    assert catalog.failures[0]["image_id"] == broken
    assert catalog.failures[0]["reason"]
    # The worker is unharmed and the next job goes through.
    publish(broker, job(good))
    assert wait_until(lambda: [r["image_id"] for r in catalog.results] == [good]), worker.log()
    assert worker.alive()


def test_a_message_that_breaks_the_contract_is_dead_lettered_without_touching_catalog_api(
    catalog, broker, start_worker
):
    worker = start_worker()
    publish(broker, b'{"image_id": "not-a-uuid", "attempt": 1}')
    publish(broker, b"this is not even json")
    publish(broker, json.dumps({"image_id": str(uuid.uuid4()), "attempt": 0}).encode())

    assert wait_until(lambda: waiting(broker, "ocr.requested.dead") == 3), worker.log()
    assert catalog.results == [] and catalog.failures == []
    assert catalog.tokens == set()
    assert worker.alive()


def test_a_duplicate_job_is_harmless_when_catalog_api_already_has_the_result(
    catalog, broker, start_worker
):
    catalog.result_status = 409
    worker = start_worker()
    image_id = str(uuid.uuid4())
    catalog.files[image_id] = scan()

    publish(broker, job(image_id))

    assert wait_until(lambda: len(catalog.results) == 1), worker.log()
    time.sleep(1.0)  # long enough for a wrongly started retry (50 ms backoff) to show itself
    assert wait_until(lambda: waiting(broker, "ocr.requested") == 0)
    assert len(catalog.results) == 1
    assert catalog.downloads[image_id] == 1  # no retries
    assert catalog.failures == []
    assert waiting(broker, "ocr.requested.dead") == 0


def test_a_job_for_an_image_that_is_no_longer_pending_is_skipped_without_reading_it(
    catalog, broker, start_worker
):
    worker = start_worker()
    finished, unknown = str(uuid.uuid4()), str(uuid.uuid4())
    catalog.review_status[finished] = "ocr_done"
    catalog.unknown.add(unknown)

    publish(broker, job(finished))
    publish(broker, job(unknown))

    assert wait_until(lambda: waiting(broker, "ocr.requested") == 0), worker.log()
    assert wait_until(lambda: len(catalog.tokens) == 1)
    assert catalog.downloads == {}
    assert catalog.results == [] and catalog.failures == []
    assert waiting(broker, "ocr.requested.dead") == 0


def test_when_catalog_api_keeps_failing_the_job_is_retried_then_dead_lettered(
    catalog, broker, start_worker
):
    catalog.result_status = 500
    catalog.failure_status = 500
    worker = start_worker()
    image_id = str(uuid.uuid4())
    catalog.files[image_id] = scan()

    publish(broker, job(image_id))

    assert wait_until(lambda: waiting(broker, "ocr.requested.dead") == 1), worker.log()
    assert len(catalog.results) == 3  # each attempt got as far as posting its result
    assert len(catalog.failures) == 1  # reporting the failure was attempted once, and survived failing
    assert worker.alive()


def test_a_tiff_and_a_very_large_page_are_read_too(catalog, broker, start_worker):
    worker = start_worker()
    tiff, large = str(uuid.uuid4()), str(uuid.uuid4())
    catalog.files[tiff] = scan(fmt="TIFF")
    catalog.files[large] = scan(size=(5200, 3000), font_size=110)

    publish(broker, job(tiff))
    publish(broker, job(large))

    assert wait_until(lambda: len(catalog.results) == 2, timeout=60), worker.log()
    for result in catalog.results:
        assert " ".join(result["text"].split()) == EXPECTED, result["image_id"]


def test_a_page_above_the_pixel_limit_is_refused_instead_of_exhausting_memory(
    catalog, broker, start_worker
):
    worker = start_worker(MAX_IMAGE_PIXELS="1000000")
    big = str(uuid.uuid4())
    catalog.files[big] = scan(size=(1500, 1500))  # 2.25 million pixels

    publish(broker, job(big))

    assert wait_until(lambda: len(catalog.failures) == 1), worker.log()
    assert catalog.results == []
    assert "pixel" in catalog.failures[0]["reason"]


def test_several_workers_share_the_queue_and_each_job_is_done_once(catalog, broker, start_worker):
    workers = [start_worker() for _ in range(3)]
    ids = [str(uuid.uuid4()) for _ in range(9)]
    for image_id in ids:
        catalog.files[image_id] = scan()

    for image_id in ids:
        publish(broker, job(image_id))

    assert wait_until(lambda: len(catalog.results) >= 9, timeout=60), [w.log() for w in workers]
    assert wait_until(lambda: waiting(broker, "ocr.requested") == 0)
    posted = sorted(result["image_id"] for result in catalog.results)
    assert posted == sorted(ids)
    assert waiting(broker, "ocr.requested.dead") == 0
