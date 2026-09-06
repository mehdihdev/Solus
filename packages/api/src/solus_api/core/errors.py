"""Error envelope per API.md §1.4: `{"error": {"code", "message", "details"}}`."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("solus_api")

_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


class APIError(Exception):
    """Domain error carrying the API.md error-envelope fields."""

    def __init__(
        self,
        status_code: int,
        code: str | None = None,
        message: str = "",
        details: list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code or _STATUS_CODES.get(status_code, "error")
        self.message = message or self.code.replace("_", " ")
        self.details = details or []
        self.headers = headers or {}
        super().__init__(self.message)


def error_response(
    status_code: int, code: str, message: str, details: list[Any] | None = None
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or []}}
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_request: Request, exc: APIError) -> JSONResponse:
        response = error_response(exc.status_code, exc.code, exc.message, exc.details)
        for name, value in exc.headers.items():
            response.headers[name] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422, "validation_error", "Request validation failed", list(exc.errors())
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Catch-all so a truly uncaught error still returns the §1.4 envelope
        # instead of FastAPI's default (unenveloped) 500. Log with full context
        # server-side; never leak the exception text to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(500, "internal_error", "Internal server error")
