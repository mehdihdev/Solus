"""SOLUS-TU-02 — documentation-ingestion paths that feed the tool-knowledge KB.

Each ingester parses an official vendor source into candidate entries and
writes them through the TU-06 guard's docs path — never directly. Nothing here
bypasses the tenancy boundary.
"""
