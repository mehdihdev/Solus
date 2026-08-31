"""A scripted Onshape upstream that COUNTS what it is asked (SOLUSDEV-167 P1).

Why this exists: nothing in the product counts an outbound integration call, so
"a repeated read of an unchanged document costs zero API calls" cannot be
asserted — only claimed. This module is the instrument. It ships zero production
lines; the production counter is the quota meter, which has a real consumer.

**Why respx and not an httpx transport.** respx patches *httpcore*'s connection
pools at class level, which is BELOW every seam a connector could route around:
`OnshapeConnector.request`'s retry ladder, `_download_bounded`'s `client.stream`
(which bypasses `request` entirely), and `_token_request`'s own short-lived
client on a different host. A transport injected at `http()` would miss the last
two — exactly the calls the audit found nobody was counting.

**What counts.** Onshape's quota is ANNUAL (2,500/user/year on Free/Standard) and
only 2xx/3xx responses count against it; 4xx/5xx are free. So `Meter.counted` is
the quota number, `Meter.attempts` is every request made (the two diverge under
the 429 retry ladders — their cost is wall-clock and amplification, not quota),
and `Meter.oauth` is tracked in its own column because the token endpoint lives
on a different host and its quota status is UNVERIFIED. Keeping it separate means
that if a live check ever shows Onshape counts it, the correction is reading a
different column rather than re-running anything.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import respx

from .onshape_sample import (
    CURRENT_MICROVERSION,
    DOCUMENT_LIST,
    ELEMENT_LIST,
    PARTS_METADATA,
    SESSION_INFO,
    STEP_EXPORT,
    TRANSLATION_ACTIVE,
    TRANSLATION_DONE,
    TRANSLATION_STARTED,
    WORKSPACE_INFO,
)

API_HOST = "cad.onshape.com"
OAUTH_HOST = "oauth.onshape.com"

#: Path → a stable template name, so a test can name an endpoint without
#: reproducing document/element ids. Order matters: first match wins.
_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sessioninfo", re.compile(r"^/api/users/sessioninfo$")),
    ("microversion", re.compile(r"^/api/v6/documents/d/[^/]+/w/[^/]+/currentmicroversion$")),
    ("elements", re.compile(r"^/api/v6/documents/d/[^/]+/w/[^/]+/elements$")),
    ("externaldata", re.compile(r"^/api/v6/documents/d/[^/]+/externaldata/[^/]+$")),
    (
        "translations_start",
        re.compile(r"^/api/v6/assemblies/d/[^/]+/w/[^/]+/e/[^/]+/translations$"),
    ),
    ("translations_poll", re.compile(r"^/api/v8/translations/[^/]+$")),
    ("parts", re.compile(r"^/api/v6/parts/d/[^/]+/w/[^/]+/e/[^/]+$")),
    ("document_list", re.compile(r"^/api/v6/documents$")),
    ("document", re.compile(r"^/api/v6/documents/[^/]+$")),
    ("oauth_token", re.compile(r"^/oauth/token$")),
)


def route_of(url: httpx.URL) -> str:
    for name, pattern in _ROUTES:
        if pattern.match(url.path):
            return name
    return f"UNROUTED:{url.path}"


@dataclass
class Meter:
    """The quota odometer, read off respx's own call log after the fact.

    `reset()` records an OFFSET rather than clearing respx's list. That is not
    fastidiousness: `respx.models.CallList` subclasses `unittest.mock.Mock`, so
    any misremembered method name (`.reset()`, which does not exist — the list
    method is `.clear()`) silently returns a child mock and does nothing. An
    offset cannot be faked by attribute auto-creation, so a typo here fails
    loudly instead of quietly making every "costs zero calls" assertion true.
    """

    router: respx.Router
    _offset: int = 0

    @property
    def _calls(self) -> list[tuple[httpx.Request, httpx.Response]]:
        seen = list(self.router.calls)[self._offset :]
        return [(c.request, c.response) for c in seen if c.response is not None]

    @property
    def attempts(self) -> int:
        """Every request that left the process for the Onshape API host."""
        return sum(1 for req, _ in self._calls if req.url.host == API_HOST)

    @property
    def counted(self) -> int:
        """The QUOTA number: 2xx/3xx on the API host. 4xx/5xx are free."""
        return sum(
            1
            for req, resp in self._calls
            if req.url.host == API_HOST and 200 <= resp.status_code < 400
        )

    @property
    def oauth(self) -> int:
        """Token-endpoint calls. Different host; quota status UNVERIFIED, so its
        own column rather than folded into `counted`."""
        return sum(1 for req, _ in self._calls if req.url.host == OAUTH_HOST)

    @property
    def by_route(self) -> Counter[str]:
        return Counter(route_of(req.url) for req, _ in self._calls)

    def reset(self) -> None:
        """Start counting from here. See the class docstring for why this is an
        offset and not a clear."""
        self._offset = len(self.router.calls)


@dataclass
class FakeOnshape:
    """One scripted upstream, installed as the catch-all's side effect.

    Three knobs drive every number in the before/after table:
      * `poll_depth`     — how many ACTIVE polls before the translation is DONE.
      * `document_pages` — how many pages the picker walks.
      * `microversion`   — bump it to make the document "change".
    """

    poll_depth: int = 8
    document_pages: int = 1
    microversion: str = str(CURRENT_MICROVERSION["microversion"])

    #: Incremented at the TOP of the handler, BEFORE any await. This is what
    #: makes the concurrency test measure the peak rather than infer it from a
    #: final tally: with a blocked upstream, `entered[route]` is the number of
    #: callers that genuinely reached the network at the same moment.
    entered: Counter[str] = field(default_factory=Counter)
    #: route → gate. A handler awaits its gate before responding.
    gates: dict[str, asyncio.Event] = field(default_factory=dict)
    #: Requests whose path matched no known route. Asserted empty at teardown so
    #: a newly-added endpoint cannot quietly become free.
    unhandled: list[str] = field(default_factory=list)

    _poll_seen: Counter[str] = field(default_factory=Counter)
    _translation_seq: int = 0

    def block_on(self, route: str) -> asyncio.Event:
        """Hold every response for `route` until the returned event is set."""
        gate = asyncio.Event()
        self.gates[route] = gate
        return gate

    def bump_microversion(self, value: str = "999999999999") -> None:
        self.microversion = value

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        route = route_of(request.url)
        self.entered[route] += 1  # BEFORE any await — see the field docstring.
        gate = self.gates.get(route)
        if gate is not None:
            await gate.wait()
        return self._respond(route, request)

    def _respond(self, route: str, request: httpx.Request) -> httpx.Response:
        handler = self._handlers().get(route)
        if handler is None:
            self.unhandled.append(f"{request.method} {request.url.path}")
            return httpx.Response(501, json={"unhandled": request.url.path})
        return handler(request)

    def _handlers(self) -> dict[str, Callable[[httpx.Request], httpx.Response]]:
        """Route → responder. A table rather than an if-ladder so adding an
        endpoint cannot quietly grow the dispatcher's branching."""
        return {
            "sessioninfo": lambda _r: httpx.Response(200, json=SESSION_INFO),
            "oauth_token": lambda _r: httpx.Response(
                200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
            ),
            "microversion": lambda _r: httpx.Response(
                200, json={"microversion": self.microversion}
            ),
            "document": lambda _r: httpx.Response(200, json=WORKSPACE_INFO),
            "document_list": lambda r: httpx.Response(200, json=self._document_page(r)),
            "elements": self._elements,
            "translations_start": self._translation_start,
            "translations_poll": self._translation_poll,
            "externaldata": lambda _r: httpx.Response(200, text=STEP_EXPORT),
            "parts": lambda _r: httpx.Response(200, json=PARTS_METADATA),
        }

    def _elements(self, request: httpx.Request) -> httpx.Response:
        # Onshape filters server-side; honouring it here keeps the target count
        # (and therefore every call number) faithful.
        wanted = request.url.params.get("elementType")
        items = [e for e in ELEMENT_LIST if not wanted or e.get("elementType") == wanted]
        return httpx.Response(200, json=items)

    def _translation_start(self, _request: httpx.Request) -> httpx.Response:
        # A NEW request id per translation, as Onshape does. Reusing one id would
        # let a later export inherit an earlier one's spent poll budget and
        # finish instantly — which silently understates cost.
        self._translation_seq += 1
        return httpx.Response(
            200, json={**TRANSLATION_STARTED, "id": f"translation-req-{self._translation_seq}"}
        )

    def _translation_poll(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path
        self._poll_seen[key] += 1
        done = self._poll_seen[key] > self.poll_depth
        return httpx.Response(200, json=TRANSLATION_DONE if done else TRANSLATION_ACTIVE)

    def _document_page(self, request: httpx.Request) -> dict[str, Any]:
        """`list_selectable` walks pages until one comes back short. Returning a
        FULL page keeps it walking, which is how `document_pages` is honoured."""
        seen = self.entered["document_list"]
        last = seen >= self.document_pages
        items = list(DOCUMENT_LIST["items"])  # type: ignore[arg-type]
        if last:
            items = items[:1]  # a short page ends the walk
        else:
            items = (items * 10)[:20]  # a full page (Onshape caps limit at 20)
        # The `next` link becomes the next request PATH, so it must be a real
        # one or the route regex stops matching and the walk reads as unrouted.
        return {"items": items, "next": None if last else "/api/v6/documents"}
