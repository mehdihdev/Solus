# Gitleaks false-positive fix — SOLUSDEV-260

## Scope and governing documents

Governed by root AGENTS.md, DECISIONS.md ADR-007, the scanner contract in
infrastructure/ci/README.md and COWORK_QA_ci_performance.md. No application
architecture, API, wireflow, contract or pipeline-selection changes.

The fix adds 30 exact historical fingerprints to .gitleaksignore, covering
31 detections (one fingerprint repeats across merge-parent patches). Reviewed
findings are a parts identifier in QA output, a Python keyword expression,
and synthetic fixtures used to test secret redaction. Each group has a reason
in the ignore file. Exceptions do not exempt whole files, rules or future commits.

## Setup

- [ ] Use the SOLUSDEV-260 feature branch with the proposed .gitleaksignore.
- [ ] Have Docker and the CI Gitleaks image available, plus a complete Git clone.
- [ ] Use only synthetic markers for controls. Never paste real credentials into
      files, reports, screenshots or logs. Keep scanner output redacted.
- [ ] For GitLab verification, the human must commit and push the fix, then open
      or reopen the MR. Retrying an old job uses its original commit and cannot
      validate this fix. Leave successful checks and pipeline rules intact.

## Verification walkthrough

1. [ ] From the repository root run the full-history scan:

   ```sh
   docker run --rm --network none -v "$PWD:/repo:ro" -w /repo \
     zricethezav/gitleaks:latest detect --source . --config .gitleaks.toml \
     --no-banner --redact \
     --log-opts='--full-history --all --diff-merges=separate'
   ```

   Expect exit 0 and no findings. If other refs contain additional findings,
   review those separately; do not broaden these exceptions automatically.

2. [ ] Scan the changed files as uncommitted content in a disposable directory,
      using the same policy and Gitleaks directory mode. Expect no new findings
      in the ignore-file comments or this QA note.
3. [ ] In a disposable Git repository copy the policy and ignore file, commit
      them, and scan. Expect exit 0. Generate a synthetic token-shaped marker
      locally, commit it, and scan again. Expect exit 1 with a finding.
4. [ ] In another disposable repository copy the existing redaction fixture
      into its original test path and line, with the new ignore file. Commit
      and scan. Expect exit 1: the historical exception must not apply to a
      different commit, even at the same path and line.
5. [ ] Run `.venv/bin/python -m pytest infrastructure/ci/tests -q`.
      Expect all tests to pass, including policy-change full scans, deleted
      content, merge patches, invalid revisions and scanner-error propagation.
6. [ ] In the new GitLab MR pipeline confirm the job checks out the human-pushed
      fixed commit, runs scan-secrets.sh, and passes. A policy change must still
      select the full-history scan. Record the job link and commit.

## Local evidence

- Before fix: 31 findings across four paths, 30 unique fingerprints.
- After fix: full-history/all-ref scan passed, 860 commits and approximately
  199 MB scanned. CI originally had a different fetched-ref inventory and scanned
  1,171 commits; local success does not replace the next GitLab run.
- Disposable clean-policy control passed. A new random synthetic marker and a
  reintroduced fixture at the original path/line each failed with one finding.
- CI regression suite: 62 passed.
- Application source and tests are unchanged; application suites were not rerun
  for this scanner-policy-only fix. No repository commits or pushes were made.
- Ponytail is unavailable in this session; independent code and security review
  cover the scoped suppression change.
