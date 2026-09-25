# Solus showcase — motion piece (SOLUSDEV-400)

`solus-showcase.mp4` — 1920×1080, 60 fps, 28.48 s, loops seamlessly. The blue SOL orb is the one shape: it
morphs, never cuts, through the product story on a 14-bar grid at 118 BPM. The UI is the solusforge.com look
(dark surfaces, domain-tinted borders, blue accent) set in IBM Plex, on the site's near-black canvas with its soft blue top glow.

| Bars  | Act                       | What happens                                                                                                                                                                                           |
| ----- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1–4   | One graph                 | Orb → _Connect sources_ → GitHub / KiCad / Onshape / ROS sync → fingerprint match (CAM_v2 · OV9281_IC · camera_node → `camera_module`, 94%) → Robotics Context Model graph                             |
| 5–8   | Catch it before it breaks | Push into the IMU → autocomplete flags an I2C 0x68 conflict → _Ask SOL_ → Guide→Expert toggle → fix `0x68 → 0x60` → loader → check → system proving 42/42                                              |
| 9–12  | Run it                    | Live Bench: sim vs real `motor_current`, anomaly +62%, scrub + spring back to LIVE → Deploy → flash → toast                                                                                            |
| 12–14 | Call to action            | The toast floods into a full-screen navy end card: _The Greatest Robotics Tool You Could Ever Have_ · **Join the waitlist** · solusforge.com → it collapses into the orb, which is frame 1 of the loop |

The acts start on the song's three crash cymbals (bars 1, 5, 9). `storyboard.png` has one still per beat.

## Pipeline

```bash
python3 tools/beatgrid.py            # tempo, downbeats, crash-aligned 12-bar loop → audio/beatgrid.json, audio/loop.wav
node tools/render.mjs beats          # one still per beat (render/beats, render/beats-sheet.png) — review these first
node tools/render.mjs cues           # the page's sound cues → audio/cues.json
node tools/render.mjs frames 6       # 4 subframes per frame (5860 JPEGs, ~1 min with 6 pages)
python3 tools/mix.py                 # synthesised UI sounds placed by measured peak → audio/mix.wav
python3 tools/encode.py              # ffmpeg tmix motion blur + mux → solus-showcase.mp4
```

`render.mjs` needs `playwright-core` (not a repo dependency): `npm i playwright-core` somewhere and set
`PW_CORE=<that>/node_modules/playwright-core`. It uses Playwright's cached headless Chromium unless
`CHROMIUM` points elsewhere. Open `showcase.html?play` to watch it live, `?t=12.5` to freeze a frame,
`?debug` for the bar.beat readout.

## How it's built

- `seek(t)` is the only renderer: every style is a pure function of time. No CSS transitions, no timers,
  no state between frames, which is what makes subframe rendering and the loop exact.
- Springs are closed-form step responses. A value that changes target many times is the sum of one
  spring per change (`track()`), so it stays a pure function of `t`.
- The toggle knob, tab indicator and Sim/Real control are `liquid()`: each edge rides its own spring,
  and the leading edge is faster than the trailing one, so the pill stretches in the direction it moves.
- The scrub handle is direct manipulation: while held, its value is computed from the cursor. On release
  it springs back to LIVE from wherever it was let go, stretching when dragged past the end.
- Springs are damped to 0.94–1.0: motion settles with ≤0.02% overshoot (no bounce).
- The loop ends on the orb shifted by `HOME` (1360, 280), a multiple of the 40 px dot grid, so the last
  frame matches the first (cursor position and speed included).

## Music

"Brainiac" by Alejandro Magaña (A. M.), Mixkit (`audio/brainiac-mixkit-167.mp3`), used under the
[Mixkit License](https://mixkit.co/license/#musicFree) (free for commercial use in projects). The loop
is 56.94 s → 81.35 s of the track. UI sounds are generated in `tools/mix.py`; nothing else is sampled.
