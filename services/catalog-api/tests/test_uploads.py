import hashlib

from support import API, PNG, stored_objects, upload


def test_uploading_an_image_creates_one_document_with_one_image_stored_under_its_id(
    client, staff, s3
):
    response = upload(
        client,
        staff,
        document_type="letter",
        physical_location="Box 12, folder 3",
        description="Order for new rigging",
        rights="PDM",
    )

    assert response.status_code == 201
    document = response.json()
    assert document["title"] == "Letter from the yard"
    assert document["document_type"] == "letter"
    assert document["physical_location"] == "Box 12, folder 3"
    assert document["description"] == "Order for new rigging"
    assert document["created_by"] == "alice"
    [image] = document["images"]
    assert image["document_id"] == document["id"]
    assert image["page_no"] == 1
    assert image["mime"] == "image/png"
    assert image["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert image["original_filename"] == "scan.png"
    assert image["rights"] == "PDM"
    assert image["review_status"] == "pending"
    stored = s3.get_object(Bucket="masters", Key=image["id"])["Body"].read()
    assert stored == PNG


def test_the_real_type_is_read_from_the_bytes_not_the_file_name(client, staff):
    jpeg = b"\xff\xd8\xff\xe0" + b"jpeg body"
    little_endian_tiff = b"II*\x00" + b"tiff body"
    big_endian_tiff = b"MM\x00*" + b"tiff body"

    mimes = [
        upload(client, staff, jpeg, "photo.txt").json()["images"][0]["mime"],
        upload(client, staff, little_endian_tiff, "scan.png").json()["images"][0]["mime"],
        upload(client, staff, big_endian_tiff, "scan.jpg").json()["images"][0]["mime"],
    ]

    assert mimes == ["image/jpeg", "image/tiff", "image/tiff"]


def test_a_file_of_the_wrong_real_type_is_refused_even_with_a_valid_extension(
    client, staff, s3, outbox
):
    pdf_named_as_jpeg = b"%PDF-1.7\n" + b"not an image"
    heic = b"\x00\x00\x00\x18ftypheic" + b"not supported"

    for content, name in ((pdf_named_as_jpeg, "scan.jpg"), (heic, "photo.png"), (b"", "empty.png")):
        response = upload(client, staff, content, name)

        assert response.status_code == 415, name
        assert "TIFF, JPEG and PNG" in response.json()["detail"]
        assert "PDF" in response.json()["detail"]
        assert "HEIC" in response.json()["detail"]
    assert stored_objects(s3) == 0
    assert outbox() == []


def test_a_file_above_the_size_limit_is_refused_with_the_limit_named(new_client, staff, s3):
    small = new_client(max_upload_bytes=100)

    response = upload(small, staff, PNG + b"x" * (101 - len(PNG)))

    assert response.status_code == 413
    assert "100 byte" in response.json()["detail"]
    assert stored_objects(s3) == 0


def test_a_file_exactly_at_the_size_limit_is_accepted(new_client, staff):
    small = new_client(max_upload_bytes=100)

    response = upload(small, staff, PNG + b"x" * (100 - len(PNG)))

    assert response.status_code == 201


def test_when_storage_is_down_the_upload_fails_and_nothing_is_recorded(
    new_client, staff, outbox
):
    broken = new_client(s3_endpoint_url="http://127.0.0.1:1")

    response = upload(broken, staff)

    assert response.status_code == 502
    assert response.json() == {"detail": "Object storage is unavailable"}
    assert outbox() == []


def test_an_upload_needs_a_staff_token_a_title_and_valid_fields(client, staff, s3):
    no_token = client.post(
        f"{API}/documents", data={"title": "x"}, files={"file": ("a.png", PNG)}
    )
    blank_title = upload(client, staff, title="   ")
    bad_rights = upload(client, staff, rights="public")
    inverted = upload(client, staff, date_from="1891-01-01", date_to="1889-01-01")

    assert no_token.status_code == 401
    assert blank_title.status_code == 422
    assert bad_rights.status_code == 422
    assert inverted.status_code == 422
    assert stored_objects(s3) == 0


def test_a_documents_uncertain_date_is_kept_as_written(client, staff):
    response = upload(
        client, staff, date_text="ca 1890", date_from="1889-01-01", date_to="1891-12-31"
    )

    assert response.json()["date"] == {
        "date_text": "ca 1890",
        "date_from": "1889-01-01",
        "date_to": "1891-12-31",
    }
    assert upload(client, staff).json()["date"] is None


def test_blank_form_fields_are_treated_as_absent(client, staff):
    # A browser form sends an empty string for every input the user left alone.
    response = upload(
        client,
        staff,
        document_type="",
        date_text=" ",
        date_from="",
        date_to="",
        physical_location="",
        description="",
    )

    assert response.status_code == 201
    document = response.json()
    assert document["document_type"] is None
    assert document["date"] is None
    assert document["physical_location"] is None
    assert document["description"] is None
