"""Cross-domain linking (SOLUS-LNK-01/02) — see `linker` module docstring."""

from solus_api.linking.linker import LinkResult, link, link_from_fingerprint, link_from_mock

__all__ = ["LinkResult", "link", "link_from_fingerprint", "link_from_mock"]
