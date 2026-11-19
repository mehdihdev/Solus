@echo off
rem integrations\mcp\kicad\bin\launch.cmd — Solus-authored ADR-031 entrypoint
rem (Windows twin of ./launch; SOLUSDEV-329). The companion's _launch_command
rem runs this file instead of ./launch on Windows, and refuses the fork when
rem it is absent — a POSIX shell script is never spawned there.
rem
rem PENDING human security re-review (both devs) — new in SOLUSDEV-329 under
rem the ADR-031 amendment of 2026-11-19; not covered by any existing sign-off.
rem See SECURITY_REVIEW.md.
rem
rem POSTURE PARITY, MINUS env -i: cmd.exe cannot scrub the child environment
rem the way ./launch does, so this script only SETS the pins below and never
rem re-exports anything it inherited. The companion's child-env allowlist
rem (solus_companion.supervisor._child_env) is the authoritative scrub on
rem Windows, on top of the MCP SDK's inherited Windows floor (APPDATA,
rem HOMEDRIVE, HOMEPATH, LOCALAPPDATA, PATH, PATHEXT, PROCESSOR_ARCHITECTURE,
rem SYSTEMDRIVE, SYSTEMROOT, TEMP, USERNAME, USERPROFILE). The KICAD_* knobs
rem ./launch forwards arrive the same way, by name, if the companion passes
rem them; this script never reads them. The residual is recorded in
rem SECURITY_REVIEW.md.
rem
rem PATH: ./launch pins the constant /usr/bin:/bin so the kicad-cli lookup
rem stays off user-controlled search paths. That constant has no Windows
rem equivalent, so the nearest pin is the system directories only
rem (%SystemRoot%\System32;%SystemRoot%), never the inherited PATH.
rem solus\cli_detect.py still prefers the absolute KICAD_CLI_PATH.
rem
rem Same guarantees as ./launch otherwise (../tests/test_launch_entrypoint.py):
rem fixed argv, the interpreter ONLY from SOLUS_MCP_PYTHON (set by the companion
rem after validating the app-data mcp-envs\kicad env; ADR-031 amendment
rem 2026-11-19), zero network I/O and zero package installation at launch, and
rem a refusal when SOLUS_MCP_WORKSPACE is empty.
setlocal

set "FORK_DIR=%~dp0.."

if "%SOLUS_MCP_PYTHON%"=="" (
  echo launch.cmd: SOLUS_MCP_PYTHON is not set; refusing to launch without an interpreter set up by Solus 1>&2
  exit /b 78
)
for %%I in ("%SOLUS_MCP_PYTHON%") do if /i not "%%~fI"=="%SOLUS_MCP_PYTHON%" (
  echo launch.cmd: SOLUS_MCP_PYTHON must be an absolute path; refusing to launch 1>&2
  exit /b 78
)
if not exist "%SOLUS_MCP_PYTHON%" (
  echo launch.cmd: SOLUS_MCP_PYTHON does not exist; refusing to launch 1>&2
  exit /b 78
)
if exist "%SOLUS_MCP_PYTHON%\*" (
  echo launch.cmd: SOLUS_MCP_PYTHON is a directory; refusing to launch 1>&2
  exit /b 78
)

if "%SOLUS_MCP_WORKSPACE%"=="" (
  echo launch.cmd: SOLUS_MCP_WORKSPACE is not set; refusing to launch without a confined workspace 1>&2
  exit /b 1
)

cd /d "%SOLUS_MCP_WORKSPACE%" || exit /b 1

set "PATH=%SystemRoot%\System32;%SystemRoot%"

"%SOLUS_MCP_PYTHON%" "%FORK_DIR%\solus\server.py"
