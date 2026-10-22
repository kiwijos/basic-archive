import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def name_for_token(names_by_token: dict[str, str], presented: str) -> str | None:
    """The name of the staff member who owns the presented token, if any."""
    for token, name in names_by_token.items():
        if hmac.compare_digest(token.encode(), presented.encode()):
            return name
    return None


def staff_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """Return the name of the staff member whose token was presented."""
    if credentials is not None:
        name = name_for_token(request.app.state.names_by_token, credentials.credentials)
        if name is not None:
            return name
    raise HTTPException(status_code=401, detail="A valid staff token is required")
