"""SOLUSDEV-321 P4-T3 — the SPICE deck rung 3 runs: a closed grammar over an untrusted netlist
(docs/api/simulation.md §7; R85, R101).

The netlist is the companion's schematic SPICE export, untrusted device output. It never becomes a
directive the simulator executes. `SpiceDeck.parse` reads it line by line, each line stripped:

- **Kept:** element cards whose first letter is R, C, L, V, I, D, Q, M or X, each in one of the
  fixed shapes `SHAPES` gives its letter. Each token is a name, a node, a number with a SPICE
  suffix (`10k`, `4.7u`, `1Meg`), a model, or `DC`/`AC`, from a bounded set of characters. A card
  is re-emitted from its tokens, never as its raw line. A `+` line continues the card before it.
- **Dropped**, never kept and never followed, each listed with its line number:
  - `.title`, because Solus writes its own;
  - `.end`, because Solus appends its own;
  - the schematic's own analysis lines (`.tran`, `.ac`, `.dc`, `.op`, `.noise`, `.tf`), because
    Solus writes the one analysis line;
  - `.include` and `.lib`, because models come only from `hardware/definitions/spice/`.
- **Skipped:** blank lines and `*` comments.
- **Refused**, each with its line number:
  - every other dot line;
  - the command words `codemodel`, `shell` and `source`, and any word starting `wr` (`write`,
    `wrdata`);
  - any other first letter, and a token outside its class;
  - a `+` that continues no kept card;
  - a name or node starting `solus_`, which Solus keeps for its own cards;
  - an element name used twice;
  - content after `.end`;
  - anything past the bounds.

  A refused word is named by its leading letters only, never by the rest of its line. A refusal
  lists the first `MAX_LISTED` lines and counts the rest.

`render` writes the deck, all of it Solus's text, in this order:

1. a fixed title line;
2. the `.model` and `.subckt` definitions the cards name, copied from the seeds. An element whose
   model the seeds lack, or hold as another kind, fails here as "model not found";
3. the kept cards;
4. any cards Solus writes itself (the motor's);
5. the one analysis line;
6. `.end`.

The seeds are Solus-authored, and still each is read through a closed grammar of its own:
`.model` lines, and `.subckt` blocks of element cards. A seed that holds anything else fails
loudly.
"""

from __future__ import annotations

import functools
import math
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from solus_api.hardware.library import DEFINITIONS_DIR
from solus_api.simulation.sim_capability import SimulationRefusedError

#: The bounds of one export.
MAX_NETLIST_BYTES: Final = 256 * 1024
MAX_LINES: Final = 4_000
MAX_CARDS: Final = 2_000
MAX_CARD_CHARS: Final = 1_024
MAX_CARD_TOKENS: Final = 64
#: How many refused or dropped lines a deck lists; the rest are counted, never held.
MAX_LISTED: Final = 32
#: Where the only models a deck may hold come from.
SPICE_DEFINITIONS: Final = DEFINITIONS_DIR / "spice"
TITLE: Final = "solus rung-3 deck"
DROPPED: Final = frozenset(
    {".title", ".end", ".tran", ".ac", ".dc", ".op", ".noise", ".tf", ".include", ".lib"}
)
COMMAND_WORDS: Final = frozenset({"codemodel", "shell", "source"})
#: Names and nodes Solus keeps for the cards it writes itself.
RESERVED: Final = "solus_"
#: The one analysis line: a transient of at most a second and at most `MAX_POINTS` points.
MAX_STOP_S: Final = 1.0
MAX_POINTS: Final = 100_000
MIN_STEP_S: Final = 1e-12

PRINTABLE: Final = re.compile(r"[\x20-\x7e\t]*")
NAME: Final = re.compile(r"[RCLVIDQMX][A-Za-z0-9_]{0,63}", re.IGNORECASE)
NODE: Final = re.compile(r"(?!.*//)[A-Za-z0-9_+\-/.]{1,64}")
VALUE: Final = re.compile(
    r"[+-]?(?:\d{1,15}(?:\.\d{0,15})?|\.\d{1,15})(?:[eE][+-]?\d{1,3})?[A-Za-z]{0,8}"
)
MODEL: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}")
#: How a refused word is named: by its leading letters only.
LEADING: Final = re.compile(r"\.?[a-z]{1,16}")
#: The seeds' own lines.
SEED_MODEL: Final = re.compile(
    r"\.model\s+([a-z0-9_][a-z0-9_.\-]{0,63})\s+(d|npn|pnp|nmos|pmos)"
    r"(?:\s*\((?:\s*[a-z][a-z0-9_]{0,15}\s*=\s*[+-]?[0-9][0-9.e+\-]{0,23}[a-z]{0,8})*\s*\))?",
    re.IGNORECASE,
)
SEED_SUBCKT: Final = re.compile(
    r"\.subckt\s+([a-z0-9_][a-z0-9_.\-]{0,63})((?:\s+[a-z0-9_+\-/.]{1,64}){1,32})", re.IGNORECASE
)

type Part = re.Pattern[str] | str
type Shape = tuple[Part, ...]
TWO: Final[Shape] = (NODE, NODE)
SOURCE: Final[tuple[Shape, ...]] = (
    (*TWO, VALUE),
    (*TWO, "dc", VALUE),
    (*TWO, VALUE, "ac", VALUE),
    (*TWO, VALUE, "ac", VALUE, VALUE),
    (*TWO, "dc", VALUE, "ac", VALUE),
    (*TWO, "dc", VALUE, "ac", VALUE, VALUE),
    (*TWO, "ac", VALUE),
    (*TWO, "ac", VALUE, VALUE),
)
#: The shapes each letter's card may take after its name: nodes, then values, keywords or a model.
SHAPES: Final[dict[str, tuple[Shape, ...]]] = {
    "R": ((*TWO, VALUE),),
    "C": ((*TWO, VALUE),),
    "L": ((*TWO, VALUE),),
    "V": SOURCE,
    "I": SOURCE,
    "D": ((*TWO, MODEL),),
    "Q": ((*TWO, NODE, MODEL), (*TWO, NODE, NODE, MODEL)),
    "M": ((*TWO, NODE, NODE, MODEL),),
    "X": tuple((*([NODE] * pins), MODEL) for pins in range(1, 33)),
}
#: What a model each letter names must be: a `.model` device type, or a subcircuit.
TAKES: Final = {"D": {"D"}, "Q": {"NPN", "PNP"}, "M": {"NMOS", "PMOS"}, "X": {"subckt"}}


class DeckRefusedError(SimulationRefusedError):
    """The export holds lines the closed grammar refuses. `refusals` lists the first `MAX_LISTED` by
    line, and the message counts the rest."""

    def __init__(self, refusals: tuple[tuple[int, str], ...], more: int = 0) -> None:
        self.refusals = refusals
        listed = "; ".join(f"line {number}: {why}" if number else why for number, why in refusals)
        rest = f"; and {more} more" if more else ""
        super().__init__(f"the SPICE export is refused: {listed}{rest}")


class ModelNotFoundError(SimulationRefusedError):
    """A card names a model the definitions do not hold, or hold as another kind."""


@dataclass(frozen=True)
class SpiceCard:
    """One element card as validated tokens, and the line it began on (0 for one Solus writes)."""

    line: int
    tokens: tuple[str, ...]

    @property
    def letter(self) -> str:
        return self.tokens[0][0].upper()

    @property
    def model(self) -> str | None:
        """The model or subcircuit it names, lowercase, for the letters that name one."""
        return self.tokens[-1].lower() if self.letter in TAKES else None

    def text(self) -> str:
        return " ".join(self.tokens)


@dataclass(frozen=True)
class SpiceAnalysis:
    """The one analysis line Solus writes: a transient from rest (`uic`), every `step_s` up to
    `stop_s`, at most a second and `MAX_POINTS` points."""

    step_s: float
    stop_s: float

    def __post_init__(self) -> None:
        finite = math.isfinite(self.step_s) and math.isfinite(self.stop_s)
        if not finite or not MIN_STEP_S <= self.step_s <= self.stop_s <= MAX_STOP_S:
            raise ValueError("a transient needs 1e-12 s <= step <= stop <= 1 s")
        if self.stop_s / self.step_s > MAX_POINTS:
            raise ValueError(f"a transient needs at most {MAX_POINTS:,} points")

    def line(self) -> str:
        return f".tran {self.step_s:.6g} {self.stop_s:.6g} uic"


@dataclass(frozen=True)
class SpiceDefinition:
    """One `.model` or `.subckt` of the seeds. It holds its lowercase name, what it is (a device
    type, or `subckt`), a subcircuit's pins, its lines, and the models its cards name."""

    name: str
    kind: str
    pins: int
    lines: tuple[str, ...]
    uses: tuple[str, ...] = ()


def fits(tokens: list[str], shape: Shape) -> bool:
    """Whether the tokens after a card's name take `shape`, token for token."""
    return len(tokens) == len(shape) and all(
        token.lower() == part if isinstance(part, str) else part.fullmatch(token) is not None
        for token, part in zip(tokens, shape, strict=True)
    )


def leading(word: str) -> str:
    """A refused word as a refusal names it: its leading letters, never the rest of its line."""
    found = LEADING.match(word)
    return found.group(0) if found else "?"


def card_error(tokens: list[str], seen: set[str]) -> str | None:
    """Why an element card is outside the grammar, or None. `seen` holds the names read so far."""
    name = tokens[0]
    if len(tokens) > MAX_CARD_TOKENS or len(" ".join(tokens)) > MAX_CARD_CHARS:
        return f"a card past {MAX_CARD_TOKENS} tokens or {MAX_CARD_CHARS:,} characters"
    if not NAME.fullmatch(name):
        return "the element name is outside the grammar"
    if name[1:].lower().startswith(RESERVED) or any(t.lower().startswith(RESERVED) for t in tokens):
        return f"names starting `{RESERVED}` are Solus's own"
    if name.lower() in seen:
        return "an element name used twice"
    seen.add(name.lower())
    letter = name[0].upper()
    if not any(fits(tokens[1:], shape) for shape in SHAPES[letter]):
        return f"not a {letter} card of the closed grammar"
    return None


@dataclass
class Listed:
    """Lines by number, the first `MAX_LISTED` of them held and the rest only counted."""

    held: list[tuple[int, str]] = field(default_factory=list)
    count: int = 0

    def add(self, number: int, text: str) -> None:
        self.count += 1
        if len(self.held) < MAX_LISTED:
            self.held.append((number, text))


class DeckReader:
    """Reads an export line by line into the cards it keeps, the lines it drops and the lines it
    refuses (module docstring)."""

    def __init__(self) -> None:
        self.cards: list[tuple[int, list[str]]] = []
        self.dropped = Listed()
        self.refused = Listed()
        self.ended = False
        self.open = False

    def read(self, number: int, line: str) -> None:
        if not line or line.startswith("*"):
            return
        why = self.take(number, line)
        if why is not None:
            self.refused.add(number, why)
            self.open = False

    def take(self, number: int, line: str) -> str | None:
        """Keeps, drops or continues one line; returns why it is refused, or None."""
        if not PRINTABLE.fullmatch(line):
            return "a character outside printable ASCII"
        if self.ended:
            return "content after `.end`"
        if line.startswith("+"):
            return self.continued(line[1:].split())
        word = line.split()[0].lower()
        if line.startswith("."):
            return self.directive(number, word)
        if word in COMMAND_WORDS or word.startswith("wr"):
            return f"`{leading(word)}` is refused"
        if word[0].upper() not in SHAPES:
            return "not an element card (R, C, L, V, I, D, Q, M or X)"
        if len(self.cards) >= MAX_CARDS:
            return f"more than {MAX_CARDS:,} element cards"
        self.cards.append((number, line.split()))
        self.open = True
        return None

    def continued(self, tokens: list[str]) -> str | None:
        if not self.open:
            return "a `+` continues no element card"
        self.cards[-1][1].extend(tokens[: MAX_CARD_TOKENS + 1])
        return None

    def directive(self, number: int, word: str) -> str | None:
        if word not in DROPPED:
            return f"`{leading(word)}` is refused"
        self.dropped.add(number, word)
        self.ended = self.ended or word == ".end"
        self.open = False
        return None

    def finish(self) -> SpiceDeck:
        """The deck of the cards that hold to the grammar; `DeckRefusedError` when any line was
        refused."""
        seen: set[str] = set()
        cards: list[SpiceCard] = []
        for number, tokens in self.cards:
            why = card_error(tokens, seen)
            if why is None:
                cards.append(SpiceCard(number, tuple(tokens)))
            else:
                self.refused.add(number, why)
        if self.refused.count:
            listed = tuple(sorted(self.refused.held))
            raise DeckRefusedError(listed, self.refused.count - len(listed))
        return SpiceDeck(tuple(cards), tuple(self.dropped.held), self.dropped.count)


@dataclass(frozen=True)
class SpiceDeck:
    """The element cards the closed grammar kept from an export, and the lines it dropped: the first
    `MAX_LISTED` of them by line, and how many there were."""

    cards: tuple[SpiceCard, ...]
    dropped: tuple[tuple[int, str], ...]
    dropped_count: int = 0

    @classmethod
    def parse(cls, text: str) -> SpiceDeck:
        """The deck of an untrusted export (module docstring). `DeckRefusedError` names each
        refused line."""
        if (
            len(text) > MAX_NETLIST_BYTES
            or len(text.encode("utf-8", "replace")) > MAX_NETLIST_BYTES
        ):
            raise DeckRefusedError(((0, f"the export is over {MAX_NETLIST_BYTES:,} bytes"),))
        lines = text.replace("\r\n", "\n").rstrip("\n").split("\n", MAX_LINES)
        if len(lines) > MAX_LINES:
            raise DeckRefusedError(((0, f"the export is over {MAX_LINES:,} lines"),))
        reader = DeckReader()
        for number, line in enumerate(lines, start=1):
            reader.read(number, line.strip())
        return reader.finish()

    def render(
        self,
        analysis: SpiceAnalysis,
        *,
        extra: tuple[SpiceCard, ...] = (),
        definitions: Mapping[str, SpiceDefinition] | None = None,
    ) -> str:
        """The deck's text (module docstring). `ModelNotFoundError` for a card whose model the
        definitions do not hold, or hold as another kind."""
        catalog = load_definitions() if definitions is None else definitions
        lines = [TITLE]
        lines += [line for found in definitions_for(self.cards, catalog) for line in found.lines]
        lines += [card.text() for card in (*self.cards, *extra)]
        return "\n".join([*lines, analysis.line(), ".end"]) + "\n"


def definition_for(
    card: SpiceCard, name: str, catalog: Mapping[str, SpiceDefinition]
) -> SpiceDefinition:
    """The definition a card names; `ModelNotFoundError` when the seeds lack it, or hold it as
    another kind or with other pins."""
    definition = catalog.get(name)
    where = f"line {card.line}"
    if definition is None:
        raise ModelNotFoundError(
            f"{where}: model `{name}` not found in hardware/definitions/spice/"
        )
    if definition.kind not in TAKES[card.letter]:
        kind = f"`{name}` is a {definition.kind}"
        raise ModelNotFoundError(f"{where}: {kind}, not a model for a {card.letter} card")
    pins = len(card.tokens) - 2
    if card.letter == "X" and pins != definition.pins:
        raise ModelNotFoundError(
            f"{where}: subcircuit `{name}` has {definition.pins} pins, the card {pins}"
        )
    return definition


def definitions_for(
    cards: tuple[SpiceCard, ...], catalog: Mapping[str, SpiceDefinition]
) -> list[SpiceDefinition]:
    """The definitions the cards name, and those their subcircuits name in turn, each once, by
    name."""
    wanted: dict[str, SpiceDefinition] = {}
    for card in cards:
        name = card.model
        if name is not None:
            wanted[name] = definition_for(card, name, catalog)
    pending = [used for definition in wanted.values() for used in definition.uses]
    while pending:
        name = pending.pop()
        if name not in wanted:
            wanted[name] = catalog[name]
            pending.extend(catalog[name].uses)
    return [wanted[name] for name in sorted(wanted)]


class SeedReader:
    """Reads one seed into its definitions, through the seeds' own closed grammar."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.definitions: list[SpiceDefinition] = []
        self.header: tuple[str, int] | None = None
        self.block: list[str] = []
        self.uses: list[str] = []
        self.seen: set[str] = set()

    def read(self, number: int, line: str) -> None:
        if not line or line.startswith("*"):
            return
        why = self.top(line) if self.header is None else self.inside(line)
        if why is not None:
            raise ValueError(f"{self.path.name} line {number}: {why}")

    def top(self, line: str) -> str | None:
        if (model := SEED_MODEL.fullmatch(line)) is not None:
            definition = SpiceDefinition(model[1].lower(), model[2].upper(), 0, (line,))
            self.definitions.append(definition)
            return None
        if (subckt := SEED_SUBCKT.fullmatch(line)) is not None:
            self.header = (subckt[1].lower(), len(subckt[2].split()))
            self.block = [line]
            return None
        return "a seed holds only `.model` lines and `.subckt` blocks of element cards"

    def inside(self, line: str) -> str | None:
        tokens = line.split()
        if tokens[0].lower() == ".ends" and self.header is not None:
            name, pins = self.header
            uses = tuple(dict.fromkeys(self.uses))
            self.definitions.append(
                SpiceDefinition(name, "subckt", pins, (*self.block, line), uses)
            )
            self.header, self.block, self.uses, self.seen = None, [], [], set()
            return None
        if tokens[0][0].upper() not in SHAPES:
            return "a subcircuit holds only element cards"
        why = card_error(tokens, self.seen)
        if why is None:
            self.block.append(" ".join(tokens))
            used = SpiceCard(0, tuple(tokens)).model
            self.uses += [used] if used is not None else []
        return why

    def finish(self) -> list[SpiceDefinition]:
        if self.header is not None:
            raise ValueError(f"{self.path.name}: a `.subckt` without `.ends`")
        return self.definitions


@functools.cache
def load_definitions(root: Path = SPICE_DEFINITIONS) -> Mapping[str, SpiceDefinition]:
    """Every `.model` and `.subckt` in `root/*.lib`, by lowercase name, read once. A seed that holds
    anything else, a name defined twice, or a subcircuit naming a model no seed holds fails loudly
    (`ValueError`)."""
    catalog: dict[str, SpiceDefinition] = {}
    for path in sorted(root.glob("*.lib")):
        reader = SeedReader(path)
        for number, line in enumerate(path.read_text(encoding="ascii").splitlines(), start=1):
            reader.read(number, line.strip())
        for definition in reader.finish():
            if definition.name in catalog:
                raise ValueError(f"{path.name}: `{definition.name}` is defined twice")
            catalog[definition.name] = definition
    for definition in catalog.values():
        missing = [name for name in definition.uses if name not in catalog]
        if missing:
            names = ", ".join(missing)
            raise ValueError(f"subcircuit `{definition.name}` names models no seed holds: {names}")
    return types.MappingProxyType(catalog)
