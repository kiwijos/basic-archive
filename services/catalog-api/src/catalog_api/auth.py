import hmac
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Caller:
    name: str
    kind: Literal["staff", "service"]


def name_for_token(names_by_token: dict[str, str], presented: str) -> str | None:
    """The name of whoever owns the presented token, if any."""
    for token, name in names_by_token.items():
        if hmac.compare_digest(token.encode(), presented.encode()):
            return name
    return None


def _caller(
    request: Request, credentials: HTTPAuthorizationCredentials | None, *kinds: Literal["staff", "service"]
) -> Caller | None:
    if credentials is None:
        return None
    for kind in kinds:
        name = name_for_token(getattr(request.app.state, f"{kind}_names_by_token"), credentials.credentials)
        if name is not None:
            return Caller(name, kind)
    return None


def any_caller(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Caller:
    """Staff or service, for endpoints that decide what each may do from the request itself."""
    caller = _caller(request, credentials, "staff", "service")
    if caller is None:
        raise HTTPException(status_code=401, detail="A valid token is required")
    return caller


def staff_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """The name of the staff member whose token was presented. Staff tokens only."""
    caller = _caller(request, credentials, "staff")
    if caller is None:
        raise HTTPException(status_code=401, detail="A valid staff token is required")
    return caller.name


def service_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """The name of the service whose token was presented. Service tokens only: a staff member
    cannot pose as the worker, and the worker cannot do what staff do."""
    caller = _caller(request, credentials, "service")
    if caller is None:
        raise HTTPException(status_code=401, detail="A valid service token is required")
    return caller.name


def staff_or_service_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """For the few reads both staff and the worker need."""
    return any_caller(request, credentials).name
