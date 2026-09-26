"""Synthesise the UI sounds and mix them onto the loop, each placed by its measured peak.

Usage: python3 brand/motion/tools/mix.py
Reads audio/loop.wav (beatgrid.py) + audio/cues.json (render.mjs cues); writes audio/mix.wav.
Placement is circular: a sound whose attack starts before t=0 wraps to the loop's end,
so the seam carries no gap or click.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from ffmpeg import ffmpeg
from numpy.typing import NDArray

ROOT = Path(__file__).resolve().parents[1]
SR = 44100
MUSIC_GAIN = 0.8
SFX_GAIN = 0.42
SEAM_FADE_S = 0.006

Float = NDArray[np.float64]
RNG = np.random.default_rng(400)  # fixed seed: the mix is reproducible


def t_axis(seconds: float) -> Float:
    return np.arange(int(seconds * SR)) / SR


def lowpass(x: Float, cutoff: Float | float) -> Float:
    """One-pole lowpass; cutoff may be a per-sample sweep."""
    a = 1 - np.exp(-2 * np.pi * np.broadcast_to(cutoff, x.shape) / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, (xi, ai) in enumerate(zip(x, a, strict=True)):
        acc += ai * (xi - acc)
        y[i] = acc
    return y


def click() -> Float:
    t = t_axis(0.05)
    body = np.sin(2 * np.pi * 2300 * t) * np.exp(-t / 0.006)
    snap = (RNG.standard_normal(len(t)) - lowpass(RNG.standard_normal(len(t)), 3000.0)) * np.exp(
        -t / 0.0015
    )
    return 0.55 * body + 0.35 * snap


def release() -> Float:
    t = t_axis(0.04)
    return 0.35 * np.sin(2 * np.pi * 1700 * t) * np.exp(-t / 0.005)


def tick() -> Float:
    t = t_axis(0.08)
    return (0.5 * np.sin(2 * np.pi * 3100 * t) + 0.12 * np.sin(2 * np.pi * 6200 * t)) * np.exp(
        -t / 0.012
    )


def type_key() -> Float:
    t = t_axis(0.03)
    n = RNG.standard_normal(len(t))
    return 0.5 * (lowpass(n, 5000.0) - lowpass(n, 900.0)) * np.exp(-t / 0.004)


def swish() -> Float:
    t = t_axis(0.26)
    env = np.where(t < 0.13, (t / 0.13) ** 2, np.exp(-(t - 0.13) / 0.035))
    sweep = 600 + 5200 * np.clip(t / 0.13, 0, 1)
    n = RNG.standard_normal(len(t))
    return 0.22 * (lowpass(n, sweep) - lowpass(n, 300.0)) * env


def pop() -> Float:
    t = t_axis(0.12)
    f = 420 + 520 * np.exp(-t / 0.018)
    return 0.6 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.03)


def chime() -> Float:
    t = t_axis(0.5)
    a = np.sin(2 * np.pi * 1318.5 * t) * np.exp(-t / 0.09)
    b = np.zeros_like(t)
    d = int(0.06 * SR)
    b[d:] = np.sin(2 * np.pi * 1975.5 * t[: len(t) - d]) * np.exp(-t[: len(t) - d] / 0.12)
    return 0.22 * (a + b) * np.minimum(1, t / 0.002)


def warn() -> Float:
    t = t_axis(0.3)
    half = t < 0.1
    f = np.where(half, 660.0, 523.25)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
    env = np.where(half, np.exp(-t / 0.05), np.exp(-(t - 0.1) / 0.07)) * np.minimum(1, t / 0.003)
    out: Float = 0.28 * tone * env
    return out


SOUNDS: dict[str, Callable[[], Float]] = {
    "click": click,
    "release": release,
    "tick": tick,
    "type": type_key,
    "swish": swish,
    "pop": pop,
    "chime": chime,
    "warn": warn,
}


def peak_index(x: Float) -> int:
    """Sample where the sound is loudest (1 ms smoothed envelope): that sample lands on the cue."""
    win = int(0.001 * SR)
    env = np.convolve(np.abs(x), np.ones(win) / win, "same")
    return int(np.argmax(env))


def read_wav(path: Path) -> Float:
    raw = ffmpeg("-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-")
    return np.asarray(np.frombuffer(raw, np.float32), dtype=np.float64).reshape(-1, 2)


def main() -> None:
    cues = json.loads((ROOT / "audio" / "cues.json").read_text())
    n = round(float(cues["T"]) * SR)
    music = read_wav(ROOT / "audio" / "loop.wav")[:n]
    music = np.pad(music, ((0, n - len(music)), (0, 0)))
    fade = np.minimum(1, np.minimum(np.arange(n), n - 1 - np.arange(n)) / (SEAM_FADE_S * SR))
    music *= fade[:, None]
    # Soft ending: equal-power fade of the song under the end card (window from the page).
    f0, f1 = (round(float(x) * SR) for x in cues.get("musicFade", [cues["T"], cues["T"]]))
    u = np.clip((np.arange(n) - f0) / max(f1 - f0, 1), 0, 1)
    music *= np.cos(0.5 * np.pi * u)[:, None]

    sfx = np.zeros(n)
    bank = {k: (s := make(), peak_index(s)) for k, make in SOUNDS.items()}
    for cue in cues["cues"]:
        sound, peak = bank[cue["kind"]]
        start = round(float(cue["t"]) * SR) - peak
        sfx[(start + np.arange(len(sound))) % n] += sound  # circular: wraps across the seam
    sfx *= SFX_GAIN / max(np.abs(sfx).max(), 1e-9)

    mix = MUSIC_GAIN * music + sfx[:, None]
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)  # gentle limiter
    out = ROOT / "audio" / "mix.wav"
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes()
    tmp = ROOT / "render" / "mix.s16"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_bytes(pcm)
    ffmpeg("-y", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(tmp), str(out))
    tmp.unlink()
    print(
        f"{len(cues['cues'])} cues mixed → {out.relative_to(ROOT)}  peaks: "
        + ", ".join(f"{k}@{p / SR * 1000:.1f}ms" for k, (_, p) in bank.items())
    )


if __name__ == "__main__":
    main()
