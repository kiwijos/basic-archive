from support import API, PNG, upload

WORKER = {"Authorization": "Bearer worker-token"}


def first_image(client, staff, content=PNG, filename="scan.png"):
    return upload(client, staff, content, filename).json()["images"][0]["id"]


def test_the_original_bytes_are_served_with_their_real_type(client, staff):
    image = first_image(client, staff)

    response = client.get(f"{API}/images/{image}/content", headers=staff)

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


def test_the_stored_type_decides_not_the_file_name(client, staff):
    jpeg = b"\xff\xd8\xff\xe0" + b"jpeg body"
    image = first_image(client, staff, jpeg, "looks-like-a-pdf.pdf.png")

    response = client.get(f"{API}/images/{image}/content", headers=staff)

    assert response.headers["content-type"] == "image/jpeg"


def test_the_browser_is_told_not_to_guess_and_not_to_share_the_page(client, staff):
    image = first_image(client, staff)

    headers = client.get(f"{API}/images/{image}/content", headers=staff).headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "private, max-age=300"
    assert headers["content-disposition"] == "inline"  # no file name taken from the upload


def test_the_content_is_for_staff_only_and_the_image_must_exist(client, staff):
    image = first_image(client, staff)
    unknown = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    assert client.get(f"{API}/images/{image}/content").status_code == 401
    assert client.get(f"{API}/images/{image}/content", headers=WORKER).status_code == 401
    assert client.get(f"{API}/images/{unknown}/content", headers=staff).status_code == 404


def test_when_storage_cannot_deliver_the_file_the_answer_is_a_plain_502(client, staff, s3, new_client):
    image = first_image(client, staff)
    cut_off = new_client(s3_endpoint_url="http://127.0.0.1:1")

    response = cut_off.get(f"{API}/images/{image}/content", headers=staff)

    assert response.status_code == 502
    assert response.json() == {"detail": "Object storage is unavailable"}
