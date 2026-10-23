import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def name_for_token(names_by_token: dict[str, str], presented: str) -> str | None:
    """The name of whoever owns the presented token, if any."""
    for token, name in names_by_token.items():
        if hmac.compare_digest(token.encode(), presented.encode()):
            return name
    return None


def _caller(request: Request, credentials: HTTPAuthorizationCredentials | None, *kinds: str) -> str | None:
    if credentials is None:
        return None
    for kind in kinds:
        name = name_for_token(getattr(request.app.state, f"{kind}_names_by_token"), credentials.credentials)
        if name is not None:
            return name
    return None


def staff_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """The name of the staff member whose token was presented. Staff tokens only."""
    name = _caller(request, credentials, "staff")
    if name is None:
        raise HTTPException(status_code=401, detail="A valid staff token is required")
    return name


def service_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """The name of the service whose token was presented. Service tokens only: a staff member
    cannot pose as the worker, and the worker cannot do what staff do."""
    name = _caller(request, credentials, "service")
    if name is None:
        raise HTTPException(status_code=401, detail="A valid service token is required")
    return name


def staff_or_service_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """For the few reads both staff and the worker need."""
    name = _caller(request, credentials, "staff", "service")
    if name is None:
        raise HTTPException(status_code=401, detail="A valid token is required")
    return name
