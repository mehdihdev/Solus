"""SOLUSDEV-322 P5-T2 (plan §5-4) — units at the evaluator: a simulated joint streams radians, the
real part's envelope is stated in degrees, and the rules must compare in the part's unit. The
evaluator converts a sample whose unit has a known scale to the envelope's (`convert_unit`) and
still drops, once a channel, one whose unit has none.

Helpers are `test_window_evaluator.py`'s (the fake arm in the real database, the counting buffer,
the `_Seen` rule double that keeps every window it is shown)."""

from __future__ import annotations

import logging
import math

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from test_window_evaluator import (
    _LOGGER,
    _arm,
    _CountingBuffer,
    _evaluator,
    _event_time,
    _feed,
    _maker,
    _Seen,
    _session_view,
)


async def test_sim_rad_signal_converts_to_the_part_unit_for_envelopes(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Servo 3's envelope is in deg (the fake arm's channels). Its position arriving in rad — a sim
    joint's unit — reaches the rules as deg, so the deg limits apply; its current arriving in
    `count`, a unit nothing scales to A, is dropped and said once."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    servo = arm.parts[2]
    buffer, seen = _CountingBuffer(), _Seen()
    await _feed(buffer, project, servo, "servo3.position", "rad", [0.5] * 20, start=0.0)
    await _feed(buffer, project, servo, "servo3.current", "count", [1.0] * 20, start=0.0)
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    streams = {"servo3.position": _event_time(0), "servo3.current": _event_time(0)}
    view = _session_view(project, arm, {servo: streams})

    await _evaluator(maker, buffer, rules=(seen,)).tick(view)

    assert seen.windows, "the window with the converted samples was judged"
    positions = seen.windows[-1].samples["servo3.position"]
    assert len(positions) == 20
    assert {sample.unit for sample in positions} == {"deg"}
    assert all(math.isclose(sample.value, math.degrees(0.5)) for sample in positions)
    assert tuple(seen.windows[-1].samples.get("servo3.current", ())) == ()
    dropped = [
        record.getMessage()
        for record in caplog.records
        if "not in their envelope's unit" in record.getMessage()
    ]
    assert len(dropped) == 1 and "servo3.current" in dropped[0]
