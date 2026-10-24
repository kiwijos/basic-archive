"""How well a machine reading matches the text that is really on a page."""

import unicodedata


def _plain(text: str) -> str:
    """Composed letters, with every run of whitespace a single space: where a scan breaks its lines is not a reading error."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def edit_distance(a: str, b: str) -> int:
    """The fewest single-character insertions, deletions and substitutions that turn one text into the other."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def character_accuracy(reference: str, reading: str) -> float:
    """1 minus the share of the reference that had to change to become the reading, never below 0."""
    wanted = _plain(reference)
    if not wanted:
        raise ValueError("there is no reference text to compare with")
    return max(0.0, 1 - edit_distance(wanted, _plain(reading)) / len(wanted))
