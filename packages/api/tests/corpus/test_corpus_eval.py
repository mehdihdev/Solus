"""CORPUS C2 — the retrieval eval, run in CI on the keyless full-text path.

Thresholds agreed at the Phase 1 gate (2026-09-06): hit@5 ≥ 0.90, domain
purity = 1.00, answer support ≥ 0.85. Questions live in
tests/fixtures/corpus_eval/<domain>.json (AUTHORING.md §7); the corpus is the
SHIPPED content tree, ingested into the test database exactly as a deploy would.
Model-judged answer correctness is the `-m live` twin in test_corpus_eval_live.py.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Final

import pytest
from pydantic import BaseModel, ConfigDict, Field
from solus_api.corpus.chunking import (
    MANIFEST_FILE,
    build_manifest,
    content_root,
    load_content_tree,
    load_release,
    validate_corpus,
)
from solus_api.corpus.domains import route_domains
from solus_api.corpus.enums import TOPIC_DOMAIN, CorpusDomain, Status, Topic
from solus_api.corpus.ingest import ingest_corpus
from solus_api.corpus.retrieval import corpus_hits
from sqlalchemy.ext.asyncio import AsyncSession

FIXTURES: Final = Path(__file__).resolve().parents[1] / "fixtures" / "corpus_eval"
K: Final = 5
MIN_QUESTIONS: Final = 50
HIT_AT_K_THRESHOLD: Final = 0.90
PURITY_THRESHOLD: Final = 1.00
SUPPORT_THRESHOLD: Final = 0.85


class Question(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=3, max_length=80)
    domain: CorpusDomain
    topic: Topic
    question: str = Field(min_length=10, max_length=500)
    gold_chunk_ids: list[str] = Field(min_length=1, max_length=3)
    required_facts: list[str] = Field(min_length=1, max_length=3)
    answer: str = Field(min_length=20, max_length=1500)


def load_questions() -> list[Question]:
    questions: list[Question] = []
    for path in sorted(FIXTURES.glob("*.json")):
        questions.extend(Question.model_validate(item) for item in json.loads(path.read_text()))
    return questions


def _active_ids() -> set[str]:
    return {c.id for c in load_content_tree(content_root()) if c.status is Status.ACTIVE}


# ------------------------------------------------------------ the shipped artifact


def test_shipped_content_tree_validates_and_every_p0_topic_is_covered() -> None:
    root = content_root()
    release = load_release(root)
    chunks = load_content_tree(root)
    validate_corpus(chunks, release)
    covered = {c.topic for c in chunks if c.status is Status.ACTIVE}
    p0 = {
        Topic.FITS_TOLERANCES, Topic.FASTENERS, Topic.MATERIAL_SELECTION,
        Topic.MACHINING_CONSTRAINTS,
        Topic.TRACE_WIDTH_CURRENT, Topic.CLEARANCE_CREEPAGE, Topic.DECOUPLING, Topic.GROUNDING,
        Topic.POWER_DESIGN, Topic.WIRE_GAUGE, Topic.CONNECTOR_SELECTION, Topic.SIGNAL_INTEGRITY,
        Topic.BUS_ADDRESSING, Topic.ANALOG_FRONTEND,
        Topic.EMBEDDED_PATTERNS, Topic.REAL_TIME_CONSTRAINTS, Topic.ROS_CONVENTIONS,
        Topic.BUILD_AND_TOOLCHAIN,
        Topic.POWER_BUDGET, Topic.THERMAL_BUDGET, Topic.SAFETY_INTERLOCKS, Topic.SYSTEM_INTEGRATION,
        Topic.ACTUATOR_SELECTION, Topic.KINEMATICS_BASICS, Topic.SENSOR_FUSION_BASICS,
        Topic.CONTROL_TUNING,
    }  # fmt: skip
    missing = sorted(t.value for t in p0 - covered)
    assert not missing, f"P0 topics with no active chunk (SCOPE.md §4): {missing}"


def test_shipped_manifest_is_current() -> None:
    root = content_root()
    built = build_manifest(load_content_tree(root), load_release(root))
    on_disk = json.loads((root / MANIFEST_FILE).read_text())
    assert on_disk == built, "manifest.json is stale: run `python -m solus_api.corpus manifest`"


# ---------------------------------------------------------------- the eval set


def test_eval_set_is_well_formed() -> None:
    questions = load_questions()
    assert len(questions) >= MIN_QUESTIONS, f"{len(questions)} questions; need {MIN_QUESTIONS}+"
    ids = Counter(q.id for q in questions)
    assert not [i for i, n in ids.items() if n > 1], "duplicate question ids"
    assert {q.domain for q in questions} == set(CorpusDomain), "every domain needs questions"
    active = _active_ids()
    for q in questions:
        assert TOPIC_DOMAIN[q.topic] is q.domain, f"{q.id}: topic not in its domain"
        for gold in q.gold_chunk_ids:
            assert gold in active, f"{q.id}: gold chunk {gold} is not an active chunk"
        assert all(fact == fact.lower() for fact in q.required_facts), f"{q.id}: facts lowercase"


# ------------------------------------------------------------------ the metrics


async def _ingested(db: AsyncSession) -> AsyncSession:
    await ingest_corpus(db, root=content_root(), embed=None)  # CI is keyless by design
    await db.commit()
    return db


def _report(name: str, per_domain: dict[CorpusDomain, list[float]]) -> str:
    rows = [
        f"  {domain.value:<11} {sum(v) / len(v):.2f}  (n={len(v)})"
        for domain, v in sorted(per_domain.items(), key=lambda kv: kv[0].value)
    ]
    return f"{name}:\n" + "\n".join(rows)


async def test_retrieval_hit_rate_and_answer_support_meet_the_thresholds(
    clean_corpus: AsyncSession,
) -> None:
    db = await _ingested(clean_corpus)
    hits_by_domain: dict[CorpusDomain, list[float]] = defaultdict(list)
    support_by_domain: dict[CorpusDomain, list[float]] = defaultdict(list)
    misses: list[str] = []
    for q in load_questions():
        routed = route_domains(q.question)
        domains = None if routed is None else [d.value for d in routed]
        retrieved = await corpus_hits(db, text=q.question, k=K, domains=domains)
        ids = [h.chunk_id for h in retrieved]
        hit = float(any(g in ids for g in q.gold_chunk_ids))
        text = " ".join(h.chunk.lower() for h in retrieved)
        support = float(all(fact in text for fact in q.required_facts))
        hits_by_domain[q.domain].append(hit)
        support_by_domain[q.domain].append(support)
        if not hit or not support:
            misses.append(
                f"{q.id} hit={int(hit)} support={int(support)} routed={domains} got={ids[:3]}"
            )
    all_hits = [v for vs in hits_by_domain.values() for v in vs]
    all_support = [v for vs in support_by_domain.values() for v in vs]
    hit_rate = sum(all_hits) / len(all_hits)
    support_rate = sum(all_support) / len(all_support)
    print(_report("hit@5", hits_by_domain))
    print(_report("answer support", support_by_domain))
    print(f"overall hit@5={hit_rate:.3f} support={support_rate:.3f} n={len(all_hits)}")
    print("misses:\n  " + "\n  ".join(misses) if misses else "misses: none")
    assert hit_rate >= HIT_AT_K_THRESHOLD, f"hit@5 {hit_rate:.3f} < {HIT_AT_K_THRESHOLD}"
    assert support_rate >= SUPPORT_THRESHOLD, f"support {support_rate:.3f} < {SUPPORT_THRESHOLD}"


async def test_a_domain_filtered_query_returns_only_that_domain(
    clean_corpus: AsyncSession,
) -> None:
    db = await _ingested(clean_corpus)
    impure: list[str] = []
    total = 0
    for q in load_questions():
        retrieved = await corpus_hits(db, text=q.question, k=K, domains=[q.domain.value])
        total += 1
        foreign = [h.chunk_id for h in retrieved if h.domain != q.domain.value]
        if foreign:
            impure.append(f"{q.id}: {foreign}")
    purity = 1.0 - len(impure) / total
    print(f"domain purity={purity:.3f} n={total}")
    assert purity >= PURITY_THRESHOLD, "\n".join(impure)


@pytest.mark.parametrize("domain", list(CorpusDomain))
async def test_the_router_never_sends_a_domain_question_to_another_domain_alone(
    domain: CorpusDomain,
) -> None:
    """Precision guard on the deterministic router: for every eval question it
    either names the right domain, several domains, or none — never ONLY a
    wrong one (that would hide the gold chunk behind a wrong filter)."""
    wrong: list[str] = []
    for q in (q for q in load_questions() if q.domain is domain):
        routed = route_domains(q.question)
        if routed is not None and len(routed) == 1 and routed[0] is not domain:
            wrong.append(f"{q.id} → {routed[0].value}")
    assert not wrong, "\n".join(wrong)
