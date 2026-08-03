"""Operator tooling (`python -m solus_api.ops.<tool>` / uv script entry points).

One-off provisioning and diagnostics run by a human operator, never by the API
process: these tools may prompt interactively and write to the SecretStore.
"""
