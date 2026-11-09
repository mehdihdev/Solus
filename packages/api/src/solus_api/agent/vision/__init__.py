"""SOLUSDEV-321 P5 — perception: one labelled view per question, read once, checked by the graph.

Renders are data for semantics (ADR-029): SOL looks at a picture to learn how something looks and
where it sits, never to count, never to trace a connection, and never to read a number the graph
states. The modules, in the order a render meets them:

- `render_view` — the SOL tool: the view the question asks for, the cache, the result;
- `renderers` — who draws it: a scene model through the livebench offscreen renderer, else a source
  whose connector declares `Capability.RENDER`;
- `render_annotate` — the graph's labels and measured facts burned into the picture;
- `vision_extract` — the one VISUAL_LOG read of the labelled picture, counted against the turn;
- `vision_postcheck` — the graph's numbers win over the read's.

Vendor-free: tests/test_capability_hygiene.py sweeps this package, so a renderer is picked by what
an entity has, never by a product's name (docs/architecture/sol-depth.md, "Perception").

`body_key` is the one name rule a scene's bodies are matched by. It lives here, importing nothing
heavy, because the livebench offscreen child imports it too (P5 fix 1, M8).
"""

import re


def body_key(name: str) -> str:
    """A name as a scene body is matched by: lower case, each run of anything else one `_`, trimmed
    and at most 128 characters."""
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")[:128]
