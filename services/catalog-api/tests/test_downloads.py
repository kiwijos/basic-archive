from urllib.parse import parse_qs, urlparse

import httpx
from test_uploads import API, PNG, upload


def first_image(client, staff, content=PNG):
    return upload(client, staff, content).json()["images"][0]


def test_an_image_can_be_read_by_id(client, staff):
    image = first_image(client, staff)

    read_back = client.get(f"{API}/images/{image['id']}", headers=staff)

    assert read_back.status_code == 200
    assert read_back.json() == image


def test_the_download_address_serves_the_original_bytes(client, staff):
    image = first_image(client, staff)

    address = client.get(f"{API}/images/{image['id']}/download-url", headers=staff)

    assert address.status_code == 200
    assert address.json()["expires_in"] == 300
    assert httpx.get(address.json()["url"]).content == PNG


def test_the_download_address_lifetime_can_be_chosen_within_limits(client, staff):
    image = first_image(client, staff)
    url = f"{API}/images/{image['id']}/download-url"

    assert client.get(url, params={"expires_in": 60}, headers=staff).json()["expires_in"] == 60
    assert client.get(url, params={"expires_in": 0}, headers=staff).status_code == 422
    assert client.get(url, params={"expires_in": 3601}, headers=staff).status_code == 422


def test_the_default_lifetime_of_the_download_address_is_configurable(new_client, staff):
    short = new_client(download_url_seconds=45)
    image = first_image(short, staff)

    address = short.get(f"{API}/images/{image['id']}/download-url", headers=staff)

    assert address.json()["expires_in"] == 45


def test_the_download_address_is_signed_for_exactly_its_stated_lifetime(client, staff):
    image = first_image(client, staff)

    address = client.get(
        f"{API}/images/{image['id']}/download-url", params={"expires_in": 90}, headers=staff
    ).json()

    signed_for = parse_qs(urlparse(address["url"]).query)["X-Amz-Expires"]
    assert signed_for == ["90"] == [str(address["expires_in"])]


def test_images_need_a_staff_token_and_must_exist(client, staff):
    image = first_image(client, staff)
    unknown = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    assert client.get(f"{API}/images/{image['id']}").status_code == 401
    assert client.get(f"{API}/images/{image['id']}/download-url").status_code == 401
    assert client.get(f"{API}/images/{unknown}", headers=staff).status_code == 404
    assert client.get(f"{API}/images/{unknown}/download-url", headers=staff).status_code == 404
