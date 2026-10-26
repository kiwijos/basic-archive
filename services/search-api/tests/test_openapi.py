API = "/api/search"


def test_the_api_describes_itself_under_its_own_prefix_so_it_is_reachable_through_the_ingress(client):
    described = client.get(f"{API}/openapi.json")

    assert described.status_code == 200
    paths = described.json()["paths"]
    assert f"{API}/documents" in paths and f"{API}/subjects" in paths and f"{API}/suggest" in paths and f"{API}/facets" in paths


def test_there_is_a_page_for_reading_that_description(client):
    page = client.get(f"{API}/docs")

    assert page.status_code == 200 and "swagger" in page.text.lower()
    assert f"{API}/openapi.json" in page.text


def test_the_description_does_not_move_with_the_old_unprefixed_address(client):
    assert client.get("/openapi.json").status_code == 404 and client.get("/docs").status_code == 404
