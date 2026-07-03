"""ARQ worker entrypoint (ADR-005). Run the connector sync worker with:

    uv run arq solus_api.worker_main.WorkerSettings

Requires the runtime env (SOLUS_REDIS_URL, DB, secret store, GitHub OAuth). Thin
glue around `build_worker_settings`; the task/cron logic lives in
`solus_api.connectors.worker`.
"""

from solus_api.connectors.worker import build_worker_settings
from solus_api.core.config import Settings

# Settings' required fields come from the environment at runtime.
WorkerSettings = build_worker_settings(Settings())  # type: ignore[call-arg]
