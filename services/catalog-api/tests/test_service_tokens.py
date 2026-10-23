from support import API, upload

WORKER = {"Authorization": "Bearer worker-token"}
UNKNOWN = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
MACHINE_RESULT = {
    "source": "machine",
    "text": "x",
    "engine": "tesseract",
    "engine_version": "5",
    "language": "swe+eng",
    "confidence": 0.9,
}


def test_the_workers_token_does_what_the_worker_does(client, staff):
    image = upload(client, staff).json()["images"][0]["id"]

    assert client.get(f"{API}/images/{image}", headers=WORKER).status_code == 200
    assert client.get(f"{API}/images/{image}/download-url", headers=WORKER).status_code == 200
    assert client.post(f"{API}/images/{image}/transcriptions", json=MACHINE_RESULT, headers=WORKER).status_code == 201
    assert client.post(f"{API}/images/{image}/ocr-failure", json={}, headers=WORKER).status_code == 409


def test_the_workers_token_cannot_do_what_only_staff_may(client, staff):
    document = upload(client, staff).json()
    image = document["images"][0]["id"]

    refused = [
        client.post(f"{API}/ships", json={"name": "Vega"}, headers=WORKER),
        client.post(f"{API}/organisations", json={"name": "Yard"}, headers=WORKER),
        client.get(f"{API}/documents/{document['id']}", headers=WORKER),
        client.get(f"{API}/images/{image}/transcriptions", headers=WORKER),
        client.post(f"{API}/images/{image}/ocr", headers=WORKER),
        client.put(f"{API}/documents/{document['id']}/subjects/{UNKNOWN}", json={}, headers=WORKER),
        upload(client, WORKER),
    ]

    assert [response.status_code for response in refused] == [401] * len(refused)


def test_a_staff_token_cannot_pose_as_the_worker(client, staff):
    image = upload(client, staff).json()["images"][0]["id"]

    forged = client.post(f"{API}/images/{image}/transcriptions", json=MACHINE_RESULT, headers=staff)
    failure = client.post(f"{API}/images/{image}/ocr-failure", json={}, headers=staff)

    assert forged.status_code == 401
    assert failure.status_code == 401
    assert client.get(f"{API}/images/{image}", headers=staff).json()["review_status"] == "pending"


def test_staff_may_still_look_at_an_image_and_its_download_address(client, staff):
    image = upload(client, staff).json()["images"][0]["id"]

    assert client.get(f"{API}/images/{image}", headers=staff).status_code == 200
    assert client.get(f"{API}/images/{image}/download-url", headers=staff).status_code == 200
