These two recordings are synthetic fixtures, not captured hardware data. The
UUIDs identify fixture graph nodes; an import integration test must establish
those identities in its own project or explicitly remap them to its fixture
robot and accepted part. They never authorize motion. `baseline.json` observes
90 degrees against an explicit 90-degree bound; `clamp.json` observes 45 degrees
against a changed 45-degree bound. Both carry an explicit 2 A fixture rating,
measured current, and a command exceeding the bound. No live device or vendor
rating is implied by this synthetic example.
