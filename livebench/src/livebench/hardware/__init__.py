"""Robot onboarding runtime seams (SOLUSDEV-248, docs/architecture/hardware-onboarding.md).

Shared, vendor-free by construction: the transport `Channel`, the `ProtocolDriver` registry,
the `Interrogator` registry and the detection loop. Anything that knows a product lives under
`livebench.plugins` and registers itself here."""
