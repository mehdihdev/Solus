"""Measure the song's beat grid and cut the 12-bar loop the showcase runs on.

Usage: python3 brand/motion/tools/beatgrid.py
Writes brand/motion/audio/beatgrid.json and brand/motion/audio/loop.wav.

Method: spectral-flux onset envelope -> comb search for tempo + phase ->
downbeats are the beats that carry the section-change crash cymbals.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ffmpeg import ffmpeg
from numpy.typing import NDArray

ROOT = Path(__file__).resolve().parents[1]
SONG = ROOT / "audio" / "brainiac-mixkit-167.mp3"
SR = 44100
HOP = 512
WIN = 2048
BARS = 14
FPS = 60
CRASH_RATIO = 4.0  # >5 kHz energy jump that marks a crash on a downbeat

Float = NDArray[np.float64]


def decode(path: Path) -> Float:
    raw = ffmpeg("-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-")
    return np.frombuffer(raw, np.float32).astype(np.float64)


def onset_envelope(x: Float) -> Float:
    frames = np.lib.stride_tricks.sliding_window_view(x, WIN)[::HOP] * np.hanning(WIN)
    mag = np.log1p(10 * np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(np.diff(mag, axis=0), 0).sum(axis=1)
    flux -= np.convolve(flux, np.ones(16) / 16, "same")
    return np.asarray(np.maximum(flux, 0), dtype=np.float64)


def fit_grid(env: Float) -> tuple[float, float]:
    """Return (period_s, first_beat_s) maximising onset energy on the grid."""
    t = np.arange(len(env)) * HOP / SR
    best = (-1.0, 0.0, 0.0)
    for bpm in np.arange(110.0, 130.0, 0.01):
        period = 60.0 / bpm
        phase = (t % period) / period
        for p0 in np.linspace(0, 1, 120, endpoint=False):
            d = ((phase - p0 + 0.5) % 1) - 0.5
            score = float((env * np.exp(-((d / 0.03) ** 2))).sum())
            if score > best[0]:
                best = (score, period, p0 * period)
    return best[1], best[2]


def hf_jump(x: Float, t: float, span: float = 0.25) -> float:
    n = int(span * SR)
    freqs = np.fft.rfftfreq(n, 1 / SR)

    def band(t0: float) -> float:
        seg = x[int(t0 * SR) : int(t0 * SR) + n]
        if len(seg) < n:
            return 1e-9
        return float(np.abs(np.fft.rfft(seg * np.hanning(n)))[freqs > 5000].sum())

    return band(t) / max(band(t - span), 1e-9)


def downbeat_slot(x: Float, beats: Float, period: float) -> int:
    """Beat-in-bar slot where bar energy jumps most: sections change on downbeats."""
    rms = np.array([np.sqrt(np.mean(x[int(b * SR) : int((b + period) * SR)] ** 2)) for b in beats])
    bar = np.convolve(rms, np.ones(4) / 4, "valid")  # bar[i] = mean rms of beats i..i+3
    rise = np.maximum(bar[4:] - bar[:-4], 0)  # bar starting at i+4 vs the bar before it
    idx = np.arange(4, 4 + len(rise))
    return int(np.argmax([np.sort(rise[idx % 4 == k])[-4:].sum() for k in range(4)]))


def main() -> None:
    x = decode(SONG)
    period, first = fit_grid(onset_envelope(x))
    beats = np.arange(first, len(x) / SR - period, period)
    jumps = np.array([hf_jump(x, b) for b in beats])
    slot = downbeat_slot(x, beats, period)
    downbeats = beats[slot::4]
    crashes = [
        float(b) for b, j in zip(beats[slot::4], jumps[slot::4], strict=True) if j > CRASH_RATIO
    ]
    loop_beats = BARS * 4
    # First crash whose 12-bar window fits and has two more crashes inside it (act breaks).
    start = next(c for c in crashes if sum(c < o < c + loop_beats * period for o in crashes) >= 2)
    frames = round(loop_beats * period * FPS)
    duration = frames / FPS
    grid = {
        "song": SONG.name,
        "bpm": round(60 / period, 3),
        "period": period,
        "downbeats_in_song": [round(float(d), 4) for d in downbeats],
        "crashes_in_song": [round(c, 4) for c in crashes],
        "loop_start_in_song": round(start, 4),
        "loop_frames": frames,
        "loop_duration": duration,
        "act_breaks": [round(c - start, 4) for c in crashes if start <= c < start + duration],
    }
    (ROOT / "audio" / "beatgrid.json").write_text(json.dumps(grid, indent=2) + "\n")
    ffmpeg(
        "-y",
        "-ss",
        f"{start:.4f}",
        "-t",
        f"{duration:.4f}",
        "-i",
        str(SONG),
        "-ar",
        str(SR),
        "-ac",
        "2",
        str(ROOT / "audio" / "loop.wav"),
    )
    print(json.dumps({k: v for k, v in grid.items() if k != "downbeats_in_song"}, indent=2))


if __name__ == "__main__":
    main()
