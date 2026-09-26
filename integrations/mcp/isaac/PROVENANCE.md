# Provenance — isaac

Server `isaac` is Solus-authored under `solus/` and `bin/`; no third-party MCP
server source is vendored. The root-owned companion registry binds its launcher.
The eight exposed names are exactly `allowlist.yaml`; six writes require central
confirmation. Low-level MCP validates original JSON arguments before coercion.

The external runtime is the user's installed NVIDIA Isaac Sim
`6.0.1-rc.7+main.0.98701505.local` at the reviewed development installation root.
NVIDIA binaries, extensions, licenses, and acceptance records are not redistributed
or modified. `python.sh`, setup script, version, and interpreter identities form
the observed launch fingerprint. This is not a claim that every NVIDIA dependency
has been independently audited or hashed.

## Historical model provenance (no longer an active bundled default)

The previously used official SO-101 geometry source is
https://github.com/TheRobotStudio/SO-ARM100 at commit
`eecbe3e0a9ebb23e25ad7b2759b03884c6660903`,
`Simulation/SO101/so101_new_calib.urdf` plus its thirteen referenced STL files.
The Apache-2.0 license is retained verbatim as `SO101-LICENSE`.
The former pinned manifest and installer were removed in the schema-v2 cleanup.
The following digest is retained solely as historical attribution:
The canonical manifest digest is
`a1be9138359e044a007a4981817f3a8783fca47985b424f3fa9ca3d02e12b5b9`.
No original geometry bytes are modified. Generated USD is a temporary derivative.

`requirements.lock.txt` reuses the repository's reviewed Code server dependency
closure (MCP 1.29.0, Pydantic 2.13.4) with hash verification. The local private
installation succeeded on 2026-09-12. No pip or extension install occurs at launch.
Schema-v2 assets are now explicitly supplied by each project under its authorized
workspace `.solus/isaac/models/<manifest-sha256>/`. No geometry is bundled,
downloaded or selected by default. Retain historical `SO101-LICENSE` attribution.

Updates require a fresh source revision, explicit manifest/digest review, native
import/physics checks, dependency audit and renewed security review. Quarterly
review and a 14-day response to relevant CVEs follow the shared fork policy;
human maintainers own release sign-off and advisory tracking.

Human release signatures remain pending. This development implementation and
agent tests are not substitutes for the two human shipping signatures.
