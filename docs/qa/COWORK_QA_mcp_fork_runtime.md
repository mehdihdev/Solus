# COWORK QA — Python for local tools (SOLUSDEV-329)

> **What this tests.** Solus's local tools (KiCad, Code, Local, Altium, Gazebo, Isaac) are small
> Python programs that run on the user's own machine. Before this ticket they only ran on a
> developer's machine. Now Solus builds each tool's Python environment itself, from the user's
> own Python 3.12/3.13 or from a Solus-managed Python, and shows it all in
> **Settings → Python for local tools**.
>
> Governing docs: DECISIONS.md ADR-031 amendment (2026-11-19) and ADR-034 amendment (2026-11-19),
> `docs/architecture/mcp-fork-runtime.md`, `docs/wireflows/settings.md`.
>
> Mark each box pass/fail. Anything marked **(Windows)** or **(Linux)** needs that OS; on the
> other platforms record it as N/A, not fail.

## Setup

- [ ] The Solus desktop app is running and you are signed in, with at least one project open, so
      the local companion is connected ("Bridge" shows connected).
- [ ] Internet access to `pypi.org` (setup downloads packages once).
- [ ] Know which Pythons this machine has. On macOS:
      `ls /Library/Frameworks/Python.framework/Versions/ /opt/homebrew/bin/python3* 2>/dev/null`.
- [ ] **Clean slate.** Quit Solus, then delete the tool environments so you start from "needs setup":
  - macOS: `~/Library/Application Support/Solus/mcp-envs/` (and `mcp-python/` if present)
  - Windows: `%LOCALAPPDATA%\Solus\mcp-envs\` (and `mcp-python\`)
  - Linux: `~/.local/share/solus/mcp-envs/` (and `mcp-python/`)
- [ ] Optional, for event checks: access to the API logs or the `events` table.

Developers running from source (`pnpm dev:all`): run `make mcp-forks` only if a flow says so.
It builds the same environments the app builds.

---

## Flow 1 — First visit: detection and the "needs setup" state

1. Open **Settings → Python for local tools**.
   - [ ] **Expected:** a short "detecting" state, then a list of the Pythons found on this machine.
2. Look at the list.
   - [ ] Supported interpreters (CPython 3.12 or 3.13) are selectable.
   - [ ] Unsupported ones are shown dimmed with a reason, for example "3.9 — Solus needs 3.12 or
         3.13", "3.14 — Solus needs 3.12 or 3.13", or
         "Virtual environment — choose the Python it was made from".
   - [ ] On macOS without Xcode tools, `/usr/bin/python3` is listed as unsupported, and **no**
         "install developer tools" system dialog appears.
3. Look at the tools list.
   - [ ] KiCad, Code and Local show **Needs setup**.
   - [ ] Gazebo shows Needs setup on macOS/Linux, or "— (Linux and macOS only)" on Windows.
   - [ ] Altium shows "— (Windows only)" on macOS/Linux.
   - [ ] Isaac shows "— (Linux only)" on macOS/Windows.
4. Open **Settings → Needs attention** (or the attention area of Settings).
   - [ ] **Expected:** a card saying local tools need setup, linking to the Python section.

## Flow 2 — Choose a Python and set everything up (happy path)

1. Select a supported interpreter in the list (prefer a 3.12 if you have one).
   - [ ] **Expected:** the choice is saved and the tools still say **Needs setup**, with a
         **Set up now** button.
2. Click **Set up now**.
   - [ ] **Expected:** a progress row per tool (venv → packages → check → stamp). KiCad takes
         longest (about 1–3 minutes on an ordinary connection; it downloads numpy/pandas).
3. Wait for it to finish.
   - [ ] **Expected:** every tool for this OS shows **Ready** with the Python version used.
   - [ ] The Needs-attention card for local tools is gone.
4. Use a tool: ask SOL something that uses KiCad or the Local folder scan in a project with a
   linked folder (for example "scan my project folder").
   - [ ] **Expected:** SOL uses the tool. There is no "tool unavailable / needs setup" message.
5. **Restart check.** Quit and reopen Solus, then reopen the section.
   - [ ] **Expected:** tools are still **Ready**, nothing rebuilds, and the chosen Python is still
         selected.

## Flow 3 — Guide vs Expert copy

1. Switch SOL mode to **Guide** (Settings → SOL mode), then reopen Python for local tools.
   - [ ] **Expected:** explanatory text (what Python is needed for and why), plus an in-page
         "Learn more" expander.
2. Switch to **Expert**.
   - [ ] **Expected:** terse text such as "Base interpreter for local MCP tools: CPython 3.12 or
         3.13." and "Ready."
3. With at least one tool needing setup (repeat the clean-slate step if needed), check the
   Needs-attention card in both modes.
   - [ ] **Expected:** the card text differs between Guide and Expert.

## Flow 4 — Pick an interpreter by hand

1. Click **Choose…**.
   - [ ] **Expected:** a native file picker opens (`.exe` filter on Windows).
2. Cancel the picker.
   - [ ] **Expected:** nothing changes and no error is shown.
3. Click **Choose…** again and pick a supported Python binary (for example
   `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13`).
   - [ ] **Expected:** it is accepted and marked as the choice; tools show Needs setup.
4. Click **Choose…** and pick an unsupported binary (for example `/usr/bin/python3` 3.9, or a
   3.14).
   - [ ] **Expected:** "That Python is not 3.12 or 3.13, so the choice was not saved." The previous
         choice is kept.
5. Click **Choose…** and pick the `python` inside any virtual environment (for example a
   project's `.venv/bin/python`).
   - [ ] **Expected:** refused as a virtual environment, and the choice is not saved.
6. Click **Choose…** and pick a non-Python file (for example `/bin/ls`).
   - [ ] **Expected:** refused with an error, and the choice is not saved. Solus does not crash.

## Flow 5 — Changing the interpreter marks tools for setup

1. With everything **Ready** (Flow 2), choose a _different_ supported interpreter.
   - [ ] **Expected:** tools show **Needs setup** again (they were built on the old Python).
2. Click **Set up now**, then click **Cancel** while it runs.
   - [ ] **Expected:** the run stops and tools still show **Needs setup**; the marking does not
         disappear.
3. Click **Set up now** and let it finish.
   - [ ] **Expected:** all **Ready**, now showing the new Python version.

## Flow 6 — Failures and Repair

1. **Network failure.** Disconnect from the internet, delete one tool's env folder (for example
   `mcp-envs/kicad`), reopen the section and click **Set up now**.
   - [ ] **Expected:** that tool fails with a message to check the connection and then use
         **Repair**. Tools that were already Ready stay Ready.
2. Reconnect and click **Repair**.
   - [ ] **Expected:** only the failed tool re-runs, and it ends **Ready**.
3. **Tampered environment.** Quit Solus. In `mcp-envs/local/solus-stamp.json` change one character
   of `lock_sha256`. Reopen Solus.
   - [ ] **Expected:** Local shows **Needs setup**, and SOL cannot use the Local tool until
         Repair/Set up. Repair fixes it.
4. **Permissions (macOS/Linux).** Quit Solus, run `chmod 755` on `mcp-envs/code`, and reopen.
   - [ ] **Expected:** Code shows **Needs setup** (the folder is no longer private to you). Setup
         rebuilds it as private (`ls -ld` shows `drwx------`).
5. **Deleted base Python.** If you can safely do so, choose a Python you can temporarily rename,
   set up, quit Solus, rename that Python, and reopen.
   - [ ] **Expected:** tools show **Needs setup** (base missing), not a crash. Rename it back.

## Flow 7 — No usable Python: the managed Python offer

> The managed Python download is **switched off in this build** until real release hashes are
> added (a human gate). This flow checks that the offer and the consent steps work and that the
> download refuses safely.

1. On a machine (or user account) with no Python 3.12/3.13, open the section.
   - [ ] **Expected:** "No Python 3.12 or 3.13 found." and an offer:
         "Install Python for Solus (~30 MB download)".
2. Decline the offer.
   - [ ] **Expected:** the offer closes, and nothing is downloaded.
3. Open the offer again and accept it in the page.
   - [ ] **Expected:** a **native** confirmation dialog from Solus names the download and its
         size.
4. Click Cancel in the native dialog.
   - [ ] **Expected:** nothing runs and no error is shown.
5. Accept in both places.
   - [ ] **Expected (this build):** install fails with a "could not be verified" message, nothing
         is downloaded, and no partial `mcp-python/` folder is left behind.

## Flow 8 — Windows **(Windows)**

1. Run Flows 1, 2 and 6.1–6.3 on Windows 11 with a python.org 3.12 install.
   - [ ] KiCad, Code and Local reach **Ready**; Altium reaches **Ready** if Altium Designer is
         installed (otherwise it still sets up, and SOL reports Altium itself as unavailable).
2. Check the environment folder is private: in PowerShell run
   `icacls "$env:LOCALAPPDATA\Solus\mcp-envs\kicad"`.
   - [ ] **Expected:** only your user and SYSTEM, with no inherited entries.
3. If a Microsoft Store Python is installed, check the list.
   - [ ] **Expected:** it is shown as "Microsoft Store Python is not supported".

## Flow 9 — Linux **(Linux)**

1. Run Flows 1 and 2 on Ubuntu 24.04 with `python3.12`.
   - [ ] Gazebo and Isaac appear (as Needs setup, or Ready after setup).
   - [ ] Envs live under `~/.local/share/solus/mcp-envs/`.

## Cross-feature checks

- [ ] **SOL settings don't erase the Python choice.** After choosing a Python, toggle a SOL
      setting (for example screen intelligence or hotkeys), restart Solus, and confirm the Python
      choice is still selected. (`~/.solus/config.json` keeps both `sol` and `mcp_runtime`.)
- [ ] **Bridge recovery.** After a successful setup the companion restarts by itself. The Bridge
      may show reconnecting for a few seconds, then connected, without you relinking the project.
- [ ] **Events (optional).** With API access, after Flows 2, 4 and 7, the `events` table
      contains `python_tools.interpreter_chosen`, `python_tools.managed_consent` and
      `python_tools.setup_finished`. **No event payload contains a file path.**

## Known limitations (not failures)

- Behind a corporate proxy or a TLS-inspecting firewall, setup fails with a network error (proxy
  settings are not passed through yet).
- The managed Python download is switched off until its hashes are added (Flow 7).
- Windows launchers and the Windows ACL check have not been run on Windows by the developers.
  Flow 8 is their first real test.
