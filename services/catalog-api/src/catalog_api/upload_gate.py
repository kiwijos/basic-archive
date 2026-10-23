import re

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from catalog_api.auth import name_for_token

# The routes that take a file: a new Document, and another page for an existing one.
UPLOAD_PATHS = re.compile(r"^/api/catalog/documents(/[0-9a-fA-F-]{36}/images)?$")

# Room for the form fields and multipart framing around the file itself.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


class UploadGate:
    """Checks who is uploading and how much, from the headers alone, before any of the body is read.

    FastAPI reads a multipart body to a temporary file before it runs dependencies, so a check made
    there comes too late to stop anyone filling the disk.
    """

    def __init__(self, app: ASGIApp, names_by_token: dict[str, str], max_upload_bytes: int):
        self.app = app
        self.names_by_token = names_by_token
        self.max_upload_bytes = max_upload_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and UPLOAD_PATHS.match(scope["path"]):
            refusal = self.refusal(Headers(scope=scope))
            if refusal is not None:
                await refusal(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def refusal(self, headers: Headers) -> JSONResponse | None:
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or name_for_token(self.names_by_token, token) is None:
            return JSONResponse(
                status_code=401, content={"detail": "A valid staff token is required"}
            )
        declared = headers.get("content-length")
        if declared is None or not declared.isdigit():
            return JSONResponse(
                status_code=411, content={"detail": "An upload must declare its Content-Length"}
            )
        if int(declared) > self.max_upload_bytes + MULTIPART_OVERHEAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"The upload is larger than the {self.max_upload_bytes} byte limit"},
            )
        return None
