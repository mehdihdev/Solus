"""LANE 0 contract models (SOLUSDEV-36).

The Pydantic half of the shapes published in `packages/shared-types/`. Each
module here has a TypeScript twin and a doc in `docs/contracts/`, and both
halves are validated against ONE set of JSON fixtures under
`packages/shared-types/fixtures/` — that pairing is what stops the two
definitions of a single shape drifting apart.

These live in their own subpackage rather than in `schemas.py` for the same
reason widgets self-register: `schemas.py` is one hot file that six lanes would
have to edit, and a contract per module is a create rather than an edit.

Nothing here is a feature. A model in this package describes a boundary; the
code that implements the boundary lives in the owning lane.
"""
