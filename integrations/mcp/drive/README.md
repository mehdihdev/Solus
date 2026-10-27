# drive — SOL uses the mouse and keyboard in an approved window (ADR-041)

A companion builtin (`packages/companion/src/solus_companion/drive/`) that runs the
Solus-built `solus-input` helper (`apps/desktop/native/solus-input/`) at a pinned
path with argument lists only. Tools: `identify`, `capture`, `act`. Every check in
ADR-041 §5 is enforced inside the helper, before every posted event.

`exposure: internal`: these tools never appear in SOL's tool set. The only caller
is the cloud drive executor, which runs after the user approves one `drive.step`
card and stays within that step's budget (sol-drive.md §4).

The server advertises nothing unless the platform is macOS, the helper path
validates, and `SOLUS_COMPANION_DRIVE=1` (set by the desktop only while "SOL can
use your mouse and keyboard" is on). This directory has no third-party code or
launcher.
