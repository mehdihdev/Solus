@echo off
rem integrations\mcp\altium\bin\launch.cmd — Solus-authored ADR-031 entrypoint
rem (human-approved Windows twin of ./launch; Altium itself runs only on
rem Windows, so this is the launcher that actually runs on customer machines).
rem
rem POSTURE PARITY, MINUS env -i: cmd.exe cannot scrub the child environment
rem the way ./launch does, so this script only SETS the pins below and never
rem re-exports anything it inherited.
rem
rem M3 CORRECTION — the Windows child-env floor is NOT empty. The companion
rem launches every vendored server through the MCP SDK's stdio_client, which
rem merges the launch spec's env ON TOP OF get_default_environment(): on
rem Windows that inherited floor is APPDATA, HOMEDRIVE, HOMEPATH, LOCALAPPDATA,
rem PATH, PATHEXT, PROCESSOR_ARCHITECTURE, SYSTEMDRIVE, SYSTEMROOT, TEMP,
rem USERNAME, USERPROFILE (mcp.client.stdio.DEFAULT_INHERITED_ENV_VARS). So
rem solus_companion.supervisor._child_env is NOT a from-scratch scrub on
rem Windows — USERPROFILE and LOCALAPPDATA (both in UPSTREAM_ENV_NEVER_FORWARDED)
rem DO reach the child there. The pins still hold: this script SETS
rem EDA_AGENT_WORKSPACE / EDA_AGENT_POINTER_FILE (and _child_env re-sets them
rem from the spec) to confined paths, and those explicit pins WIN over
rem upstream's USERPROFILE-based machine-global pointer fallback
rem (upstream/src/eda_agent/config.py), so the IPC drop box stays confined
rem regardless of the inherited profile roots. The residual — the inherited
rem Windows floor, plus a non-companion caller handing this script its own
rem unscrubbed environment — is recorded in SECURITY_REVIEW.md.
rem
rem Same guarantees as ./launch otherwise (../tests/test_launch_entrypoint.py):
rem fixed argv, pinned fork-private interpreter, zero network I/O and zero
rem package installation at launch, and the three EDA_AGENT_* pins derived
rem from SOLUS_MCP_WORKSPACE — never inherited — so upstream's machine-global
rem pointer file (C:\ProgramData\eda-agent\workspace-path.txt) is never read,
rem written, or repointed.
setlocal

set "FORK_DIR=%~dp0.."

if "%SOLUS_MCP_WORKSPACE%"=="" (
  echo launch.cmd: SOLUS_MCP_WORKSPACE is not set; refusing to launch without a confined workspace 1>&2
  exit /b 1
)

cd /d "%SOLUS_MCP_WORKSPACE%" || exit /b 1

rem The confined file-drop IPC workspace and pointer file: always inside the
rem Solus workspace, mirroring ./launch and solus\pointer.py exactly.
set "EDA_AGENT_BACKEND=altium"
set "EDA_AGENT_WORKSPACE=%SOLUS_MCP_WORKSPACE%\.eda-agent-ipc"
set "EDA_AGENT_POINTER_FILE=%SOLUS_MCP_WORKSPACE%\.eda-agent-ipc\workspace-path.txt"

"%FORK_DIR%\.venv\Scripts\python.exe" "%FORK_DIR%\solus\server.py"
