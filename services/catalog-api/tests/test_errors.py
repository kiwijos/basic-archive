from fastapi.testclient import TestClient

from catalog_api.app import create_app


def test_an_internal_failure_returns_a_plain_error_without_internals(
    make_settings, scratch_database_url
):
    unreachable_url = scratch_database_url.replace(":55432/", ":1/") + "?connect_timeout=1"
    broken = TestClient(
        create_app(make_settings(database_url=unreachable_url)), raise_server_exceptions=False
    )

    response = broken.get(
        "/api/catalog/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        headers={"Authorization": "Bearer alice-token"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    for leak in ("Traceback", "sqlalchemy", "psycopg", "localhost", "archive_scratch"):
        assert leak not in response.text
