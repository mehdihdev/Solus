+++
title = "Fixing a hub to a shaft: set screws slip, keys fret, clamps and D-shafts hold"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/bearings_shafts/radial-thrust-preload-and-mounting", "corpus:mechanical/fits_tolerances/choosing-fits-bearing-dowel-press"]
further_reading = []
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "DIN 6885 — Drive type fastenings without taper action; parallel keys, keyways, deep pattern", author = "DIN", identifier = "DIN 6885", url = "https://www.din.de/" },
  { title = "Fastener Design Manual (NASA Reference Publication 1228)", author = "Barrett, NASA Lewis Research Center", identifier = "NASA-RP-1228", url = "https://ntrs.nasa.gov/" },
  { title = "Gearheads and shaft-mounted accessories — catalogue mounting notes", author = "maxon", identifier = "", url = "https://www.maxongroup.com/" },
]
+++

The failure: a wheel, pulley, or arm is attached to a motor shaft with a single set screw. It works for the demo, then the robot loses position, the set screw has chewed a groove in the shaft, and the hub now rattles no matter how hard the screw is tightened. A point contact on a round shaft transmits torque by friction over a tiny area, and a reversing load works it loose in minutes.

Options, from worst to best for a robot joint:

- **Set screw on a round shaft** — holds only light, one-directional loads. If used at all, use two at 90° on a flat with thread-locker, and accept a scarred shaft.
- **Set screw on a D-shaft or flat** — the flat turns the point contact into a positive stop against rotation, which is a real improvement; the screw still relaxes and the hub can rock on the flat. Adequate for small hobby motors only.
- **Parallel key and keyway** (DIN 6885 sizes the key to the shaft diameter) — positive torque transmission and the industrial default. The weaknesses: a key needs a machined keyway in both shaft and hub; the hub still needs an axial retention (set screw onto the key, retaining ring, or shoulder); and under reversing torque the key rocks in its slot and **frets**, gradually widening the keyway. A keyed joint under alternating load is a backlash source that grows with time.
- **Clamping (split) hub or collar** — a hub whose bore is closed onto the shaft by screws, gripping the full circumference. No marks, no keyway, infinitely adjustable position, holds well against reversing load, and removable. The standard answer for pulleys, arms, and couplings on smooth shafts. Torque capacity comes from the vendor; it is set by bore size and screw clamping force, so undersized clamps slip silently.
- **Shaft collar with a keyless locking element** (tapered bushings, Ringfeder-style locking assemblies) — the clamping-hub principle scaled to high torque; zero backlash and self-centring.
- **Splines, tapers, and flanged outputs** — when the actuator offers a flange or spline output, use it; it exists because the vendor knows that shaft-plus-set-screw fails.

Whichever method, add a separate **axial** retention (shoulder plus retaining ring, or a clamp collar) rather than asking the torque connection to also hold the hub in place, and check every hub after the first hours of operation — a joint that has begun to slip shows a bright polished band or metal dust at the interface.
