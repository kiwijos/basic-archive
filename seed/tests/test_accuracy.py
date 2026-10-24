import pytest

from archive_seed.accuracy import character_accuracy, edit_distance


def test_the_edit_distance_is_the_fewest_single_character_changes_between_two_texts():
    assert edit_distance("kitten", "sitting") == 3  # the textbook example: two substitutions and an insertion
    assert edit_distance("", "abc") == 3
    assert edit_distance("abc", "") == 3
    assert edit_distance("same", "same") == 0
    assert edit_distance("flaw", "lawn") == 2


def test_a_perfect_reading_scores_one_and_each_wrong_character_costs_its_share():
    assert character_accuracy("Skeppet gick", "Skeppet gick") == 1.0
    assert character_accuracy("0123456789", "0123456780") == pytest.approx(0.9)  # one wrong of ten
    assert character_accuracy("0123456789", "012345678") == pytest.approx(0.9)  # one missing of ten
    assert character_accuracy("0123456789", "0123456789x") == pytest.approx(0.9)  # one extra of ten


def test_line_breaks_and_spacing_do_not_count_as_errors_because_scans_wrap_lines_their_own_way():
    reference = "Skeppet lämnade Göteborg den 14 mars."
    reading = "Skeppet  lämnade\nGöteborg\n\nden 14   mars. "

    assert character_accuracy(reference, reading) == 1.0


def test_swedish_letters_compare_the_same_however_they_are_encoded():
    composed = "Göteborg Älvsborg Ångare"
    decomposed = "Go\u0308teborg A\u0308lvsborg A\u030angare"

    assert character_accuracy(composed, decomposed) == 1.0


def test_a_reading_that_is_nothing_like_the_text_scores_zero_never_below():
    assert character_accuracy("abcdef", "") == 0.0
    assert character_accuracy("abc", "x" * 50) == 0.0
    assert character_accuracy("a", "zzzzzzzz") == 0.0


def test_there_has_to_be_a_text_to_compare_with():
    with pytest.raises(ValueError):
        character_accuracy("   ", "anything")
