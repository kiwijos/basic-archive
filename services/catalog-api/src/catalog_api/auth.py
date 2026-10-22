import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def staff_name(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """Return the name of the staff member whose token was presented."""
    if credentials is not None:
        for token, name in request.app.state.names_by_token.items():
            if hmac.compare_digest(token.encode(), credentials.credentials.encode()):
                return name
    raise HTTPException(status_code=401, detail="A valid staff token is required")
