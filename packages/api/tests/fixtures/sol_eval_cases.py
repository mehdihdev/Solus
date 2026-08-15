# SOLUSDEV-130 (SOL-02) — the cross-domain-bug eval set.
#
# A labeled retrieval corpus + queries with EXPECTED citations, served through
# a deterministic W0-07 implementation (`EvalSystems`) that ranks by word
# overlap and honors k — so retrieval-quality scores are reproducible in CI.
# Until SYS-04/ERR-02 land, these scores measure the REASONING layer's pull
# planning and packing against a controlled corpus, not real pgvector quality;
# re-run against the real systems impl when it exists (same Protocol).
from __future__ import annotations

import re
from typing import NamedTuple

from solus_api.agent.fake_systems import FakeSolSystems
from solus_api.agent.interfaces import ErrorHit, RagHit, RetrievalFilter
from solus_api.fingerprint.contract import SourceRef


class LabeledChunk(NamedTuple):
    chunk: str
    connector: str
    ref: str
    solution: str | None = None

    @property
    def citation(self) -> str:
        return f"[{self.connector}:{self.ref}]"


ERROR_CORPUS: list[LabeledChunk] = [
    LabeledChunk(
        "I2C address 0x68 conflict between the IMU and the RTC on the sensor bus",
        "error_store",
        "eval-err-1",
        "Re-strap AD0 high so the IMU moves to 0x69",
    ),
    LabeledChunk(
        "servo PWM jitter causes camera frame drops while the arm is moving",
        "error_store",
        "eval-err-2",
        "Give the servo rail its own regulator and star ground",
    ),
]

DOCUMENT_CORPUS: list[LabeledChunk] = [
    LabeledChunk(
        "OV9281 camera datasheet: global shutter, 120fps at 1280x800",
        "datasheet",
        "ov9281.pdf",
    ),
    LabeledChunk(
        "PCA9685 PWM driver: 25MHz internal oscillator, 12-bit resolution",
        "datasheet",
        "pca9685.pdf",
    ),
    LabeledChunk(
        "camera_node publishes /image_raw at 30Hz over ROS",
        "ros",
        "camera_node",
    ),
    LabeledChunk(
        "LM2596 buck converter: output ripple grows under fast load transients",
        "datasheet",
        "lm2596.pdf",
    ),
]


class EvalCase(NamedTuple):
    case_id: str
    query: str
    expected_citations: frozenset[str]


CASES: list[EvalCase] = [
    EvalCase(
        "eval-cross-domain-camera-servo",
        "camera frame drops while the servo is moving",
        frozenset({"[error_store:eval-err-2]", "[ros:camera_node]"}),
    ),
    EvalCase(
        "eval-i2c-conflict",
        "I2C conflict between the IMU and something on the bus",
        frozenset({"[error_store:eval-err-1]"}),
    ),
    EvalCase(
        "eval-pwm-oscillator",
        "what oscillator does the PWM driver use?",
        frozenset({"[datasheet:pca9685.pdf]"}),
    ),
    EvalCase(
        "eval-runtime-ripple",
        "supply ripple glitch during the run under load",
        frozenset({"[datasheet:lm2596.pdf]"}),
    ),
    # Two expected hits in the SAME feed — the case a naive k=1 must miss.
    EvalCase(
        "eval-two-documents",
        "the camera datasheet specs and the camera_node publish rate",
        frozenset({"[datasheet:ov9281.pdf]", "[ros:camera_node]"}),
    ),
]


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def _overlap(query: str, chunk: str) -> int:
    return len(_words(query) & _words(chunk))


class EvalSystems(FakeSolSystems):
    """W0-07 over the labeled corpus: deterministic word-overlap ranking that
    honors k — the retrieval half of the eval harness."""

    async def get_error_history(
        self, query: str, k: int, filter: RetrievalFilter | None = None
    ) -> list[ErrorHit]:
        ranked = sorted(ERROR_CORPUS, key=lambda c: (-_overlap(query, c.chunk), c.ref))
        return [
            ErrorHit(
                chunk=c.chunk,
                source_ref=SourceRef(source_connector=c.connector, external_ref=c.ref),
                score=float(_overlap(query, c.chunk)),
                solution_text=c.solution,
            )
            for c in ranked[:k]
            if _overlap(query, c.chunk) > 0
        ]

    async def rag_query(
        self, text: str, k: int, filter: RetrievalFilter | None = None
    ) -> list[RagHit]:
        ranked = sorted(DOCUMENT_CORPUS, key=lambda c: (-_overlap(text, c.chunk), c.ref))
        return [
            RagHit(
                chunk=c.chunk,
                source_ref=SourceRef(source_connector=c.connector, external_ref=c.ref),
                score=float(_overlap(text, c.chunk)),
            )
            for c in ranked[:k]
            if _overlap(text, c.chunk) > 0
        ]
