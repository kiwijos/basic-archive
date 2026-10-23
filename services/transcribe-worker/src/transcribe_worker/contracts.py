import json
import os
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

# In the image the contracts are copied to /app/contracts; in a checkout they sit at the repo root.
CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR", Path(__file__).resolve().parents[4] / "contracts"))


class ContractViolation(Exception):
    """A message does not follow its contract."""


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((CONTRACTS_DIR / f"{name}.schema.json").read_text()))


def validate(name: str, message: object) -> None:
    """Raise ContractViolation unless the message follows the named contract."""
    try:
        _validator(name).validate(message)
    except ValidationError as error:
        raise ContractViolation(f"{name}: {error.message}") from error
