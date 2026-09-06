"""The engineering corpus (CORPUS C1/C2, ADR-036) — what SOL ships knowing.

Global, tenant-free content: `contract` is the chunk shape, `enums` its closed
vocabularies, `hosts` the rights-holder allowlist, `chunking` turns authored
Markdown into chunks, `ingest` is the ONLY write path into `corpus_chunk`,
`retrieval` serves active chunks by domain/topic, and `router` exposes the
manifest, chunk lookup, and search.
"""
