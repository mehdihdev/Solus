"""SOLUS-TU-06 — vendor control catalog + doc-domain allowlist.

The catalog is the "allowlist at the source" the contract doc demands: the
probe and visual paths may only attach geometry/meaning to controls that vendor
documentation (seed files or previously published vendor_docs rows) already
names. The doc-domain allowlist keeps a customer document from posing as
vendor documentation.
"""

from collections.abc import Callable

import pytest
from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.toolkb.catalog import (
    VENDOR_DOC_DOMAINS,
    is_known_vendor_control,
    is_vendor_doc_url,
)
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]


def test_every_tool_family_has_a_doc_domain_entry() -> None:
    assert set(VENDOR_DOC_DOMAINS) == set(ToolFamily)


class TestVendorDocUrl:
    def test_allowed_host(self) -> None:
        assert is_vendor_doc_url(ToolFamily.KICAD, "https://docs.kicad.org/8.0/en/eeschema/")

    def test_path_prefix_entries_reject_other_paths_on_same_host(self) -> None:
        assert is_vendor_doc_url(ToolFamily.ONSHAPE, "https://cad.onshape.com/help/Content/x.htm")
        # a customer document on the SAME host is not vendor documentation
        assert not is_vendor_doc_url(
            ToolFamily.ONSHAPE, "https://cad.onshape.com/documents/9a1c2ef4b7d8"
        )

    def test_prefix_match_ends_at_a_segment_boundary(self) -> None:
        # /helpdesk-upload must not satisfy the /help prefix (review finding)
        assert not is_vendor_doc_url(
            ToolFamily.ONSHAPE, "https://cad.onshape.com/helpdesk-upload/x"
        )
        # the exact prefix with no trailing path is still vendor docs
        assert is_vendor_doc_url(ToolFamily.ONSHAPE, "https://cad.onshape.com/help")

    def test_host_must_match_exactly_not_by_suffix(self) -> None:
        assert not is_vendor_doc_url(
            ToolFamily.KICAD, "https://docs.kicad.org.attacker.example/8.0/"
        )

    def test_https_only(self) -> None:
        assert not is_vendor_doc_url(ToolFamily.KICAD, "http://docs.kicad.org/8.0/")

    def test_garbage_url(self) -> None:
        assert not is_vendor_doc_url(ToolFamily.KICAD, "not a url")


class TestKnownVendorControl:
    async def test_seed_controls_are_known(self, db: AsyncSession) -> None:
        assert await is_known_vendor_control(db, ToolFamily.KICAD, "kicad.eeschema.place_net_label")

    async def test_unknown_control_is_unknown(self, db: AsyncSession) -> None:
        assert not await is_known_vendor_control(
            db, ToolFamily.ONSHAPE, "onshape.custom.gripper_generator"
        )

    async def test_published_vendor_docs_rows_extend_the_catalog(
        self, db: AsyncSession, make_entry: EntryFactory
    ) -> None:
        control = "kicad.pcbnew.interactive_router_settings"  # deliberately not in the seed
        assert not await is_known_vendor_control(db, ToolFamily.KICAD, control)
        db.add(make_entry(control_id=control))
        await db.flush()
        assert await is_known_vendor_control(db, ToolFamily.KICAD, control)

    async def test_candidate_rows_do_not_extend_the_catalog(
        self, db: AsyncSession, make_entry: EntryFactory
    ) -> None:
        control = "kicad.pcbnew.candidate_only"
        db.add(make_entry(control_id=control, status=KnowledgeStatus.CANDIDATE))
        await db.flush()
        assert not await is_known_vendor_control(db, ToolFamily.KICAD, control)


@pytest.mark.parametrize("tool", list(ToolFamily))
def test_doc_domains_are_https_hosts_without_scheme(tool: ToolFamily) -> None:
    for entry in VENDOR_DOC_DOMAINS[tool]:
        assert not entry.startswith("http"), "domain entries are host[/path], scheme-less"
        assert " " not in entry
