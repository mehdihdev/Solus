"""Solus-authored tests for the altium fork (SOLUSDEV-102 ALT-3).

This directory is deliberately a PACKAGE — the one fork test dir that ships an
`__init__.py` — because its module basenames mirror the kicad fork's
(test_launch_entrypoint.py, test_tree_hash.py, ...) and pytest's default
prepend import mode cannot hold two top-level modules with one name in a
single session (`import file mismatch`). As a package these import as
`tests.test_*`, which never collides with kicad's bare-name modules. A
conftest.py is NOT an option: a module literally named `conftest` on sys.path
shadows `packages/api/tests/conftest` for the API tests that import it by
bare name. The import bootstrap lives in `altium_paths.py` instead.
"""
