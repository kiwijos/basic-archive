from support import API

MULTIPART = {"content-type": "multipart/form-data; boundary=x"}


def test_an_upload_without_a_token_is_refused_before_its_body_is_read(client):
    # The body is not valid multipart: only a check made before reading it can answer 401.
    response = client.post(f"{API}/documents", content=b"not multipart " * 10, headers=MULTIPART)

    assert response.status_code == 401


def test_an_upload_with_the_wrong_token_is_refused_before_its_body_is_read(client):
    response = client.post(
        f"{API}/documents",
        content=b"not multipart",
        headers={**MULTIPART, "Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_an_oversized_upload_is_refused_from_its_declared_length(new_client, staff):
    small = new_client(max_upload_bytes=1000)
    over_the_limit_with_room_for_multipart = b"x" * (1024 * 1024 + 2000)

    response = small.post(
        f"{API}/documents",
        content=over_the_limit_with_room_for_multipart,
        headers={**MULTIPART, **staff},
    )

    assert response.status_code == 413
    assert "1000 byte" in response.json()["detail"]


def test_an_upload_that_does_not_declare_its_length_is_refused(client, staff):
    def streamed():
        yield b"--x--"

    response = client.post(
        f"{API}/documents", content=streamed(), headers={**MULTIPART, **staff}
    )

    assert response.status_code == 411


def test_the_gate_applies_only_to_uploads(client, staff):
    assert client.get(f"{API}/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301").status_code == 401
    assert client.post(f"{API}/ships", json={"name": "Vega"}, headers=staff).status_code == 201
