# Integration QA checkpoint — SOLUSDEV-261

Updated 2026-09-14 UTC. This is a checkpoint, not full integration sign-off.

## Live CAD pause

The user explicitly chose to keep the Onshape conservation threshold at 70% and
pause live CAD testing. The last local meter read was 1,260/1,800 estimated calls,
with no provider exhaustion latch. No threshold, counter or credential was changed.

**Leader still needs repair:** `Pitch servo rigid mount` rotated one occurrence.
Independent readback caught the change despite SOL's incorrect preservation claim.
Historical-pose correction is implemented and tested, but its live preview was
quota-blocked before execution. On resumption, restore against reference
`b7614f982498156996eb6b5d` and independently verify every pose before adding mates.

## Evidence by integration

| Area | Verified evidence | Remaining limit |
| --- | --- | --- |
| Onshape | Persisted FeatureScript cylinder geometry; Full Hand import beyond 25 tabs; SOL-selected trigger and wrist-pitch revolutes with all 23 poses preserved; nested connectors; automatic turn-end graph sync | Rigid-mount restoration, remaining Leader joints and full mechanism motion acceptance are open |
| KiCad | Saved approved label mutation, separate geometry readback, automatic webhook sync with four updates and zero errors; native circuit/ERC fixture evidence | Passing these journeys does not mark every unchecked failure-path scenario passed |
| Local code / GitHub | Recorded disposable build exit 0 and pytest exit 0 (three tests); reviewed approval recovery; read-only repository acceptance | GitHub remains read-only; GitLab was omitted at the user's request |
| Isaac Sim | Recorded SOL session start, model load, sensor edit, clearance and lift routines, status and stop | Bottle lift/contact/retention were observed, but strict target tracking and grasp criteria did not pass |
| Tool knowledge | Published selected reference entries and nine live SOL Guide question checks | Sampled retrieval is not exhaustive vendor-tool coverage |

Hardware, Arduino follow-up and Live Bench remain excluded by the user's scope.
The current browser-only runtime does not itself prove native companion readiness.

## Regression evidence

- Desktop: 3,726 tests passed; Node type checks passed.
- Node lint: exit 0, zero errors and 152 warnings.
- Script tests: 25 passed.
- Broad API run: 6,727 passed, six skipped and one failed. The KiCad native write
  test used the obsolete direct-write protocol. Its corrected preview-bound test
  passed separately and received independent review; production gates were unchanged.
- Onshape geometry/reconciliation affected run: 176 tests across ten files passed.
  Later rigid-pose corrections have separate focused verification and review.
- Quota-preview reporting: 180 broader tests passed; one expected tool-list
  assertion was updated for the new gated recovery tool. The corrected assertion
  and nine quota regressions passed together. Ruff, mypy and independent review
  passed. Known preview refusals now explain the conservation threshold while
  post-write readback failures retain an uncertain outcome.

These runs overlap and some precede the final corrections. Do not add their counts
or describe them as one fresh full-suite pass on the final tree.

Detailed walkthroughs and evidence are in `COWORK_QA_onshape-quota-acceptance.md`,
`ONSHAPE_QUOTA_AUDIT_SOLUSDEV-261.md`, `COWORK_QA_kicad-development.md`,
`COWORK_QA_code-git-development.md`, `COWORK_QA_isaac-development.md` and
`COWORK_QA_integration-tool-knowledge.md`.
