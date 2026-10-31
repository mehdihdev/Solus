"""SOLUSDEV-321 P1-T5 — how a turn's one web query is built (`should_research`, pure).

Three sources, in order: the composer's `/web <q>`, an explicit ask (`search` / `look up`, from its
verb to the end of the message) and the first part-number-shaped term the planner could not
resolve. One rule builds every query: a path-like term never leaves the server (the planner's
classifier, plus every token that holds a backslash), a quoted term leaves only on the first two,
the text is redacted BEFORE it is cut to 400 characters, and a query that is empty, carries a mask
or differs from what was typed is dropped. No database, no model, nothing scripted.
"""

from __future__ import annotations

import string

from solus_api.agent import turn_scope
from solus_api.agent.research import (
    QUESTION_MAX,
    ResearchTrigger,
    should_research,
    strip_web_command,
)
from test_research_gating import ASK, QUERY

#: 41 characters from the entropic charset with 41 distinct ones: `redact_text` masks it whole.
HIGH_ENTROPY = "q" + string.ascii_letters[:30] + string.digits


def test_fires_on_explicit_ask_slash_web_or_mpn_missing_term() -> None:
    web = should_research("/web OV9281 voltage", (), research_query="OV9281 voltage")
    assert web == ResearchTrigger(query="OV9281 voltage", reason="web_command")

    # An explicit ask is the person's own words: `search` or `look up`, any case, as words — and
    # the query is the message FROM that verb to the end (what they wrote as the ask).
    asks = {
        ASK: QUERY,
        "SEARCH the web for STM32 errata": "SEARCH the web for STM32 errata",
        "can you search for it?": "search for it?",
    }
    for message, query in asks.items():
        assert should_research(message, (), research_query=None) == ResearchTrigger(
            query=query, reason="explicit_ask"
        )
    for message in ("researching the motor", "I am searching", "lookup the pins", "what is I2C"):
        assert should_research(message, (), research_query=None) is None

    # An MPN-shaped term the planner could not resolve: the first one, and only its token.
    missing = (("Servo 3", "word"), ("OV9281", "part_token"), ("STM32F407", "part_token"))
    assert should_research("why does it brown out", missing, research_query=None) == (
        ResearchTrigger(query="OV9281", reason="missing_part")
    )
    # No ask and nothing MPN-shaped missing: no research, on any tier.
    plain = (("Servo 3", "word"),)
    assert should_research("why does it brown out", plain, research_query=None) is None
    assert should_research("why does it brown out", (), research_query=None) is None

    # The `/web` remainder outranks an ask in the same message, an ask outranks a missing term.
    part = (("OV9281", "part_token"),)
    both = should_research("search OV9281", part, research_query="OV9281 pinout")
    assert both is not None and both.reason == "web_command"
    ask = should_research("search OV9281", part, research_query=None)
    assert ask is not None and ask.reason == "explicit_ask"


def test_quoted_and_path_terms_never_auto_search() -> None:
    missing = (("my motor", "quoted"), ("fw/main.c", "path"), ("Servo 3", "word"))
    assert should_research("why does it stall", missing, research_query=None) is None

    # The planner's own classification: a quoted part number and a path never reach the gate
    # as a part_token, so the only thing they could produce is no query at all.
    message = 'why does "OV9281" fail in fw/ov9281_driver.c with the Servo 3?'
    tokens = turn_scope.scope_tokens(message)
    assert ("OV9281", "quoted") in tokens and ("fw/ov9281_driver.c", "path") in tokens
    assert should_research(message, tokens, research_query=None) is None

    # A bare part number the planner could not resolve is the one automatic query.
    found = turn_scope.scope_tokens("check OV9281 on the Servo 3 board")
    trigger = should_research("check OV9281 on the Servo 3 board", found, research_query=None)
    assert trigger == ResearchTrigger(query="OV9281", reason="missing_part")

    # A shape string alone is not enough: the token must itself be part-number shaped.
    assert should_research("x", (("not a part", "part_token"),), research_query=None) is None


def test_a_path_never_leaves_and_a_quoted_term_leaves_only_when_the_person_asked() -> None:
    message = (
        r'hey, look up "OV9281 pinout" in /home/me/fw/main.c, fw/x.c and C:\Users\bob\fw\y.c ok'
    )
    ask = should_research(message, (), research_query=None)

    # The ask starts at its verb, keeps the person's quoted phrase, and carries no path at all
    # (a Windows path too: the planner's own classifier reads `/` only).
    assert ask is not None and ask.reason == "explicit_ask"
    assert ask.query.startswith("look up") and '"OV9281 pinout"' in ask.query
    for private in ("/home/me", "main.c", "x.c", "y.c", "bob", "Users"):
        assert private not in ask.query

    # `/web` is the person's own choice too: the quote stays, the path goes.
    web = should_research("/web", (), research_query='"OV9281" pinout /home/me/fw/main.c')
    assert web == ResearchTrigger(query='"OV9281" pinout', reason="web_command")

    # Past the planner's own caps (eight tokens, 255 characters each) a path is still cut out.
    quotes = " ".join(f'"q{n}"' for n in range(10))
    crowded = should_research(f"search {quotes} /h/x.c /{'seg/' * 80}f.c", (), research_query=None)
    assert crowded is not None and "/h/" not in crowded.query and "seg" not in crowded.query


def test_a_token_with_a_backslash_never_leaves_even_when_the_path_has_a_space() -> None:
    """The planner's classifier reads `/` only, so every whitespace-delimited token that holds a
    backslash is dropped: a UNC path, a drive path, and the pieces of a path with a space in it."""
    message = (
        r"look up why \\server\share\fw.c and C:\Users\bob\My Documents\fw.c and "
        r"C:\Users\bob\fw\y.c fail"
    )

    ask = should_research(message, (), research_query=None)

    assert ask is not None and ask.query.startswith("look up why ")
    for private in ("server", "share", "Users", "bob", "Documents", "fw.c", "y.c"):
        assert private not in ask.query
    # The same cut applies to `/web`, where the person typed the whole query.
    web = should_research("/web", (), research_query=r"OV9281 pinout \\nas\fw\main.c")
    assert web == ResearchTrigger(query="OV9281 pinout", reason="web_command")


def test_a_query_that_redaction_changed_or_that_ends_empty_is_never_searched() -> None:
    # A query redaction would change is dropped, never searched as "[REDACTED]" (nor billed) —
    # whether it is an automatic term, an ask or `/web`. An AWS key id is part-number shaped.
    key = "AKIA" + "ABCD1234" + "EFGH5678"
    assert (key, "part_token") in turn_scope.scope_tokens(f"look up {key}")
    assert should_research("why", ((key, "part_token"),), research_query=None) is None
    assert should_research(f"look up why {key} is rejected", (), research_query=None) is None
    assert should_research(f"/web {key}", (), research_query=key) is None
    assert should_research(f"search {HIGH_ENTROPY} fails", (), research_query=None) is None

    # Nothing after the verb, or only a path: nothing worth asking.
    for bare in ("search", "Please look up.", "look up fw/main.c", "search /home/me/robot", "/web"):
        assert should_research(bare, (), research_query=strip_web_command(bare)) is None


def test_redaction_comes_before_the_cut_so_no_prefix_of_a_secret_leaves() -> None:
    # The secret starts five characters before the 400-character edge. Cut first, five of its
    # characters would leave unmasked (too short for any detector); redacted first, the edge
    # meets the mask, the query no longer matches what was typed, and nothing is searched.
    padded = "search " + "x" * (QUESTION_MAX - 13) + f" {HIGH_ENTROPY} tail"
    assert padded.index(HIGH_ENTROPY) == QUESTION_MAX - 5
    assert should_research(padded, (), research_query=None) is None
    # A secret wholly past the edge never leaves, and does not stop the clean part going.
    beyond = "search " + "x" * (QUESTION_MAX - 7) + f" {HIGH_ENTROPY}"
    clean = should_research(beyond, (), research_query=None)
    assert clean is not None and len(clean.query) == QUESTION_MAX and "q" not in clean.query


def test_strip_web_command_takes_the_prefix_only() -> None:
    assert strip_web_command("/web OV9281 voltage") == "OV9281 voltage"
    assert strip_web_command("   /WEB\tOV9281   voltage  ") == "OV9281   voltage"
    for not_a_command in ("/web", "/web   ", "/webcam stuff", "hello /web x", "web x", ""):
        assert strip_web_command(not_a_command) is None
