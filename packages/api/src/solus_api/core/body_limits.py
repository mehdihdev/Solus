"""Body-size pre-check for the SOL message route (SOLUSDEV-252 review M1).

FastAPI reads and parses the JSON body BEFORE any dependency or validator runs,
so `agent/screen.py`'s 3.5 MiB cap only fires after a 500 MB body has been
buffered. This pure-ASGI middleware looks at `Content-Length` alone and answers
`411 length_required` / `413 payload_too_large` (the artifacts router's
wording, docs/api/API.md) before `receive` is ever awaited.

ponytail: scoped to the one route that accepts pixels; widen `_SOL_MESSAGES`
if another JSON route grows a multi-MiB field.
"""

import re

from starlette.types import ASGIApp, Receive, Scope, Send

from solus_api.core.errors import error_response

#: 3.5 MiB of crop + ~2 MiB of context, base64, plus prose and JSON framing.
MAX_SOL_MESSAGE_BODY_BYTES = 6 * 1024 * 1024
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
_SOL_MESSAGES = re.compile(r"^/api/v1/projects/[^/]+/sol/conversations/[^/]+/messages/?$")


def _declared_length(scope: Scope) -> int | None:
    """`Content-Length` as an int, `None` when absent or malformed."""
    for name, value in scope["headers"]:
        if name == b"content-length":
            return int(value) if value.strip().isdigit() else None
    return None


class SolMessageBodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in _BODY_METHODS
            or not _SOL_MESSAGES.match(scope["path"])
        ):
            await self._app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is None:
            response = error_response(
                411, "length_required", "Content-Length header is required for SOL messages"
            )
        elif declared > MAX_SOL_MESSAGE_BODY_BYTES:
            response = error_response(
                413, "payload_too_large", "SOL message exceeds the 6 MiB size limit"
            )
        else:
            await self._app(scope, receive, send)
            return
        await response(scope, receive, send)


__all__ = ["MAX_SOL_MESSAGE_BODY_BYTES", "SolMessageBodyLimit"]
