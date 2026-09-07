"""Solus-authored tests for the `local` server (SOLUSDEV-249).

A PACKAGE on purpose (like the altium fork's tests): several basenames here
mirror the kicad fork's (`test_launch_entrypoint.py`, ...) and pytest's
prepend import mode cannot hold two top-level modules with one name in a
single session. As a package these import as `local.tests.test_*`. A
conftest.py is NOT an option (a module literally named `conftest` on
sys.path shadows `packages/api/tests/conftest`); the import bootstrap lives
in `local_paths.py` and every sibling imports it FIRST.
"""
