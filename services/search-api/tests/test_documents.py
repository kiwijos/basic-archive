from conftest import document

API = "/api/search"


def test_unverified_documents_are_found_by_default_with_verified_false_and_drop_out_when_verified_only(
    client, meili
):
    unchecked = document(title="Maskinläst brev", text="Vega seglade", verified=False)
    checked = document(title="Rättat brev", text="Vega seglade", verified=True, verified_images=1)
    meili.add("documents", unchecked, checked)

    everything = client.get(f"{API}/documents", params={"q": "Vega"}).json()
    assert {hit["id"]: hit["verified"] for hit in everything["hits"]} == {unchecked["id"]: False, checked["id"]: True}

    only = client.get(f"{API}/documents", params={"q": "Vega", "verified_only": "true"}).json()
    assert [hit["id"] for hit in only["hits"]] == [checked["id"]]
