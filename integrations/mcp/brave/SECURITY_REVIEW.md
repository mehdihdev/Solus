# Fork security review — `brave` @ tree `2d69236406e2231f08b2122215e09eadeeccd207` — `2026-09-07`

> Filled from `integrations/mcp/SECURITY_REVIEW.template.md` (SOLUSDEV-252 P6 lane draft review).
> Append-only: later reviews are appended below, never rewrite this one. **SIGNATURES LIVE IN
> PROVENANCE.md AND REMAIN BLANK — filling them is a human-only act; the two devs must read this
> checklist, re-run the pasted commands, and sign against the tree hash above.** Items that need
> CI or a network-disabled container are dispositioned **PENDING(human/CI)** rather than ticked.
>
> Scope: `@brave/brave-search-mcp-server@2.1.3` npm tarball (`upstream/`), plus `bin/launch`,
> `allowlist.yaml`, the fork-root `package.json` + `package-lock.json`. **Threat model differs
> from the template's default:** this fork runs **in the Solus API container** (cloud-side, human
> decision 2026-09-07), not on a customer machine. What it can do locally = what the API process
> can do: hold the team's Brave key (delivered per spawn), reach the network. The review therefore
> weights egress, key handling and the child-environment scrub above filesystem confinement.

## 1. Supply chain

- [x] `upstream/` matches the pinned artifact — evidence: `npm pack @brave/brave-search-mcp-server@2.1.3`
      → tarball sha512 recomputed = `cdd6db2b…3708ff`, equal to the registry `dist.integrity`
      (`sha512-zdbbKxCv…ODcI/w==`, `npm view … dist.integrity`); `package/` extracted verbatim;
      `git rev-parse`-equivalent tree hash of `upstream/` = `2d69236406e2231f08b2122215e09eadeeccd207`,
      recomputed on every run by `tests/test_launch_entrypoint.py::test_provenance_pins_version_tarball_and_matching_tree_hash`.
- [x] No runtime fetch — evidence: `bin/launch` read in full (72 lines); token scan pinned by
      `test_launch_contains_no_network_or_installer_commands` (npx/uvx/npm install/npm ci/pip
      install/curl/wget/git clone/nc/ftp/rsync/ssh banned from command text). The launcher's only
      exec before the server is `"$NODE" --version` (version gate, local).
- [x] Registry install hooks — evidence: `upstream/package.json` `scripts`: `build`, `prepare`
      (`npm run format && npm run build`), `watch`, `format*`, `test`, `inspector*`. No
      `preinstall`/`postinstall`. `prepare` would run on `npm install` of the package **from git**
      only; the fork is never installed as a package (dist is run in place) and the dependency
      install runs `npm ci --ignore-scripts` (`scripts/install-mcp-forks.sh`, Dockerfile), so no
      dependency lifecycle script runs either.
- [x] Lockfile committed, complete, hash-pinned — evidence: `package-lock.json` (lockfileVersion 3,
      96 packages, 96 `integrity` sha512 entries, 96 `resolved` registry URLs, 0 `dev: true`),
      shape enforced by `test_lockfile_pins_every_package_with_an_integrity_hash`.
      **PENDING(human/CI):** the offline `npm ci --omit=dev --ignore-scripts` reproduction in a
      network-disabled container (the Dockerfile stage is the natural place).
- [ ] Dependency audit — **PENDING(human/CI):** `npm audit --audit-level=high` against
      `package-lock.json` is the CI dependency-audit job (CLAUDE.md §7); not run in this session
      (`npm audit` needs registry access and the lane installed with `--no-audit`). Every advisory
      found there must be dispositioned in an appended section before ship. Dependency roster:
      `@modelcontextprotocol/sdk@1.30.0`, `commander@14.0.3`, `dotenv@17.3.1`, `express@5.2.1`,
      `zod@4.3.6` + transitive (express pulls the usual body-parser/qs/… set; `express` is used
      only by the `http` transport, which the launcher never selects).
- [x] Reproducibility — evidence: every package exactly pinned with integrity (see lockfile test);
      two `npm ci` runs from the same lock cannot resolve different sets. Bit-identical artifacts
      are a template exclusion.

## 2. Least privilege

- [x] Runs as the invoking user — evidence:
      `grep -rn "sudo\|setuid\|seteuid\|runas" upstream/dist bin/` → **0 hits**. In the API image
      the invoking user is the non-root `solus` (uid 10001, `api.Dockerfile`).
- [x] Filesystem scope — evidence (tier-1 line-read): the ONLY file access in `upstream/dist`
      (non-test) is `utils.js::readBraveApiKeyFromFile` (`readFileSync`), reached solely via
      `--brave-api-key-file`/`BRAVE_API_KEY_FILE` (`config.js:38,77-83`) — neither is set by the
      launcher, and the child env is scrubbed so an ambient value cannot supply it. No writes
      anywhere (`grep -rn "writeFile\|createWriteStream\|appendFile" upstream/dist` → 0 hits).
      `dotenv.config()` (`config.js:6`) reads `./.env` from **cwd** — the launcher `cd`s to the
      fork directory, where a `.env` can never exist (pinned by
      `test_launch_forwards_exactly_the_declared_env_and_fixed_argv`: child `PWD` == fork dir).
- [x] Network egress: **`https://api.search.brave.com` only** — evidence:
      `grep -rnE "fetch\(|axios|net\.connect|WebSocket|http\.request|https\.request" upstream/dist`
      (non-test) → exactly one hit, `BraveAPI/index.js:104 fetch(urlWithParams, { headers })`,
      with `urlWithParams` built from the constant `https://api.search.brave.com` +
      `typeToPathMap[endpoint]` (`:3-13,45`). `test_upstream_network_egress_is_the_brave_api_only`
      pins "fetch( appears in that file only". The `goggles` parameter may carry an `https://` URL
      but it is sent to Brave as a query parameter, not fetched by the server (`:26-40,80-89`).
      The `express` `app.listen` (`protocols/http.js:82`) is the http transport — unreachable:
      the launcher passes `--transport stdio` and `BRAVE_MCP_TRANSPORT=stdio`.
- [x] No `shell=True` / `child_process` — evidence:
      `grep -rnE "child_process|\beval\(|new Function|execSync|spawn\(" upstream/dist` → **0 hits**
      (also pinned in the egress test).
- [x] `spec.args` fixed — evidence: `MCPServerSpec(name="brave", command=<abs>/bin/launch, args=())`
      (`mcp_servers.py`); `bin/launch` bans `$@`/`$*` and pins the exec line
      `"$NODE" "$FORK_DIR/upstream/dist/index.js" --transport stdio`
      (`test_launch_has_fixed_argv_with_no_argument_passthrough`; behavioural check passes
      `--injected arg` and asserts the child argv is unchanged). Upstream's `commander`
      `.allowUnknownOption()` would otherwise accept stray flags — irrelevant with a fixed argv.

## 3. Sandbox posture

- [x] Declared posture — see "Declared sandbox posture" below (cloud container, not per-OS).
- [ ] Functions under the strictest declared posture — **PENDING(human/CI):** run
      `brave_web_search` once inside the API image with egress restricted to
      `api.search.brave.com:443` and a read-only filesystem outside `/tmp`; no failure caused by
      blocked _undeclared_ access is expected (the code has no other access sites — §2).
- [x] Nothing detects/disables sandboxing or self-modifies the install — tier-1 read of
      `index.js`, `config.js`, `server.js`, `protocols/stdio.js`, `BraveAPI/index.js`, `utils.js`:
      no filesystem writes, no self-update, no environment probing beyond the documented
      `BRAVE_*` knobs.

## 4. Secret hygiene

- [x] Environment access confined — evidence: `grep -rn "process\.env" upstream/dist` (non-test)
      → 12 hits, ALL in `config.js:21,37-47`: `BRAVE_API_KEY`, `BRAVE_API_KEY_FILE`,
      `BRAVE_MCP_LOG_LEVEL`, `BRAVE_MCP_TRANSPORT`, `BRAVE_MCP_ENABLED_TOOLS`,
      `BRAVE_MCP_DISABLED_TOOLS`, `BRAVE_MCP_PORT`, `BRAVE_MCP_HOST`, `BRAVE_MCP_ALLOWED_ORIGINS`,
      `BRAVE_MCP_ALLOWED_HOSTS`, `BRAVE_MCP_STATELESS`. The launcher's `env -i` allowlist passes
      `HOME LANG TMPDIR PATH(const) BRAVE_API_KEY BRAVE_MCP_TRANSPORT BRAVE_MCP_LOG_LEVEL
BRAVE_MCP_ENABLED_TOOLS` and nothing else; Solus-set values are applied last so an ambient
      `BRAVE_MCP_TRANSPORT=http` cannot open a listener
      (`test_launch_forwards_exactly_the_declared_env_and_fixed_argv`).
- [x] No credential ever logged — evidence: `grep -rn "console\." upstream/dist` (non-test) →
      `helpers.js:7` ("Server shut down."), `http.js:65,78,83` (error / config / listen URL —
      http path, unreachable), `index.js:7,18` ("Invalid configuration" / caught error). The key
      is referenced only to build the `X-Subscription-Token` header (`BraveAPI/index.js:18`) and
      in `config.js` assignment/validation; never interpolated into a log line. The
      "key required" error (`config.js:85`) names the knobs, not a value. Cloud side:
      `mcp_tool.py::_resolve_env` puts the value into the child env dict only; log lines carry
      ref NAMES (pinned by `tests/test_mcp_tool.py` caplog assertion).
- [x] No telemetry/phone-home — covered by the §2 egress grep: the single `fetch` target is the
      Brave API the tools exist to call. Nothing to strip.
- [x] No credential persistence — no write sites exist (§2); `readBraveApiKeyFromFile` is a read
      of an operator-supplied path, unreachable here.
- [x] SecretStore delivery seam — the value travels `SecretStore.get("brave_api_key")` →
      `_resolve_env` → `StdioServerParameters.env["BRAVE_API_KEY"]` → launcher → child env.
      Nothing in the fork reads Solus config or credential stores.

## 5. Untrusted I/O

- [x] Tool inputs hostile — every exposed tool's arguments are validated by zod schemas before
      the request is built (`tools/web/params.js`, `tools/llm_context/schemas/input.js`,
      `tools/news/params.js`, `tools/summarizer/params.js`: bounded `query` ≤ 400 chars / 50 words,
      integer ranges on counts, enum-restricted filters). No path or archive handling anywhere in
      the exposed roster (nothing touches the filesystem — §2).
- [x] Parsers bound input sizes — Brave API responses are parsed with `response.json()`; the
      `brave_llm_context` response is additionally schema-checked (`LlmContextSearchApiResponseSchema.safeParse`,
      `tools/llm_context/index.js`) with a treeified error returned as `isError` on mismatch.
      Cloud side, `mcp_tool._map_result` caps error text at `UNTRUSTED_TEXT_CAP` and the prompt
      layer caps/fences every result (`ToolDescriptor.result_cap`, `data_block`). Response SIZE
      from Brave is not bounded in the fork itself — the API-side `research()` budget
      (`max_bytes`) and the registry result cap are the bound; recorded residual.
- [x] No `eval`/`exec`/`Function()` — `grep -rnE "\beval\(|new Function|import\(" upstream/dist`
      → 0 hits (`import(` dynamic: 0).

## 6. Destructive actions

- [x] Classification — independent read of the four exposed handlers (`tools/web/index.js`,
      `tools/llm_context/index.js`, `tools/news/index.js`, `tools/summarizer/index.js`): each
      issues one `GET` to Brave and formats the response. All four `requires_confirmation: false`
      with a Solus-written `reason` in `allowlist.yaml`. No differences against the allowlist.
- [x] Destructive tools carry the gate — n/a: none are destructive. `destructiveHint`/
      `openWorldHint` annotations from the server were not relied on (`mcp_tool.py` ignores them).
- [x] No side effects beyond description — `brave_web_search` with `summary: true` returns a
      summarizer key consumed by `brave_summarizer`; that is documented upstream behaviour, not a
      hidden mutation.

## 7. Code-review depth — the honest tiers

- [x] **Tier 1 — 100% line-read:** `bin/launch`; `upstream/dist/index.js`, `config.js`,
      `server.js`, `protocols/index.js`, `protocols/stdio.js`, `BraveAPI/index.js`, `utils.js`,
      `helpers.js`; the fork-root `package.json`.
- [x] **Tier 2 — line-read (exposed handlers):** `tools/index.js`, `tools/web/index.js`,
      `tools/llm_context/index.js` (+ `schemas/input.js`, `schemas/output.js`),
      `tools/news/index.js`, `tools/summarizer/index.js`.
- [x] **Tier 3 — spot-check (unexposed, never registered):** `tools/local/index.js`,
      `tools/place_search/index.js` — same `API.issueRequest` shape, no extra access sites.
      Skipped: `tools/images/*`, `tools/videos/*`, `protocols/http.js` (line-read for §2 only),
      `protocols/rebinding.js`, `jsonSchemaDialect.js`, `constants.js`, all `*.test.js`
      (never executed — no test runner in the image).
- [x] Non-allowlisted tool code — disabled in-process via upstream's own
      `BRAVE_MCP_ENABLED_TOOLS` knob set by the launcher (`server.js::isToolPermittedByUser`),
      AND skipped cloud-side by the allowlist filter. Residual: the code is present in
      `upstream/dist` but unregistered; it shares the single egress site.
- [x] Depth recorded above.

## 8. Update path

- [x] Re-review triggers in force (PROVENANCE.md); tree hash recomputed by the fork tests on
      every run.
- [x] Rebase rule acknowledged (§8 of the template).
- [ ] Both PROVENANCE sign-off lines dated against THIS tree hash — **BLANK, human-only.**

---

## Declared sandbox posture (fill per fork)

**Where it runs:** the Solus API container (`infrastructure/docker/api.Dockerfile`, non-root
`solus` user), spawned per tool call by `mcp_tool._open_session` with the SDK's stdio transport.
NOT the customer machine, NOT the companion. (A customer companion that discovers this fork dir
would attempt a launch and get exit 78 on the empty-key check — noisy but harmless; a companion
"cloud-side fork, skip" marker is a follow-up outside this lane.)

**What confines it today:** OS user permissions of `solus`; the launcher's `env -i` scrub with a
constant PATH; fixed argv; cwd pinned to the fork dir; interpreter pinned to `SOLUS_NODE_BIN` or
a fixed absolute list with a `>= 22` version gate; the key present only in the child env for the
lifetime of one call; upstream's tool roster trimmed by env to the allowlist; per-call process
lifetime (the registry's timeout reaps a hung child — `test_timed_out_invoke_reaps_the_server_process`).

**What it assumes the platform adds:** container egress policy limited to `api.search.brave.com:443`
(ECS security group / NACL — infrastructure, not this lane); the CI `npm audit` job.

## Exclusions — deliberately NOT on this checklist

Per the template (no fork-specific additions).

## Known failure modes of this scheme (and the built-in mitigations)

Per the template. Fork-specific note: the Brave response SIZE is unbounded in the fork; the
cloud-side `research()` byte budget and `ToolDescriptor.result_cap` are the bound.
