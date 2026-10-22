from datetime import date

from pydantic import model_validator
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class UncertainDate:
    """A date as written ("ca 1890") with the earliest and latest dates it could mean."""

    date_text: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def range_is_not_inverted(self) -> "UncertainDate":
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValueError("date_to must not be earlier than date_from")
        return self

    def is_blank(self) -> bool:
        return self.date_text is None and self.date_from is None and self.date_to is None


def present(uncertain: UncertainDate | None) -> UncertainDate | None:
    """Treat an all-empty date as absent, however the database layer happened to load it."""
    return None if uncertain is None or uncertain.is_blank() else uncertain
