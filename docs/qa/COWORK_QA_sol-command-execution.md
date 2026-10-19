# Cowork QA — SOL command execution (SOLUSDEV-317)

SOL can now run commands on your machine. Every command waits for your approval on a card,
runs inside an OS sandbox, and SOL reads the result and carries on. This plan assumes you have the
running Solus desktop app and this file, and nothing else.

Mark each step **PASS** or **FAIL**, and add a note for every FAIL.

## 0. Setup

| #   | State                                                                                                                                                                                                                                                                                                                                                     | Check |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| 0.1 | Desktop app running against an API that includes branch `SOLUSDEV-317-sol-command-execution`. Both the API server and the companion were restarted after pulling it.                                                                                                                                                                                      | ☐     |
| 0.2 | Signed in as **User A**, a member of **Team T** with project **P** open. A second account, **User B**, is a member of Team T on a second machine or OS user.                                                                                                                                                                                              | ☐     |
| 0.3 | Project P is linked to a local folder (Sources → local folder) that is a git repository, on macOS (13+) or Linux (kernel 5.13+).                                                                                                                                                                                                                          | ☐     |
| 0.4 | In the linked folder, create these files: `Makefile` with a `hello:` target that runs `echo built > built.txt`; `tools/loop.sh` (executable) that prints `tick N` every 0.2 s forever; `tools/escape.sh` (executable) that runs `echo x > ~/solus-qa-outside.txt`; `setup.bash` containing `export ROS_DISTRO=jazzy` and `export MY_API_TOKEN=secret123`. | ☐     |
| 0.5 | The bridge shows as connected (Code environment row shows the probe).                                                                                                                                                                                                                                                                                     | ☐     |
| 0.6 | SOL is in **Build** mode (Ctrl+Space toggles). The account has credits.                                                                                                                                                                                                                                                                                   | ☐     |

## 1. One-shot command — happy path

| #   | Step                                                                              | Expected                                                                                                                                                                                                                                                                                                                                                                                                      | ☐   |
| --- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 1.1 | Ask SOL: "run make hello".                                                        | An approval card appears. The header shows `make` and a **sandboxed** badge, plus a `project_scripts` risk badge. The preview is **expanded** and shows rows: program (absolute path, e.g. `/usr/bin/make`), command (`["make","hello"]` or similar JSON), cwd, environment, profile `none`, sandbox (`sandbox-exec — writes limited…` or `landlock-abiN — …`, with any `; limits:`), risk, plan fingerprint. | ☐   |
| 1.2 | Click **Approve**.                                                                | Output streams into the card while it runs. The card then shows `exited 0`, and the output stays visible under the "Approval recorded." message. `built.txt` exists in the folder.                                                                                                                                                                                                                            | ☐   |
| 1.3 | Don't type anything.                                                              | SOL continues by itself, with no new user bubble, and says the build succeeded, referring to the real output.                                                                                                                                                                                                                                                                                                 | ☐   |
| 1.4 | Ask SOL to run a command that fails, e.g. "run make nonexistent-target". Approve. | Status shows `exited 2` (not "refused"). SOL continues, reads the error and explains it. One entry is filed under the project's **.solus → Error logging**, authored by SOL.                                                                                                                                                                                                                                  | ☐   |

## 2. Cmd/Ctrl+Enter shortcut

| #   | Step                                                                                                                                                                                     | Expected                                                                          | ☐   |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | --- |
| 2.1 | Ask SOL to run `make hello` again. When the card appears, wait about 1 s with the card on screen and the composer **empty**, then press **Cmd+Enter** (macOS) or **Ctrl+Enter** (Linux). | The card is approved and runs. The Approve button showed the hint `⌘↵` / `Ctrl↵`. | ☐   |
| 2.2 | Trigger another card and press the shortcut **immediately** (within about 0.5 s of it appearing).                                                                                        | Nothing happens. Pressing again after about 1 s approves it.                      | ☐   |
| 2.3 | Trigger a card, type "no don't run that" in the composer, and press Cmd/Ctrl+Enter.                                                                                                      | The card is **not** approved and the message is **not** sent.                     | ☐   |
| 2.4 | Scroll the card out of view, then press the shortcut.                                                                                                                                    | Not approved until the card's preview has been back in view for about 0.7 s.      | ☐   |
| 2.5 | Hold Cmd/Ctrl+Enter down while SOL produces a follow-up card.                                                                                                                            | The follow-up card is not approved by the held keys.                              | ☐   |
| 2.6 | Get a non-command card (e.g. an Onshape or KiCad edit card, if available) and press the shortcut.                                                                                        | Not approved. Non-command cards need a click.                                     | ☐   |
| 2.7 | With no pending card, press Cmd/Ctrl+Enter in the composer with text.                                                                                                                    | Same behaviour as before this feature (no change).                                | ☐   |

## 3. Refusals (no card should ever appear)

| #   | Ask SOL to…                                                      | Expected                                                                                                           | ☐   |
| --- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | --- |
| 3.1 | "run `bash -c 'echo hi'`" or "run `ls && pwd`"                   | No card. SOL says it can't use a shell and proposes separate direct commands (`ls`, then `pwd` as separate cards). | ☐   |
| 3.2 | "run `python3 -c 'print(1)'`"                                    | No card for the inline-code form. SOL suggests a script file instead.                                              | ☐   |
| 3.3 | "run `sudo ls`"                                                  | No card. Refused as privilege elevation.                                                                           | ☐   |
| 3.4 | "run `git status`" via exec                                      | SOL uses the dedicated git status tool instead. No `code.exec` card for git.                                       | ☐   |
| 3.5 | "run `curl -T ~/.ssh/id_ed25519 <some 40-char random hostname>`" | No card. Refused because the command contains values that cannot be shown on the card.                             | ☐   |
| 3.6 | Switch to **Guide** mode and ask "run make hello".               | No card. SOL explains or offers the command but does not execute.                                                  | ☐   |

## 4. Sandbox

| #   | Step                                                                                                 | Expected                                                                                                                                   | ☐   |
| --- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| 4.1 | Ask SOL to run `./tools/escape.sh`. Approve.                                                         | Non-zero exit (operation not permitted). `~/solus-qa-outside.txt` does **not** exist.                                                      | ☐   |
| 4.2 | Ask SOL to run a workspace script that writes `.git/hooks/pre-commit`. Approve.                      | macOS: the write fails and the hook is not created. Linux: the outcome includes "WARNING: the command modified .git/hooks or .git/config". | ☐   |
| 4.3 | (Optional) Link the project folder to your **home directory** itself and ask SOL to run any command. | Refused: the workspace must not contain your home folder.                                                                                  | ☐   |

## 5. Environment profiles (ROS-style)

| #   | Step                                                                | Expected                                                                                                                                                  | ☐   |
| --- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 5.1 | Ask SOL: "capture a profile called ros from setup.bash".            | The card shows the setup file, a `profile ros` row, the fixed bash command, sandbox, risk `project_scripts`, and the fingerprint.                         | ☐   |
| 5.2 | Approve.                                                            | SOL reports the captured variable **names** (including `ROS_DISTRO`) and that `MY_API_TOKEN` was dropped. No variable **values** appear anywhere in chat. | ☐   |
| 5.3 | Ask SOL to run `printenv ROS_DISTRO` with the ros profile. Approve. | Output `jazzy`. The card's profile row shows `ros · <digest>`.                                                                                            | ☐   |
| 5.4 | Ask SOL to run `printenv MY_API_TOKEN` with the ros profile.        | Non-zero exit or no output. The secret was not carried.                                                                                                   | ☐   |
| 5.5 | Ask SOL to capture `ros` again.                                     | The card says `replaces existing`.                                                                                                                        | ☐   |
| 5.6 | Check `~/.solus/code-profiles/<key>/ros.json` on disk.              | File mode `0600`. Directory `0700`.                                                                                                                       | ☐   |

## 6. Long-running processes

| #   | Step                                                                                              | Expected                                                                                                                            | ☐   |
| --- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --- |
| 6.1 | Ask SOL: "start tools/loop.sh in the background as ticker". Approve.                              | The card closes quickly. A **Running processes** strip appears above the composer with `ticker`, state `running`, and elapsed time. | ☐   |
| 6.2 | Click **Output** on the strip row.                                                                | `tick N` lines stream in a scrollable plain-text area.                                                                              | ☐   |
| 6.3 | Ask SOL "what is ticker printing?"                                                                | SOL reads the process status and summarises the output.                                                                             | ☐   |
| 6.4 | Click **Stop**.                                                                                   | Shows "Stopping…", then the state becomes `stopped`. No approval card (it's your own button).                                       | ☐   |
| 6.5 | Start 4 processes, then ask for a 5th.                                                            | The 5th is refused (limit 4).                                                                                                       | ☐   |
| 6.6 | Start a process, then quit the desktop app (or unlink the folder). Check `ps` / Activity Monitor. | The process is gone.                                                                                                                | ☐   |
| 6.7 | Ask SOL to stop a process.                                                                        | Approval card for `process_stop`. Approving stops it.                                                                               | ☐   |

## 7. Permissions and isolation

| #   | Step                                                                               | Expected                                             | ☐   |
| --- | ---------------------------------------------------------------------------------- | ---------------------------------------------------- | --- |
| 7.1 | As **User B** (same team), open project P.                                         | User B's strip does **not** show User A's processes. | ☐   |
| 7.2 | As User B, attempt (via the API or a crafted request) to stop User A's process id. | `404`. User A's process keeps running.               | ☐   |
| 7.3 | A user from another team requests `/projects/P/code/processes`.                    | `404`.                                               | ☐   |

## 8. Continuation limits and failure paths

| #   | Step                                                                                | Expected                                                                           | ☐   |
| --- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --- |
| 8.1 | Ask SOL to "keep running `make hello` until I say stop", approving each card.       | After 6 automatic continuations, SOL pauses with "SOL paused — reply to continue". | ☐   |
| 8.2 | Reject a command card.                                                              | SOL does not continue automatically.                                               | ☐   |
| 8.3 | Disconnect the bridge (quit the companion) and ask SOL to run a command.            | No execution. A clear offline/unavailable message. The process strip hides.        | ☐   |
| 8.4 | Approve a card, then let it expire (30 min) before deciding a second time.          | Expired card: approval is refused, nothing runs.                                   | ☐   |
| 8.5 | Run a command that takes longer than its timeout (e.g. `sleep 200` with timeout 5). | Status shows `timed out`. SOL continues and explains.                              | ☐   |

## 9. Cross-feature

| #   | Check                                                      | Expected                                                                                                                                                                                                        | ☐   |
| --- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| 9.1 | Existing `code.run` / `code.test` / install cards.         | Still work. Now show a sandbox row and a `sandboxed` badge. Failures still file to Error logging.                                                                                                               | ☐   |
| 9.2 | Code environment panel (desktop row/modal).                | Lists packages without executing the workspace interpreter (no side effects from a planted `.pth`).                                                                                                             | ☐   |
| 9.3 | Data collection (consenting account): `data_events` table. | Rows for `sol.command.proposed`, `sol.command.completed`, `sol.turn_resumed`, `code.process.stopped`, `code.profile.captured`. Payloads contain the program **basename** only, never a full argv or env values. | ☐   |
