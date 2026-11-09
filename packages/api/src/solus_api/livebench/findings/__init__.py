"""SOLUSDEV-321 P2 — live signals into findings: envelopes (what normal, warning and limit look like
for each quantity of each part), then the rules that compare a window of samples against them.

Shared code: it names a quantity and a limit key, never a product, a vendor or a simulator
(`tests/test_capability_hygiene.py` and `tests/test_vendor_hygiene_api.py` sweep this package).
"""
