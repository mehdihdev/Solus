# UI implementation and Isaac connection cleanup — execution plan

User authority: 2026-09-15 attachment “UI implementation (Live Bench, graph, hardware add) +
Isaac de-hardcoding”. Its descriptions supersede conflicting presentation wireflows. No design
screens directory exists. Work remains on the existing SOLUSDEV-262 branch, commit per phase.

1. Live Bench: one view with scene/sensor column and dynamic signal grid/reasoning; pause display,
   retain capture/playback inline, preserve stream and confirmation boundaries. Worker owns
   `features/bench/**`; root owns governing docs and verification.
2. Graph: deterministic organic default packing, untouched saved positions, grouped curved
   labelled relationships, nested metadata and real floating proposals. Scope
   `features/graph/navigation/**`, with narrow upstream data/persistence wiring if required.
3. Hardware: three inline sections, shared device cards, search/details, describe-as-part;
   remove modal paths and use existing entity/library/sourcing services. Scope
   `features/graph/hardware/**`, excluding the phase4 hygiene ratchet.
4. Isaac: remove product import offer from application connection; expose truthful application
   state and connection controls through existing bridge capability; extend hygiene regressions.
   Scope connection presentation, existing Isaac status seam, and vendor-hygiene tests.

Each phase has its own commits and verification. After the shared Phase1 interface settled,
Phase2 graph navigation, Phase3 hardware controls, and Phase4 application connection work can
proceed in parallel on disjoint ownership with stable existing APIs; root integrates reviews.
Independent read-only inspection/reviews may overlap. Each
implementation writes tests first, records RED, verifies GREEN and commits its phase. Root runs
final desktop types/tests, appropriate Python checks if touched, safety ratchets and migration
head. Fresh code/security/language reviewers inspect each relevant change. No pushes or MRs.

Truthfulness decisions: pause is presentation-only; imported/confirmed geometry drives joints;
absent sensor/unknown units remain explicit. CAD-linked and nominal status require supporting
evidence. Auto placement never changes user positions. Missing categorization remains a stated
suggestion, not a fabricated SOL call. Connection never imports a platform or commands motion.

Known seams to resolve during phases: account headers currently have session-local presentation
coordinates (not graph UUIDs); persist these separately without inventing graph identity. Existing
Isaac control is an external bridge capability, not the legacy Live Bench simulator adapter.
The normal destructive-action gate remains authoritative for launching/stopping a simulator.
