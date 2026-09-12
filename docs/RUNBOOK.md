# Runbook — driving Solus end to end

Copy-pasteable steps for everything classified WORKS or WORKS-WITH-SETUP in
[`CAPABILITIES.md`](./CAPABILITIES.md). Every step here is one I ran on 2026-08-15; the
**Traps** are the things that actually cost me time, not hypotheticals.

---

## 0. Bring the stack up

```bash
# 1. Postgres + Redis
make db-up

# 2. Schema. REQUIRED — SOLUS_AUTO_CREATE_TABLES is false, so the API will NOT
#    create tables for itself. A fresh or wiped DB starts empty and every route 500s.
cd packages/api && uv run alembic upgrade head && cd -

# 3. The vendored MCP forks' private virtualenvs (once per checkout)
make mcp-forks

# 4. Every key in the root .env into the SecretStore (once per database; idempotent)
make seed-secrets
#    verify: uv run --package solus-api python scripts/seed-provider-keys.py --check

# 5. Everything: API :8000 + desktop + companion
pnpm dev:all
```

Backend only: `pnpm dev:api`. Health: `curl localhost:8000/readyz` → `database: ok`.

### Traps

- **Nothing auto-loads `.env`.** There is exactly one env file, at the repo root. The API reads it
  through an anchored `env_file` in `core/config.py`, so it works from any cwd — but a shell you
  type commands into does _not_ have those variables unless you `set -a; . ./.env; set +a`.
- **`uvicorn` needs the factory flag:** `uvicorn --factory solus_api.main:create_app`. Without
  `--factory` it fails.
- **Migrate before first start** (step 2). This bit me: with auto-create off, an empty DB gives
  `relation "…" does not exist` on every route.
- **`pnpm install` first in a fresh worktree**, or the desktop typecheck fails on unresolved
  workspace packages.
- **Port 8000 occupied?** An orphaned API from an earlier session survives its terminal.
  `ss -ltnp "sport = :8000"`, then `kill -- -<pgid>`. `pnpm dev:all` now refuses to start and names
  the offender. Do **not** `pkill -f uvicorn` — with `--reload` the worker is a bare `python3` and
  that pattern misses it.
- **Provider keys are SecretStore refs, not env vars.** `ANTHROPIC_API_KEY` in `.env` is only the
  input to step 4; the app reads `anthropic_api_key` from the store. Step 4 needs
  `SOLUS_SECRETS_KEY` set (44-char Fernet) or the store is in-memory and the write lands in the
  wrong process.

---

## 1. Authenticate for API calls

The desktop signs in through Supabase. To drive the API directly, mint a dev token with the same
secret the API validates against:

```bash
TOKEN=$(uv run python - <<'PY'
import os, time, jwt
from dotenv import load_dotenv; load_dotenv("/home/beeboss/Solus/.env")
print(jwt.encode({
  "sub": "<supabase_user_id from the users table>",
  "email": "you@example.com", "email_verified": True,
  "aud": "authenticated", "exp": int(time.time()) + 3600,
}, os.environ["SOLUS_SUPABASE_JWT_SECRET"], algorithm="HS256"))
PY
)
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/users/me
```

`aud` **must** be `authenticated`. A token with any other audience is rejected with a bare 401.
A `sub` that does not exist yet auto-provisions a new user, personal team and 14-day trial on first
request — which is also how you make a second tenant for isolation testing.

---

## 2. SOL — a real turn

> SOL answers from the REAL W0-07 feeds (SYS-04, `agent/feeds.py`): your project's graph,
> the live telemetry buffer, and SYS-02 retrieval — project-scoped in-query, and honestly
> empty where no data exists. Verified 2026-08-15: a turn against the 243-entity Onshape
> project cited its actual Kinova Gen3 parts and invoked real Onshape tools.

```bash
P=<project_id>
CONV=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"demo"}' "localhost:8000/api/v1/projects/$P/sol/conversations" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["id"])')

curl -sN -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"What are the main components in this project?"}' \
  "localhost:8000/api/v1/projects/$P/sol/conversations/$CONV/messages"
```

Streams SSE: `event: token` … `event: message` … `event: done`. Guide/Expert narration follows the
per-user SOL mode (ADR-016).

---

## 3. Live Bench telemetry

```bash
P=<project_id>
# device_id must match a graph entity's external_ref for resolution to succeed
EXT=$(docker exec solus-db-1 psql -U solus -d solus -tAc \
  "select external_ref from graph_entity where project_id='$P' and external_ref is not null limit 1;")

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "{
  \"packets\":[{\"schema_version\":1,\"device_id\":\"$EXT\",\"ts_us\":1786806000000000,
                \"values\":{\"temp_c\":41.5,\"rpm\":120.0},\"units\":{\"temp_c\":\"C\"},\"seq\":1}],
  \"events\":[{\"kind\":\"threshold_breach\",\"device_id\":\"$EXT\",\"signal\":\"temp_c\",
               \"at\":\"2026-08-15T15:01:00Z\",\"value\":95.0,\"detail\":{\"limit\":80}}]
}" "localhost:8000/api/v1/projects/$P/bench/telemetry"
# -> {"accepted":1,"unresolved":0,"rejected":0}

ENTITY=$(docker exec solus-db-1 psql -U solus -d solus -tAc \
  "select id from graph_entity where project_id='$P' and external_ref='$EXT';")
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/v1/projects/$P/bench/recent/$ENTITY"
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/v1/projects/$P/bench/summary?duration_seconds=3600"
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/v1/projects/$P/bench/events"
```

### Traps

- **The body is the WIRE shape, not the model shape.** The timestamp field is **`ts_us`**
  (microseconds since epoch) — a packet with `timestamp` is silently counted in `"rejected"` with
  no reason given. Canonical shape:
  `{schema_version, device_id, ts_us, values, seq, units}`.
- **`duration_seconds` is required and capped at 3600.** Omitting it is a 422; 86400 is a 422.
- `"unresolved"` (rather than `"rejected"`) means the packet parsed but `device_id` matched no
  entity's `external_ref`.
- To debug a rejection, decode locally — it gives a real message:
  ```bash
  uv run python -c "from solus_api.graph.codec import from_wire; from_wire({...})"
  # PacketDecodeError: packet is missing ts_us
  ```

---

## 4. MuJoCo simulation

```bash
uv run python - <<'PY'
import asyncio, sys
from datetime import datetime, UTC
sys.path.insert(0, "livebench/src")
from livebench.sim.mujoco_source import MuJoCoPacketSource
XML = """<mujoco model="pendulum"><option gravity="0 0 -9.81"/><worldbody>
  <body name="arm" pos="0 0 1"><joint name="hinge" type="hinge" axis="0 1 0"/>
  <geom name="rod" type="capsule" fromto="0 0 0 0.5 0 0" size="0.02" mass="1"/>
</body></worldbody></mujoco>"""
async def main():
    src = MuJoCoPacketSource(XML, scene_name="pendulum",
        start_time=datetime(2026,8,15,15,0,0,tzinfo=UTC), sample_hz=50.0, duration_seconds=0.5)
    async for p in src.__aiter__():
        print(p.timestamp.strftime("%S.%f")[:6], {k: round(v,4) for k,v in p.values.items()})
    await src.aclose()
asyncio.run(main())
PY
```

Emits LB-06 packets (`device_id="<scene>/<joint>"`, `values={qpos,qvel}`) that POST unchanged to
the telemetry endpoint above. Use a **horizontal** rod: a vertical one sits at equilibrium and
every value stays 0.0, which looks like a broken stream.

---

## 5. Robot detection (RBT-01)

```bash
uv run python -c "
import sys; sys.path.insert(0,'livebench/src')
from livebench.recognition.passive import enumerate_usb_serial
for p in enumerate_usb_serial(): print(p)"
```

With the CH343 on this bench it reports the bridge and `mcu_known=False` at confidence 0.3. That is
the correct answer, not a failure — a USB-serial bridge carries no identity for the MCU behind it.
Needs membership of the `dialout` group (or the device world-readable) to enumerate.

---

## 6. The bridge and the MCP forks

```bash
make mcp-forks     # once; hash-verified installs into each fork's .venv
pnpm dev:all
```

Success looks like, in the `dev:all` log:

```
WebSocket /api/v1/projects/{id}/bridge   [accepted]
connection open
kicad overlay: registered [7 tools]
```

### Traps

- **`make mcp-forks` uses `python -m venv --copies`, not `uv venv`,** deliberately: uv symlinks the
  interpreter to the system python and the companion refuses it
  (_"REFUSED private interpreter … resolves outside"_). It must be a real copy inside the tree.
- The companion **does not spawn until a project is selected** — its bridge URL is project-scoped
  and baked in at spawn. No project ⇒ no companion ⇒ "Bridge offline".
- `altium` will fail with `SOLUS_MCP_WORKSPACE is not set`; `fusion` needs Autodesk Fusion running
  locally on `127.0.0.1:27182`; `autocad`/`solidworks` are Windows-only. All three are expected.

---

## 7. Onshape

Already connected on this machine (`sources.type=onshape`, `status=connected`, 243 parts). To
repeat from scratch: connect through the desktop Integrations panel, complete the OAuth grant in
the browser, then sync. Verify:

```bash
docker exec solus-db-1 psql -U solus -d solus -c \
  "select type,status from sources; select count(*) from graph_entity;"
```

Requires `SOLUS_ONSHAPE_CLIENT_ID` / `SOLUS_ONSHAPE_CLIENT_SECRET` in the root `.env`.

---

## 8. Reading the graph

```bash
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/v1/projects/$P/entities" | head -c 400
E=<entity_id>
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/v1/projects/$P/graph?root=$E&depth=1"
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/v1/projects/$P/entities/$E/relations"
```

`depth` is capped at 2 server-side. Impact traversal exists as a Python module but has **no HTTP
route** — it is not drivable from the app today.

---

## 9. Tearing down cleanly

```bash
# dev:all: Ctrl+C tears the whole tree down (process-group kill)
# If something was orphaned:
ss -ltnp "sport = :8000"           # find the holder
kill -- -<pgid>                    # kill the group, not the pid
```

Never leave a background `pytest` running: the Stop-gate hook runs the full suite against the same
per-checkout test database and the two collide into unrelated-looking failures.
