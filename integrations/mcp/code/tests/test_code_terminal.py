"""SOLUSDEV-317 — interactive-process terminal text (docs/api/code-command-execution.md
§11.1): escape and control stripping, CR handling, the held partial line, prompt
detection after an answer, and the bounded prompt tail. Pure; no processes."""

from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip

terminal = overlay_module("terminal")
progress = overlay_module("progress")


def _feed(*blocks: bytes) -> tuple[list[str], Any]:
    lines: list[str] = []
    text = terminal.TerminalText(lines.append)
    for block in blocks:
        text.feed(block)
    return lines, text


def test_plain_lines_and_crlf() -> None:
    lines, text = _feed(b"one\r\ntwo\nthr", b"ee\r\n")
    assert lines == ["one\n", "two\n", "three\n"]
    assert text.pending_line == ""


def test_lone_cr_ends_the_line_even_across_reads() -> None:
    lines, text = _feed(b"10%\r20%\r", b"30%\r", b"\ndone")
    assert lines == ["10%\n", "20%\n", "30%\n"]
    assert text.pending_line == "done"


@pytest.mark.parametrize(
    "raw",
    [
        b"\x1b[31mred\x1b[0m\n",
        b"\x1b[?2004hred\x1b[?2004l\n",
        b"\x1b]0;title\x07red\n",
        b"\x1b]8;;http://x\x1b\\red\x1b]8;;\x1b\\\n",
        b"\x1bPdcs-payload\x1b\\red\n",
        b"\x1b(Bred\n",
        b"\x1b=red\n",
        b"r\x08e\x00\x07d\x7f\x1b[K\n",
        "\u009b31mred\n".encode(),
        "\u009d0;t\u009cred\n".encode(),
    ],
)
def test_escape_sequences_and_controls_are_removed(raw: bytes) -> None:
    lines, _ = _feed(raw)
    assert lines == ["red\n"]
    assert all(ch == "\n" or ch == "\t" or ch.isprintable() for ch in "".join(lines))


def test_escape_split_across_reads_is_still_removed() -> None:
    lines, _ = _feed(b"a\x1b", b"[3", b"1mb\x1b]0;x", b"\x07c\n")
    assert lines == ["abc\n"]


def test_tab_is_kept_and_invalid_utf8_is_replaced() -> None:
    lines, _ = _feed(b"a\tb\xff\n")
    assert lines == ["a\tb�\n"]


def test_pending_line_is_capped_at_512() -> None:
    _, text = _feed(b"x" * 600)
    assert text.pending_line == "x" * terminal.PENDING_CHARS


def test_oversized_line_is_suppressed_like_line_output() -> None:
    lines, text = _feed(b"y" * (progress.MAX_LINE + 10), b"tail\nnext\n")
    assert lines == [progress.SUPPRESSED, "next\n"]
    assert text.pending_line == ""


def test_unterminated_osc_does_not_swallow_everything() -> None:
    lines, _ = _feed(b"\x1b]" + b"z" * (terminal.MAX_STRING + 5) + b"\nafter\n")
    assert lines[-1] == "after\n"


def test_finish_flushes_the_partial_line() -> None:
    lines, text = _feed(b"Name: ")
    text.finish()
    assert lines == ["Name: "] and text.pending_line == ""


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Plug in the servo, then press Enter ", True),
        ("PRESS RETURN to go", True),
        ("Press any key", True),
        ("Overwrite? [y/N]", True),
        ("Proceed (Y/n) now", True),
        ("Do you want to continue? ok", True),
        ("Name:", True),
        ("  >  ", True),
        ("Ready?", True),
        ("compiling foo.c", False),
        ("", False),
        ("   ", False),
    ],
)
def test_prompt_patterns(line: str, expected: bool) -> None:
    assert terminal.looks_like_prompt(line) is expected


def test_pending_prompt_and_last_line_prompt() -> None:
    _, text = _feed(b"Plug in the servo, then press Enter ")
    assert text.prompting()
    _, text = _feed(b"Overwrite? [y/N]\n")
    assert text.prompting()
    _, text = _feed(b"building\n")
    assert not text.prompting()


def test_an_answered_prompt_is_not_detected_again() -> None:
    lines, text = _feed(b"Name: ")
    text.mark_answered(3)
    text.feed(b"bob")  # the terminal's echo of the input
    assert not text.prompting()
    text.feed(b"\r\n")  # the echoed Enter ends the answered line
    assert lines == ["Name: bob\n"] and not text.prompting()
    text.feed(b"Age: ")
    assert text.prompting()


def test_new_output_after_an_answer_on_the_same_line_is_a_new_prompt() -> None:
    _, text = _feed(b"Press any key ")
    text.mark_answered(0)
    assert not text.prompting()
    text.feed(b"Again? ")
    assert text.prompting()


def test_prompt_tail_is_bounded_and_clean() -> None:
    previous = [f"line {n}\n" for n in range(8)]
    tail = terminal.prompt_tail(previous, "Name:\t")
    assert tail == "line 3\nline 4\nline 5\nline 6\nline 7\nName: "
    long = terminal.prompt_tail(["z" * 900 + "\n", "w" * 900 + "\n"], "p" * 300)
    assert len(long) == terminal.TAIL_CHARS and long.endswith("p" * 300)
    assert terminal.prompt_tail([], "") == ""


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("", True),
        ("yes", True),
        ("héllo wörld", True),
        ("a" * 1024, True),
        ("a" * 1025, False),
        ("a\nb", False),
        ("a\rb", False),
        ("tab\t", False),
        ("\x1b[A", False),
        ("\x03", False),
        ("\x7f", False),
        (" ", False),
        ("\u009b", False),
    ],
)
def test_input_text_validation(text: str, ok: bool) -> None:
    assert (terminal.input_refusal(text) is None) is ok
    assert terminal.input_refusal(5) is not None
