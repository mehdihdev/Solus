"""Blend the 4 subframes of every frame into one (motion blur) and mux the mix.

Usage: python3 brand/motion/tools/encode.py
Reads render/sub/*.jpg (render.mjs frames) + audio/mix.wav (mix.py); writes solus-showcase.mp4.
tmix averages each run of 4 consecutive subframes; select keeps the run that ends on the
frame's last subframe, so output frame f = mean(subframes 4f .. 4f+3).
"""

from __future__ import annotations

import json
from pathlib import Path

from ffmpeg import ffmpeg

ROOT = Path(__file__).resolve().parents[1]
SUBFRAMES = 4
FPS = 60


def main() -> None:
    frames = json.loads((ROOT / "audio" / "beatgrid.json").read_text())["loop_frames"]
    out = ROOT / "solus-showcase.mp4"
    blur = (
        f"tmix=frames={SUBFRAMES}:weights='1 1 1 1',"
        f"select='eq(mod(n\\,{SUBFRAMES})\\,{SUBFRAMES - 1})',setpts=N/{FPS}/TB,format=yuv420p"
    )
    ffmpeg(
        "-y",
        "-framerate",
        str(FPS * SUBFRAMES),
        "-i",
        str(ROOT / "render" / "sub" / "%06d.jpg"),
        "-i",
        str(ROOT / "audio" / "mix.wav"),
        "-vf",
        blur,
        "-r",
        str(FPS),
        "-frames:v",
        str(frames),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "15",
        "-tune",
        "animation",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    )
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
