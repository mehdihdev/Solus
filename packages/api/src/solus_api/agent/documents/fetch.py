"""Fetch a PDF from a URL SOL was given (SOLUSDEV-252 P6) — an SSRF surface.

The URL comes from the model, which got it from a page, a repo or a person: it
is untrusted. So: https only; the host is RESOLVED and every address must be
globally routable (no loopback, private, link-local or metadata ranges); at most
three redirects, each re-checked under the same rules; the body is streamed
under a byte cap and must start with the `%PDF-` magic (the bytes, not the header, decide).
Nothing is executed or parsed here — that is `pdf.py`'s job, behind its own caps.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from typing import Final
from urllib.parse import urlsplit

import httpx

from solus_api.agent.documents.pdf import MAX_PDF_BYTES, DocumentError

MAX_REDIRECTS: Final = 3
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
_PDF_MAGIC: Final = b"%PDF-"
_CHUNK: Final = 64 * 1024

Resolver = Callable[[str], Awaitable[Sequence[str]]]


async def _resolve_host(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return [str(info[4][0]) for info in infos]


def _parsed_address(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(raw.split("%", 1)[0])  # strip a v6 zone id
    except ValueError:
        return None


async def _checked_url(url: str, resolver: Resolver) -> str:
    """The URL if it is https to a public host; `DocumentError` otherwise."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise DocumentError("only https URLs can be fetched")
    literal = _parsed_address(parts.hostname)
    # An IP literal IS the answer — asking a resolver about it would let
    # `https://127.0.0.1/` past the guard on any box whose DNS echoes names back.
    addresses: Sequence[str] = [parts.hostname] if literal else await resolver(parts.hostname)
    if not addresses:
        raise DocumentError("host could not be resolved")
    for raw in addresses:
        address = _parsed_address(raw)
        if address is None:
            raise DocumentError("host resolved to an unusable address")
        if not address.is_global:
            raise DocumentError("host resolves to a private or local address")
    return url


async def _read_body(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise DocumentError(f"document exceeds {max_bytes // (1024 * 1024)} MB")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise DocumentError(f"document exceeds {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body.startswith(_PDF_MAGIC):  # the bytes are authoritative over the declared type
        raise DocumentError("the URL did not return a PDF (not a PDF file)")
    return body


async def fetch_pdf(
    url: str,
    *,
    max_bytes: int = MAX_PDF_BYTES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver | None = None,
) -> bytes:
    """The PDF's bytes, or `DocumentError` naming the refusal. `transport` and
    `resolver` exist for tests; production uses the real network and DNS.

    ponytail: the host is checked at resolve time and httpx connects by name, so a
    DNS answer that changes between the two (rebinding) is not pinned. Closing that
    needs a custom transport that connects to the vetted address and sets SNI/Host
    itself — add it when a public deployment fetches from untrusted URLs."""
    resolve = resolver or _resolve_host
    target = await _checked_url(url, resolve)
    async with httpx.AsyncClient(
        transport=transport, timeout=timeout, follow_redirects=False
    ) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                async with client.stream(
                    "GET", target, headers={"accept": "application/pdf"}
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise DocumentError("redirect without a location")
                        target = await _checked_url(str(response.url.join(location)), resolve)
                        continue
                    if response.status_code != 200:
                        raise DocumentError(f"the URL answered HTTP {response.status_code}")
                    return await _read_body(response, max_bytes)
            except httpx.HTTPError as exc:
                raise DocumentError(f"fetch failed ({type(exc).__name__})") from None
    raise DocumentError(f"too many redirects (more than {MAX_REDIRECTS})")


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "MAX_REDIRECTS", "Resolver", "fetch_pdf"]
