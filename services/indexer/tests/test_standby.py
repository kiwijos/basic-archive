import signal

import support
from support import event, wait_until
from test_indexing import publish

EVENTS = 12


def start_pair(start_indexer):
    first = start_indexer()
    assert wait_until(first.ready, timeout=30), first.log()
    second = start_indexer()
    assert wait_until(second.ready, timeout=30), second.log()
    return first, second


def test_two_indexers_never_apply_changes_at_the_same_time_so_an_older_view_cannot_overwrite_a_newer_one(
    start_indexer, catalog, broker, meili
):
    start_pair(start_indexer)
    catalog.delay = 0.1
    views = [catalog.put(support.document(title=f"Brev {n}")) for n in range(EVENTS)]

    for view in views:
        publish(broker, event("document", view["id"]))

    assert wait_until(lambda: len(meili.documents("documents")) == EVENTS, timeout=60)
    assert catalog.most_at_once == 1


def test_when_the_indexer_that_is_working_dies_the_other_carries_on_and_no_change_is_lost(
    start_indexer, catalog, broker, meili
):
    first, second = start_pair(start_indexer)
    catalog.delay = 0.1
    views = [catalog.put(support.document(title=f"Brev {n}")) for n in range(EVENTS)]
    for view in views:
        publish(broker, event("document", view["id"]))
    assert wait_until(lambda: len(meili.documents("documents")) >= 2, timeout=30)

    first.process.send_signal(signal.SIGKILL)  # dies mid-work, with a change in hand that it never acknowledged

    assert wait_until(lambda: len(meili.documents("documents")) == EVENTS, timeout=60), second.log()
    assert second.alive()
