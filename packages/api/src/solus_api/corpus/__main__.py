"""Corpus CLI — `python -m solus_api.corpus <command>`.

validate   load the content tree, run every contract and cross-chunk rule, report counts
manifest   write content/manifest.json from the tree (fails CI when stale — see tests)
ingest     the ONLY write path into corpus_chunk (ADR-036 rule 3); deploy/admin step
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from solus_api.corpus.chunking import (
    MANIFEST_FILE,
    ChunkingError,
    build_manifest,
    content_root,
    load_content_tree,
    load_release,
    validate_corpus,
)
from solus_api.corpus.enums import CorpusDomain


def _load(root: Path, only: list[str] | None = None):  # type: ignore[no-untyped-def]
    release = load_release(root)
    domains = None if not only else [CorpusDomain(d) for d in only]
    chunks = load_content_tree(root, only=domains)
    validate_corpus(chunks, release)
    return release, chunks


def cmd_validate(root: Path, only: list[str] | None) -> int:
    release, chunks = _load(root, only)
    by_domain = Counter(c.domain.value for c in chunks)
    by_status = Counter(c.status.value for c in chunks)
    topics = Counter((c.domain.value, c.topic.value) for c in chunks)
    print(f"corpus {release.corpus_version}: {len(chunks)} chunks, {len(topics)} topics")
    print("by domain:", dict(sorted(by_domain.items())))
    print("by status:", dict(sorted(by_status.items())))
    return 0


def cmd_manifest(root: Path, *, check: bool) -> int:
    release, chunks = _load(root)
    manifest = json.dumps(build_manifest(chunks, release), indent=2, sort_keys=False) + "\n"
    path = root / MANIFEST_FILE
    if check:
        current = path.read_text() if path.exists() else ""
        if current != manifest:
            print(f"{path} is stale; run `python -m solus_api.corpus manifest`", file=sys.stderr)
            return 1
        print(f"{path} is current ({len(chunks)} chunks)")
        return 0
    path.write_text(manifest)
    print(f"wrote {path} ({len(chunks)} chunks, corpus {release.corpus_version})")
    return 0


def cmd_ingest(root: Path, *, database_url: str | None, embed: bool) -> int:
    from solus_api.corpus.ingest import run_ingest_cli

    return asyncio.run(run_ingest_cli(root, database_url=database_url, embed=embed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m solus_api.corpus")
    parser.add_argument("--root", type=Path, default=content_root(), help="content tree root")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument(
        "--domain", action="append", help="restrict to a domain (repeatable); default: all"
    )
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--check", action="store_true", help="fail if the manifest is stale")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--database-url", default=None, help="defaults to SOLUS_DATABASE_URL")
    ingest.add_argument("--no-embed", action="store_true", help="skip embeddings (keyless)")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return cmd_validate(args.root, args.domain)
        if args.command == "manifest":
            return cmd_manifest(args.root, check=args.check)
        return cmd_ingest(args.root, database_url=args.database_url, embed=not args.no_embed)
    except ChunkingError as exc:
        print(f"corpus invalid — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
