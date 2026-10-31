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
  string is masked and then length-capped before it enters the digest. The digest reaches
  the model as one fenced `research` prompt section (`context._research_sections`), which
  masks and caps every field again (CLAUDE.md §7).
* **The budget is HARD.** Queries, pages, bytes and wall-clock are all checked
  BEFORE each call and after each payload; the first ceiling hit sets
  `truncated_reason` and ends the loop. A research question can never turn into
  an unbounded crawl or an unbounded bill.

Since SOLUSDEV-321 P1-T5 the MODEL no longer asks for research — the runner does,
once a turn, when `should_research` fires (an explicit ask, `/web`, or a
part-number-shaped term the planner could not resolve). `ResearchStep` is that
step: the gate, the 7-day `ResearchCache`, the spend admission a model call
passes, ONE synthetic call through the gated dispatcher under the tier's web caps,
the per-call ledger debit (`debit_web_calls`) and the `research_sources` frame.
An unquoted path-like term never leaves the server; a quoted one leaves only when the
person asked; a query that redaction changed is not searched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.agent.modes import DispatchFn
from solus_api.agent.stream import RESEARCH_QUESTION_CAP, RESEARCH_TITLE_CAP, AgentEvent
from solus_api.agent.tools import ToolCall, ToolDescriptor, ToolError, ToolErrorCode, ToolResult
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.tools.untrusted import REDACTED, redact_text
from solus_api.agent.turn_scope import PART_TOKEN, name_tokens
from solus_api.billing.credits import debit_credits
from solus_api.billing.reconciliation import record_failed_debit
from solus_api.connectors.httpcache import within_bound
from solus_api.orchestration.gates import (
    InsufficientCreditsError,
    TrialCapReachedError,
    TrialExpiredError,
    assert_can_spend,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.runtime import AgentRunContext
    from solus_api.agent.turn_budget import TurnBudget
    from solus_api.connectors.httpcache import CacheStore
    from solus_api.orchestration.config import LimitsConfig

logger = logging.getLogger("solus.agent.research")

#: The registered name of the research tool, and the tools only the SERVER drives: they stay
#: registered (dispatch needs them, `GET /sol/tools` lists them) but are never offered to the
#: model (`model_visible`) and a model-proposed call to one is refused (`withhold_server_driven`).
TOOL_NAME: Final = "research"
SERVER_DRIVEN_TOOLS: Final = frozenset({TOOL_NAME})

#: The two vendored Brave tools this loop drives, by their REMOTE names
#: (`integrations/mcp/brave/allowlist.yaml`). `call_tool` is injected, so the
#: registry name qualification (`brave.<remote>`) is the caller's business.
WEB_SEARCH_TOOL: Final = "brave_web_search"
LLM_CONTEXT_TOOL: Final = "brave_llm_context"

# The query and title bounds are defined once, in stream.py, with the frame that is held to them.
QUESTION_MAX: Final = RESEARCH_QUESTION_CAP  # Brave's own query ceiling (400 chars / 50 words)
QUOTE_MAX: Final = 300
CLAIM_MAX: Final = 300
TITLE_MAX: Final = RESEARCH_TITLE_CAP
#: A longer URL is dropped, never cut: a truncated address is a different address.
MAX_URL: Final = 2048
MAX_SOURCES: Final = 20
_SEARCH_COUNT: Final = 10
#: How long a digest answers the same question in the same project.
CACHE_TTL_SECONDS: Final = 7 * 24 * 3600

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
    #: The server-driven shape (P1-T5): exactly `min(max_searches, variants)` searches, then ONE
    #: reading call for up to `max_pages` — so `max_searches + 1` calls at most, with
    #: `max_queries` set to that by the caller. None keeps the loop's own halving of `max_queries`.
    max_searches: int | None = Field(default=None, ge=1)


class Finding(BaseModel):
    """One cited claim. `quote` is verbatim UNTRUSTED page text, capped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str
    quote: str
    url: str
    title: str


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # The bounds the loop already keeps, stated on the model so a digest read back from the cache
    # (a week-old value in a shared store) or from a tool result proves them again.
    url: str = Field(max_length=MAX_URL)
    title: str = Field(max_length=TITLE_MAX)
    fetched: bool  # True when page content was actually read, not just listed


class ResearchDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: list[Finding] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list, max_length=MAX_SOURCES)
    #: Brave API calls made: the searches AND the reading calls. This is the billing count.
    queries_run: int = 0
    #: How many of those calls were searches; the rest read pages.
    searches_run: int = 0
    pages_fetched: int = 0
    bytes: int = 0
    #: Which ceiling ended the loop: max_queries | max_pages | max_bytes |
    #: max_seconds, or None when the loop finished its plan.
    truncated_reason: str | None = None
    #: True when the cache answered: nothing was searched, read or billed this turn.
    cached: bool = False


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
    """`value` on one line, at most `limit` characters. Masked BEFORE it is cut: a credential that
    straddles the cut would leave a prefix too short for any detector to recognise."""
    return " ".join(redact_text(str(value or "")).split())[:limit]


def _web_url(value: object) -> str | None:
    """`value` as a web address, or None: http(s) only and no longer than MAX_URL. The URL is
    untrusted text the desktop shows and may open, so one past the bound is ignored like any
    other malformed hit — never truncated into a different address."""
    if (
        isinstance(value, str)
        and value.startswith(("http://", "https://"))
        and len(value) <= MAX_URL
    ):
        return value
    return None


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
        url = _web_url(entry.get("url"))
        if url is not None:
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
        url = _web_url(entry.get("url"))
        if url is None:
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
        self.searches = 0
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
            self.searches += 1
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
            searches_run=self.searches,
            pages_fetched=len(self.fetched),
            bytes=self.bytes,
            # ONLY a ceiling that actually cut the loop short. A plan that
            # finished having spent its last query is not "truncated".
            truncated_reason=self.reason or ("max_queries" if self.plan_trimmed else None),
        )


def _plan(variants: list[str], budget: ResearchBudget) -> tuple[list[str], list[str]]:
    """The query variants to search and the ones to read.

    Unset `max_searches`: half the query budget searches, so gathering can never STARVE reading
    (a digest of ranked links with no page quotes is not research — observed live with
    max_queries=2, where both queries went to search and nothing was read), and every variant
    may then read. Set: that many searches, then ONE reading call on the question itself."""
    if budget.max_searches is None:
        return variants[: max(1, budget.max_queries // 2)], variants
    return variants[: budget.max_searches], variants[:1]


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
    searchable, readable = _plan(variants, budget)
    run.plan_trimmed = len(searchable) < len(variants)
    await run.search(call_tool, searchable)
    await run.read(call_tool, readable)
    return run.digest()


# --------------------------------------------------------------------------------------------
# SOLUSDEV-321 P1-T5 — the server drives research: the gate, the cache, the ledger, the step.
# --------------------------------------------------------------------------------------------

TriggerReason = Literal["web_command", "explicit_ask", "missing_part"]

#: The person's own words asking for a lookup: `search` or `look up`, as words, any case.
_EXPLICIT_ASK: Final = re.compile(r"\b(?:search|look up)\b", re.IGNORECASE)
#: The composer's `/web <q>`: at the start (leading space allowed), then the query.
_WEB_COMMAND: Final = re.compile(r"\s*/web(?:\s+(.*))?\Z", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class ResearchTrigger:
    """Why a turn researches, and the ONE query that may leave the server for it."""

    query: str
    reason: TriggerReason


def strip_web_command(content: str) -> str | None:
    """The query a `/web <q>` message carries, trimmed — or None when `content` is not that
    command or names no query. The route sets it as the turn's `research_query` and leaves the
    message itself whole, so history reads as the person wrote it."""
    match = _WEB_COMMAND.match(content)
    remainder = (match.group(1) or "").strip() if match else ""
    return remainder or None


def _without_paths(text: str) -> str:
    """`text` on one line, every path-like term cut out: by the scope planner's own classifier
    (`name_tokens`, uncapped — `scope_tokens` keeps eight tokens of 255 characters, so a path past
    either would stay), then every token that holds a backslash, because that classifier reads `/`
    only (a drive or UNC path, even one with a space in it). A path names the person's machine
    and has nothing to search for."""
    kept, at = [], 0
    for start, token, shape in name_tokens(text):
        if shape == "path":
            kept.append(text[at:start])
            at = start + len(token)
    kept.append(text[at:])
    return " ".join(word for word in " ".join(kept).split() if "\\" not in word)


def _outbound(raw: str) -> str | None:
    """`raw` as the one query that may leave the server, or None when nothing worth asking or
    safe to send is left. Paths are cut out; the rest is redacted BEFORE it is cut to Brave's
    bound (a secret straddling it would leave a prefix no detector could see); a query that
    redaction changed or that carries a mask is dropped: `[REDACTED]` is no search, nor billed."""
    text = _without_paths(raw)
    query = redact_text(text)[:QUESTION_MAX]
    return query if query and query == text[:QUESTION_MAX] and REDACTED not in query else None


def _ask(message: str) -> str | None:
    """What the person wrote as the ask: the message from their `search` / `look up` to the end
    (paths cut out), or None when nothing but punctuation follows the verb."""
    match = _EXPLICIT_ASK.search(text := _without_paths(message))
    return text[match.start() :] if match and re.search(r"\w", text[match.end() :]) else None


def should_research(
    message: str, missing: Sequence[tuple[str, str]], *, research_query: str | None
) -> ResearchTrigger | None:
    """Whether this turn researches the web, and with what query (pure). In order: the `/web`
    remainder; an explicit ask, from its verb to the end of the message; the first term the
    planner could not resolve that is itself part-number shaped (`missing` is
    `TurnScope.missing`). `_outbound` builds every query: a path never leaves the server, a
    quoted term only on the first two (the person chose to send their words), an automatic query
    is one bare part number redaction left unchanged. A source with no query falls through."""
    part = next(
        (term for term, shape in missing if shape == "part_token" and PART_TOKEN.fullmatch(term)),
        None,
    )
    sources: list[tuple[TriggerReason, str | None]] = [
        ("web_command", research_query),
        ("explicit_ask", _ask(message)),
        ("missing_part", part),
    ]
    for reason, raw in sources:
        query = _outbound(raw) if raw else None
        if query:
            return ResearchTrigger(query=query, reason=reason)
    return None


class ResearchCache:
    """Digests in the shared store (Redis when there is one), per project and question, for
    a week: `solus:research:<project>:<sha1(normalised question)>`. A store that fails, or that
    holds another deploy's shape, is a MISS — the cache never fails a turn."""

    def __init__(self, store: CacheStore, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self._store = store
        self._ttl = ttl_seconds

    @staticmethod
    def key(project_id: UUID, question: str) -> str:
        normalised = " ".join(question.casefold().split())
        digest = hashlib.sha1(normalised.encode(), usedforsecurity=False).hexdigest()
        return f"solus:research:{project_id}:{digest}"

    async def get(self, project_id: UUID, question: str) -> ResearchDigest | None:
        try:
            raw = await within_bound(self._store.get(self.key(project_id, question)))
        except Exception as exc:  # a down or stalled (M13) cache is a miss, not a failed turn
            logger.warning("research cache read failed (%s); searching", type(exc).__name__)
            return None
        if raw is None:
            return None
        try:
            return ResearchDigest.model_validate_json(raw).model_copy(update={"cached": True})
        except ValidationError:  # another deploy's shape, or past the bounds: search again
            logger.debug("research cache holds a digest of another shape; searching")
            return None

    async def put(self, project_id: UUID, question: str, digest: ResearchDigest) -> None:
        if not (digest.sources or digest.findings):
            return  # nothing found is not worth a week of repeating it
        try:
            await within_bound(
                self._store.set(self.key(project_id, question), digest.model_dump_json(), self._ttl)
            )
        except Exception as exc:
            logger.warning("research cache write failed (%s)", type(exc).__name__)


async def _debit_one(
    session: AsyncSession, user_id: UUID, credits: int, key: str, attrs: dict[str, Any]
) -> int:
    """One call's debit (1 applied, 0 a replay). The call has already been made and paid for, so
    a failed write is deferred to the billing reconciliation sweep, never raised into the turn."""
    where = f"key={key} user_id={user_id} credits={credits}"
    try:
        result = await debit_credits(session, user_id, credits, idempotency_key=key, attrs=attrs)
        return int(result.applied)
    except Exception as exc:
        logger.error(
            "web debit failed; deferring to reconciliation %s (%s)", where, type(exc).__name__
        )
    try:
        await session.rollback()
        await record_failed_debit(session, user_id, credits, idempotency_key=key, attrs=attrs)
    except Exception as exc:
        logger.error("could not record the pending web debit %s (%s)", where, type(exc).__name__)
    return 0


async def debit_web_calls(
    session: AsyncSession,
    user_id: UUID,
    digest: ResearchDigest,
    *,
    call_id: str,
    turn_id: UUID,
    project_id: UUID,
    credits_per_call: int,
) -> int:
    """One ledger row per Brave API call `digest` records — the first `searches_run` are
    searches, the rest page-reading calls — each `credits_per_call` (models.yaml
    `cost.web_call_credits`; zero still writes its row). Keyed `web:<call_id>:<n>`, so replaying
    a turn's debits applies nothing twice. Returns how many rows were applied."""
    applied = 0
    for n in range(digest.queries_run):
        attrs = {
            "purpose": "web",
            "kind": "search" if n < digest.searches_run else "context",
            "project_id": str(project_id),
            "turn_id": str(turn_id),
        }
        applied += await _debit_one(session, user_id, credits_per_call, f"web:{call_id}:{n}", attrs)
    return applied


def model_visible(tools: Sequence[ToolDescriptor]) -> tuple[ToolDescriptor, ...]:
    """The descriptors the MODEL is offered: every tool but the ones only the server drives."""
    return tuple(tool for tool in tools if tool.name not in SERVER_DRIVEN_TOOLS)


def withhold_server_driven(dispatch: DispatchFn) -> DispatchFn:
    """`dispatch` as the model's proposed calls see it: a server-driven tool is answered like any
    unknown name — never run, whatever the model was shown or imitated from history — so the
    model cannot hand the web a quoted or path-like token the gate keeps on the server."""

    async def model_dispatch(call: ToolCall) -> ToolResult:
        if call.tool in SERVER_DRIVEN_TOOLS:
            error = ToolError(
                code=ToolErrorCode.NOT_FOUND,
                message=f"No tool named {call.tool!r}",
                retryable=False,
            )
            return ToolResult.failure(call.call_id, error)
        return await dispatch(call)

    return model_dispatch


def _digest_of(result: ToolResult) -> ResearchDigest | None:
    """The digest a research result carries, or None for a failure or a value of another shape."""
    if not result.ok or result.value is None:
        return None
    try:
        return ResearchDigest.model_validate(result.value)
    except ValidationError:
        return None


@dataclass(frozen=True, slots=True)
class _Who:
    """A signed-in user and the sessionmaker their ledger is written through."""

    user_id: UUID
    sessionmaker: async_sessionmaker[AsyncSession]


class ResearchStep:
    """ONE turn's server-driven web research (SOLUSDEV-321 P1-T5).

    The runner builds it for a turn that reaches the model; `events()` streams the frames and
    leaves what it found in `digest`, for the prompt. With a trigger and a registered research
    tool it makes ONE call — `tool_call`, `tool_result`, `research_sources` — through
    `ctx.dispatch`, the gated dispatcher a model-proposed call uses (CLAUDE.md §7). The cache
    answers first: no admission, no web call, no debit. A miss is admitted like a model call (this
    step runs before the gateway has admitted anything; a refusal is a failed `tool_result`),
    runs under the tier's web caps, is cached and debited per Brave call, and counts against the
    turn's budget. A failed lookup is a failed `tool_result`; the turn goes on without a digest.
    A turn with no signed-in user, or whose prompt Solus wrote (`research_allowed` false), does
    not research."""

    def __init__(
        self,
        ctx: AgentRunContext,
        *,
        missing: Sequence[tuple[str, str]],
        budget: TurnBudget,
        limits: LimitsConfig,
        credits_per_call: int,
    ) -> None:
        self._ctx = ctx
        self._missing = missing
        self._budget = budget
        self._limits = limits
        self._credits = credits_per_call
        user, maker = ctx.user_id, ctx.sessionmaker
        self._who = _Who(user, maker) if user and maker else None
        self.digest: ResearchDigest | None = None

    def _trigger(self) -> ResearchTrigger | None:
        ctx = self._ctx
        if not ctx.research_allowed or not any(tool.name == TOOL_NAME for tool in ctx.tools):
            return None  # not the person's words, or no web tools: nothing to drive or to show
        trigger = should_research(ctx.prompt, self._missing, research_query=ctx.research_query)
        if trigger is not None and self._who is None:
            logger.info(
                "web research skipped: the turn has no user identity turn_id=%s", ctx.turn_id
            )
            return None  # no one to admit or to bill: the step does not run, and shows nothing
        return trigger

    async def events(self) -> AsyncIterator[AgentEvent]:
        trigger, who = self._trigger(), self._who
        if trigger is None or who is None:
            return
        limits = self._budget.limits
        args = {
            "question": trigger.query,
            "max_searches": limits.web_searches,
            "max_pages": limits.web_fetches,
        }
        call = ToolCall(tool=TOOL_NAME, args=args)
        yield AgentEvent.tool_call(call)
        result, digest = await self._resolve(call, trigger, who)
        self._budget.note_tool_calls(1)
        yield AgentEvent.tool_result(result)
        if digest is None:
            # ponytail: a lookup that fails after an earlier search succeeded is not billed or
            # counted — the loop returns no partial digest to read the calls from.
            return
        self.digest = digest
        searches, pages = (0, 0) if digest.cached else (digest.searches_run, digest.pages_fetched)
        self._budget.note_web(searches, pages)
        logger.info(
            "web research reason=%s cached=%s searches=%d pages=%d turn_id=%s user_id=%s "
            "project_id=%s",
            trigger.reason,
            digest.cached,
            searches,
            pages,
            self._ctx.turn_id,
            self._ctx.user_id,
            self._ctx.project_id,
        )
        yield AgentEvent.research_sources(
            call_id=call.call_id,
            question=trigger.query,
            cached=digest.cached,
            searches=searches,
            pages=pages,
            sources=[source.model_dump() for source in digest.sources],
        )

    async def _resolve(
        self, call: ToolCall, trigger: ResearchTrigger, who: _Who
    ) -> tuple[ToolResult, ResearchDigest | None]:
        """The cached digest as a result; else, for a user who may spend, the dispatched call's —
        cached and billed. A refused call is a failed result and nothing else."""
        ctx = self._ctx
        cache = ctx.research_cache
        hit = await cache.get(ctx.project_id, trigger.query) if cache is not None else None
        if hit is not None:
            return ToolResult.success(call.call_id, hit.model_dump(mode="json")), hit
        refusal = await self._refusal(call, who)
        if refusal is not None:
            return refusal, None
        result = await ctx.dispatch(call)
        digest = _digest_of(result)
        if digest is not None:
            # Before the frames: a stream the client closes after the result must not make
            # the calls it already caused free.
            await self._bill(call.call_id, digest, who)
            if cache is not None:
                await cache.put(ctx.project_id, trigger.query, digest)
        return result, digest

    async def _refusal(self, call: ToolCall, who: _Who) -> ToolResult | None:
        """The failed result for a call this user may not spend on, else None: the gate a model
        call passes (`assert_can_spend`), run BEFORE the first paid web call, since nothing else
        has admitted this turn yet."""
        try:
            async with who.sessionmaker() as session:
                await assert_can_spend(who.user_id, session=session, limits=self._limits)
        except (TrialCapReachedError, TrialExpiredError, InsufficientCreditsError) as exc:
            logger.info(
                "web research refused reason=%s turn_id=%s user_id=%s",
                type(exc).__name__,
                self._ctx.turn_id,
                who.user_id,
            )
            error = ToolError(code=ToolErrorCode.UNAUTHORIZED, message=str(exc), retryable=False)
            return ToolResult.failure(call.call_id, error)
        return None

    async def _bill(self, call_id: str, digest: ResearchDigest, who: _Who) -> None:
        async with who.sessionmaker() as session:
            await debit_web_calls(
                session,
                who.user_id,
                digest,
                call_id=call_id,
                turn_id=self._ctx.turn_id,
                project_id=self._ctx.project_id,
                credits_per_call=self._credits,
            )
