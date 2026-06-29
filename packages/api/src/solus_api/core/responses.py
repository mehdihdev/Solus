"""Success envelope per API.md §1.4: `{"data": …, "meta": …?, "links": …?}`."""

from typing import Any


def envelope(
    data: Any,
    meta: dict[str, Any] | None = None,
    links: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"data": data}
    if meta is not None:
        body["meta"] = meta
    if links is not None:
        body["links"] = links
    return body
