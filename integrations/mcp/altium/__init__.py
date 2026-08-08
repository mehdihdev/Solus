"""Namespace anchor for the altium fork (SOLUSDEV-102 ALT-3).

This `__init__.py` exists so the Solus-authored `tests/` package resolves as
`altium.tests` (and `solus/` as `altium.solus`) instead of claiming the bare
top-level names. Without it, mypy invocations that receive both this fork's
`tests/__init__.py` and the vendored `upstream/tests/__init__.py` in one run
(the H8/H10 hooks pass changed files explicitly, bypassing `exclude`) fail
with `Duplicate module named "tests"`, and the bare names would also be one
sys.modules slot shared with every other fork's identically-named packages.

`upstream/` is NOT part of this package (it ships no fork-level `__init__`
chain and stays byte-pristine under the PROVENANCE tree hash), and the
launchers' runtime import of `solus` is unaffected: `bin/launch` puts the
fork directory itself on the child's import path, where `solus/` remains a
top-level package regardless of this file.
"""
