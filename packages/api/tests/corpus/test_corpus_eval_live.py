"""CORPUS C2 — answer correctness, model-judged. `-m live` only; never in CI.

For each eval question: retrieve the top-5 corpus chunks on the real store, ask
a model to answer USING ONLY the fenced chunks (the same containment SOL uses),
then ask a second model call to judge the answer against the fixture's
known-good answer. Pass when ≥ 85 % of judgements are "agrees". Run with:

    SOLUS_LIVE_ANTHROPIC_KEY=… pytest -m live tests/corpus/test_corpus_eval_live.py -s
"""

from __future__ import annotations

import os

import pytest
from solus_api.agent import prompt
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.corpus.chunking import content_root
from solus_api.corpus.domains import route_domains
from solus_api.corpus.ingest import ingest_corpus
from solus_api.corpus.retrieval import corpus_hits
from solus_api.orchestration.enums import Complexity
from solus_api.orchestration.gateway import complete
from solus_api.orchestration.providers import ANTHROPIC_API_KEY_NAME
from sqlalchemy.ext.asyncio import AsyncSession

from corpus.corpus_helpers import RELEASE_TOML  # noqa: F401  (keeps helpers importable)

from .test_corpus_eval import K, load_questions

pytestmark = pytest.mark.live

_KEY = os.environ.get("SOLUS_LIVE_ANTHROPIC_KEY")
CORRECTNESS_THRESHOLD = 0.85
_MAX_QUESTIONS = int(os.environ.get("SOLUS_LIVE_EVAL_MAX", "89"))


@pytest.mark.skipif(not _KEY, reason="SOLUS_LIVE_ANTHROPIC_KEY not set")
async def test_model_answers_from_corpus_agree_with_the_known_good_answers(
    clean_corpus: AsyncSession,
) -> None:
    assert _KEY is not None
    store = InMemorySecretStore()
    await store.put(ANTHROPIC_API_KEY_NAME, _KEY)
    await ingest_corpus(clean_corpus, root=content_root(), embed=None)
    await clean_corpus.commit()

    agreed, judged, disagreements = 0, 0, []
    for q in load_questions()[:_MAX_QUESTIONS]:
        routed = route_domains(q.question)
        domains = None if routed is None else [d.value for d in routed]
        hits = await corpus_hits(clean_corpus, text=q.question, k=K, domains=domains)
        nonce = prompt.new_nonce()
        blocks = "\n".join(
            prompt.data_block(nonce, "context_corpus", {"text": h.chunk, "citation": h.chunk_id})
            for h in hits
        )
        answer = await complete(
            "Answer the engineering question in at most 120 words using ONLY the fenced "
            "reference data below; if the data does not answer it, say so.\n"
            f"Question: {q.question}\n{blocks}",
            secret_store=store,
            complexity=Complexity.STANDARD,
            max_tokens=400,
        )
        verdict = await complete(
            "You are grading an engineering answer. Reply with exactly one word: AGREES if the "
            "candidate answer states the same engineering conclusion as the reference answer "
            "(wording may differ), or DISAGREES if it contradicts it or fails to answer.\n"
            f"Reference answer: {q.answer}\nCandidate answer: {answer.text}",
            secret_store=store,
            complexity=Complexity.TRIVIAL,
            max_tokens=5,
        )
        judged += 1
        if verdict.text.strip().upper().startswith("AGREES"):
            agreed += 1
        else:
            disagreements.append(f"{q.id}: {answer.text[:160]!r}")
    rate = agreed / judged
    print(f"answer correctness={rate:.3f} n={judged}")
    print("disagreements:\n  " + "\n  ".join(disagreements) if disagreements else "none")
    assert rate >= CORRECTNESS_THRESHOLD, f"{rate:.3f} < {CORRECTNESS_THRESHOLD}"
