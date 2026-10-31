"""SOLUSDEV-321 P5 — the graph's labels burned into a render before anything reads it (R103).

`annotate_render` draws onto a render what the graph says about it, so the one vision read quotes
facts off the picture instead of guessing them:

- each labelled part's name at its projected bounds: a box, and the name above it;
- a caption band under the picture: a label with no bounds, the net a sheet is about, the view,
  and each labelled part's measured extents from the graph (`render_view` writes them). Face ids
  join it where a renderer exposes them; none does yet.

Every label and caption is graph text, untrusted (CLAUDE.md §7): `drawable_text` reduces it to
printable ASCII on one line, at most `LABEL_CHARS`, so it can only ever become pixels. At most
`MAX_LABELS` labels and `MAX_CAPTIONS` caption lines are drawn.

The picture passes the one image gate (`bridge.service.checked_image`: its magic, its header's
dimensions, its size) before Pillow decodes it.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from solus_api.bridge.service import PIL_FORMATS, ImageRefusedError, checked_image

MAX_LABELS: Final = 16
MAX_CAPTIONS: Final = 8
LABEL_CHARS: Final = 80
LINE_PX: Final = 14
PAD_PX: Final = 6
LABEL_INK: Final = (200, 30, 30)
CAPTION_INK: Final = (20, 20, 20)
PAPER: Final = (255, 255, 255)

type Box = tuple[int, int, int, int]
type Font = ImageFont.ImageFont | ImageFont.FreeTypeFont


@dataclass(frozen=True, slots=True)
class RenderLabel:
    """One part's name, at its bounds in the render (x0, y0, x1, y1 px) when the renderer
    projected them. A label without bounds is drawn as a caption."""

    text: str
    box: Box | None = None


def drawable_text(text: str) -> str:
    """Graph text as only pixels can carry it: printable ASCII on one line, at most
    `LABEL_CHARS`."""
    ascii_text = text.encode("ascii", "replace").decode("ascii")
    printable = "".join(ch if ch.isprintable() else " " for ch in ascii_text)
    return " ".join(printable.split())[:LABEL_CHARS]


def annotate_render(png: bytes, labels: Sequence[RenderLabel], captions: Sequence[str]) -> bytes:
    """`png` with each boxed label at its bounds and a caption band beneath (module docstring),
    as a PNG. `ImageRefusedError` when the picture fails the gate; nothing decodes it before."""
    picture = _decoded(png)
    kept = list(labels[:MAX_LABELS])
    unplaced = [drawable_text(label.text) for label in kept if label.box is None]
    lines = [line for line in (*unplaced, *map(drawable_text, captions)) if line][:MAX_CAPTIONS]
    band = 2 * PAD_PX + LINE_PX * len(lines) if lines else 0
    canvas = Image.new("RGB", (picture.width, picture.height + band), PAPER)
    canvas.paste(picture)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for label in kept:
        if label.box is not None:
            _draw_box(draw, font, label.text, label.box, picture.size)
    for row, line in enumerate(lines):
        position = (PAD_PX, picture.height + PAD_PX + row * LINE_PX)
        draw.text(position, line, fill=CAPTION_INK, font=font)
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _draw_box(
    draw: ImageDraw.ImageDraw, font: Font, text: str, box: Box, size: tuple[int, int]
) -> None:
    """The bounds, clamped to the picture, and the name above them (below, at the top edge) on a
    paper background so it stays legible over the render."""
    width, height = size
    x0, x1 = sorted(min(max(x, 0), width - 1) for x in (box[0], box[2]))
    y0, y1 = sorted(min(max(y, 0), height - 1) for y in (box[1], box[3]))
    draw.rectangle((x0, y0, x1, y1), outline=LABEL_INK, width=2)
    name = drawable_text(text)
    if not name:
        return
    top = y0 - LINE_PX if y0 >= LINE_PX else min(y1 + 2, max(height - LINE_PX, 0))
    left, upper, right, lower = draw.textbbox((x0, top), name, font=font)
    draw.rectangle((left - 1, upper - 1, right + 1, lower + 1), fill=PAPER)
    draw.text((x0, top), name, fill=LABEL_INK, font=font)


def _decoded(png: bytes) -> Image.Image:
    """The picture's pixels, decoded only as the type and at the size the gate read (P5 fix 1, I1):
    another type, or a later header naming another size, is refused before a pixel is allocated."""
    media_type, width, height = checked_image(png)
    try:
        with Image.open(io.BytesIO(png), formats=[PIL_FORMATS[media_type]]) as opened:
            if opened.size != (width, height):
                raise ImageRefusedError(
                    f"the image's headers disagree: {width}x{height} first, "
                    f"{opened.size[0]}x{opened.size[1]} as decoded"
                )
            return opened.convert("RGB")
    except (OSError, Image.DecompressionBombError):
        raise ImageRefusedError("the bytes do not decode as the image they claim to be") from None
