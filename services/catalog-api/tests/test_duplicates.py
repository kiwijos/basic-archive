from support import API, PNG, stored_objects, upload


def test_a_second_upload_of_identical_bytes_is_flagged_as_a_duplicate(client, staff, s3):
    first = upload(client, staff, title="First copy").json()
    second = upload(client, staff, title="Second copy", filename="other-name.png").json()

    assert first["duplicate_of_image_id"] is None
    assert second["duplicate_of_image_id"] == first["images"][0]["id"]
    assert second["id"] != first["id"]
    assert stored_objects(s3) == 2


def test_different_bytes_are_not_flagged(client, staff):
    upload(client, staff, PNG)

    other = upload(client, staff, PNG + b" and then some")

    assert other.json()["duplicate_of_image_id"] is None
