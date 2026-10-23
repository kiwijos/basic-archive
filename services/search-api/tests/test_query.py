from search_api.query import Search

HEAVY = {"images", "images.text", "text", "relations", "documents", "subjects", "name_details_full"}


def retrieved(scope):
    return set(Search(scope).body()["attributesToRetrieve"])


def test_a_list_search_retrieves_only_what_a_result_shows_not_the_landing_payload():
    documents = retrieved("documents")
    subjects = retrieved("subjects")

    assert {"id", "title", "verified", "verified_images", "image_count", "images.id", "images.page_no"} <= documents
    assert {"id", "entity", "name", "name_details"} <= subjects
    for heavy in ("images", "images.text", "text", "relations", "documents", "subjects"):
        assert heavy not in documents, heavy
        assert heavy not in subjects, heavy


def test_the_facet_only_request_still_asks_for_no_hits():
    assert Search("documents").body(hits=False)["hitsPerPage"] == 0
