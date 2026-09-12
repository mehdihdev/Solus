"""`research()` — SOL's bounded web-research loop over the vendored Brave fork
(SOLUSDEV-252 P6, docs/architecture/sol-research.md).

One question in, a `ResearchDigest` out: a handful of findings that each CITE the
page they came from, the sources considered, and an honest account of what the
budget cut short. The loop is deliberately dumb — search, rank, read, quote — and
carries no model call of its own; SOL reads the digest and does the reasoning.

Two invariants shape every line here:

* **Everything from the web is DATA.** Titles, descriptions, page snippets and
  URLs are attacker-authored text. Nothing fetched is interpreted as an
  instruction, no fetched text is concatenated into a Solus sentence, and every
  string is length-capped before it enters the digest. The digest leaves through
  `prompt.tool_outcome`, which fences and re-caps it (CLAUDE.md §7).
* **The budget is HARD.** Queries, pages, bytes and wall-clock are all checked
  BEFORE each call and after each payload; the first ceiling hit sets
  `truncated_reason` and ends the loop. A research question can never turn into
  an unbounded crawl or an unbounded bill.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from solus_api.agent.tools.tool import ToolException

#: The two vendored Brave tools this loop drives, by their REMOTE names
#: (`integrations/mcp/brave/allowlist.yaml`). `call_tool` is injected, so the
#: registry name qualification (`brave.<remote>`) is the caller's business.
WEB_SEARCH_TOOL: Final = "brave_web_search"
LLM_CONTEXT_TOOL: Final = "brave_llm_context"

QUESTION_MAX: Final = 400  # Brave's own query ceiling (400 chars / 50 words)
QUOTE_MAX: Final = 300
CLAIM_MAX: Final = 300
TITLE_MAX: Final = 160
MAX_SOURCES: Final = 20
_SEARCH_COUNT: Final = 10

#: A part number: an alphanumeric token carrying at least one digit (OV9281,
#: STM32F407, SN74HC595). Deliberately loose — a false positive only adds one
#: extra query variant, which the budget already bounds.
_PART_TOKEN: Final = re.compile(r"\b(?=[a-z-]*\d)[a-z0-9][a-z0-9-]{3,}\b", re.IGNORECASE)
_PROTOCOLS: Final = frozenset(
    "i2c spi uart can canbus usb ethernet modbus ros ros2 pwm rs485 rs232 i2s mavlink dds".split()
)
_WORD: Final = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)

_DOC_HOST_PREFIXES: Final = ("docs.", "doc.", "developer.", "dev.", "documentation.")
_DOC_HOST_SUFFIXES: Final = ("readthedocs.io", "readthedocs.org", "rtfd.io", "readthedocs.build")
_CODE_HOSTS: Final = frozenset({"github.com", "gitlab.com", "sourceforge.net"})
_ENCYCLOPEDIA: Final = ("wikipedia.org", "wikimedia.org", "fandom.com")
_DOC_PATHS: Final = ("/docs/", "/documentation/", "/datasheet", "/reference/", "/manual")


class ResearchBudget(BaseModel):
    """The hard ceilings for ONE `research()` call. Defaults are the ADR-019
    shape: a research question is a few searches and a few pages, never a crawl."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_queries: int = Field(default=6, ge=1)
    max_pages: int = Field(default=8, ge=1)
    max_bytes: int = Field(default=600_000, ge=1)
    max_seconds: float = Field(default=45.0, gt=0)


class Finding(BaseModel):
    """One cited claim. `quote` is verbatim UNTRUSTED page text, capped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str
    quote: str
    url: str
    title: str


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    title: str
    fetched: bool  # True when page content was actually read, not just listed


class ResearchDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: list[Finding] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    queries_run: int = 0
    pages_fetched: int = 0
    bytes: int = 0
    #: Which ceiling ended the loop: max_queries | max_pages | max_bytes |
    #: max_seconds, or None when the loop finished its plan.
    truncated_reason: str | None = None


CallTool = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
Clock = Callable[[], float]


def rank_url(url: str, vendors: Sequence[str]) -> int:
    """Where a hit sits in reading order — LOWER is better. A small, explicit
    heuristic, not a model: the vendor's own site beats a docs site, which beats
    the vendor's repo, which beats a random page; an encyclopedia is last."""
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    if any(vendor in host for vendor in vendors):
        return 0
    if host.startswith(_DOC_HOST_PREFIXES) or host.endswith(_DOC_HOST_SUFFIXES):
        return 1
    if host in _CODE_HOSTS:
        return 2 if any(vendor in path for vendor in vendors) else 4
    if any(marker in path for marker in _DOC_PATHS):
        return 3
    if host.endswith(_ENCYCLOPEDIA):
        return 9
    return 5


def _vendors(graph_hints: Sequence[str] | None) -> list[str]:
    """Manufacturer-ish tokens from the graph, lowercased. Hints are Solus's own
    graph text, but they are still only used to WEIGHT and to phrase a query."""
    seen: list[str] = []
    for hint in graph_hints or ():
        for word in _WORD.findall(str(hint)[:120]):
            token = word.lower()
            if token.isalpha() and token not in seen:
                seen.append(token)
    return seen[:6]


def _query_variants(question: str, vendors: Sequence[str]) -> list[str]:
    """2-3 phrasings: the question, a docs-seeking variant when it names a part
    or a protocol, and a vendor-scoped one when the graph knows the maker."""
    base = " ".join(question.split())[:QUESTION_MAX]
    variants = [base]
    words = {word.lower() for word in _WORD.findall(base)}
    if words & _PROTOCOLS:
        variants.append(f"{base} documentation")
    elif _PART_TOKEN.search(base):
        variants.append(f"{base} datasheet")
    if vendors:
        variants.append(f"{vendors[0]} {base}")
    out: list[str] = []
    for variant in variants:
        trimmed = variant[:QUESTION_MAX]
        if trimmed not in out:
            out.append(trimmed)
    return out


def _cap(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _search_hits(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    """`(url, title, description)` per web result. `brave_web_search` returns one
    JSON-encoded object per content block (plus a summarizer-key block); anything
    that is not an object with a url is ignored rather than trusted."""
    hits: list[tuple[str, str, str]] = []
    for block in payload.get("content") or ():
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        try:
            entry = json.loads(block.get("text") or "")
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            hits.append(
                (
                    url,
                    _cap(entry.get("title"), TITLE_MAX),
                    _cap(entry.get("description"), CLAIM_MAX),
                )
            )
    return hits


def _context_pages(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    """`(url, title, quote)` per grounded page from `brave_llm_context`."""
    grounding = payload.get("grounding")
    generic = grounding.get("generic") if isinstance(grounding, dict) else None
    pages: list[tuple[str, str, str]] = []
    for entry in generic or ():
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        snippets = [s for s in (entry.get("snippets") or ()) if isinstance(s, str) and s.strip()]
        pages.append(
            (
                url,
                _cap(entry.get("title"), TITLE_MAX),
                _cap(snippets[0] if snippets else "", QUOTE_MAX),
            )
        )
    return pages


def _size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str))


class _Run:
    """The mutable half of one `research()` call: the counters the budget bounds
    and the deduped hits. Split out so each phase stays small and the ceiling
    check lives in exactly ONE place."""

    def __init__(self, budget: ResearchBudget, clock: Clock, vendors: Sequence[str]) -> None:
        self.budget = budget
        self.clock = clock
        self.started = clock()
        self.vendors = vendors
        self.hits: dict[str, tuple[str, str]] = {}  # url -> (title, description)
        self.findings: list[Finding] = []
        self.fetched: set[str] = set()
        self.queries = 0
        self.bytes = 0
        self.reason: str | None = None
        #: Set when the query budget was too small to search every variant. Not
        #: `reason` itself: that would block the read phase before it ran.
        self.plan_trimmed = False

    def ceiling(self) -> str | None:
        """The first ceiling reached, or None. Checked BEFORE every call and
        after every payload, so no ceiling can be overshot by a whole request."""
        if self.queries >= self.budget.max_queries:
            return "max_queries"
        if len(self.fetched) >= self.budget.max_pages:
            return "max_pages"
        if self.bytes >= self.budget.max_bytes:
            return "max_bytes"
        if self.clock() - self.started >= self.budget.max_seconds:
            return "max_seconds"
        return None

    def blocked(self) -> bool:
        self.reason = self.reason or self.ceiling()
        return self.reason is not None

    async def search(self, call_tool: CallTool, variants: Sequence[str]) -> None:
        """Rank-gathering: titles, descriptions and URLs only. A failure here
        propagates — a keyless or unreachable server must say so, not answer
        with an empty digest."""
        for query in variants:
            if self.blocked():
                return
            self.queries += 1
            payload = await call_tool(WEB_SEARCH_TOOL, {"query": query, "count": _SEARCH_COUNT})
            self.bytes += _size(payload)
            for url, title, description in _search_hits(payload):
                self.hits.setdefault(url, (title, description))

    async def read(self, call_tool: CallTool, variants: Sequence[str]) -> None:
        """Page content for the best hits, one finding per page, deduped by URL.
        A failure here is absorbed: the ranked hits are already a real answer."""
        for query in variants:
            if self.blocked():
                return
            self.queries += 1
            try:
                payload = await call_tool(
                    LLM_CONTEXT_TOOL,
                    {
                        "query": query,
                        "maximum_number_of_urls": self.budget.max_pages - len(self.fetched),
                    },
                )
            except ToolException:
                return
            self.bytes += _size(payload)
            for page in _context_pages(payload):
                if len(self.fetched) >= self.budget.max_pages:
                    self.reason = self.reason or "max_pages"
                    return
                self._record(page)

    def _record(self, page: tuple[str, str, str]) -> None:
        url, title, quote = page
        if url in self.fetched:
            return  # dedupe by URL across every query variant
        self.fetched.add(url)
        known_title, description = self.hits.get(url, ("", ""))
        self.hits.setdefault(url, (title, ""))
        if quote:
            self.findings.append(
                Finding(
                    claim=description or title or known_title or url,
                    quote=quote,
                    url=url,
                    title=title or known_title,
                )
            )

    def digest(self) -> ResearchDigest:
        ranked = sorted(
            self.hits.items(), key=lambda item: (rank_url(item[0], self.vendors), item[0])
        )
        findings = sorted(self.findings, key=lambda f: (rank_url(f.url, self.vendors), f.url))
        return ResearchDigest(
            findings=findings,
            sources=[
                Source(url=url, title=title, fetched=url in self.fetched)
                for url, (title, _description) in ranked[:MAX_SOURCES]
            ],
            queries_run=self.queries,
            pages_fetched=len(self.fetched),
            bytes=self.bytes,
            # ONLY a ceiling that actually cut the loop short. A plan that
            # finished having spent its last query is not "truncated".
            truncated_reason=self.reason or ("max_queries" if self.plan_trimmed else None),
        )


async def research(
    question: str,
    *,
    call_tool: CallTool,
    budget: ResearchBudget,
    clock: Clock,
    graph_hints: Sequence[str] | None = None,
) -> ResearchDigest:
    """Search, rank, read, quote — inside `budget`, citing every claim.

    `call_tool(name, args)` is an injected async callable over the registered
    brave tools, raising `ToolException` on failure. `graph_hints` are short
    strings from the project graph (part names, manufacturers); they only weight
    the ranking and add one vendor-scoped query variant.
    """
    run = _Run(budget, clock, _vendors(graph_hints))
    variants = _query_variants(question, run.vendors)
    # Split the query budget in half so gathering can never STARVE reading: a
    # digest of ranked links with no page quotes is not research. Observed live
    # with max_queries=2 — both queries went to search and nothing was read.
    searchable = variants[: max(1, budget.max_queries // 2)]
    run.plan_trimmed = len(searchable) < len(variants)
    await run.search(call_tool, searchable)
    await run.read(call_tool, variants)
    return run.digest()
