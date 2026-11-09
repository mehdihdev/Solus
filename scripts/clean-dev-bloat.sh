#!/usr/bin/env bash
# Reclaim disk taken by local dev leftovers: Docker junk, leaked test databases,
# lint/type/test caches, and the pnpm/uv/npm download caches.
#
#   bash scripts/clean-dev-bloat.sh            # dry run: show what would go
#   bash scripts/clean-dev-bloat.sh --yes      # actually clean (safe tier)
#   bash scripts/clean-dev-bloat.sh --yes --deep
#       also: every unused Docker image, anonymous unused volumes, the Swift
#       helper build dir, desktop build output, and the whole npm cache.
#
# Never touched: the dev Postgres volume, the solus / solus_admin / solus_dev*
# databases, node_modules, .venv, git worktrees (only reported).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY=0
DEEP=0
for arg in "$@"; do
  case "$arg" in
    --yes | -y) APPLY=1 ;;
    --deep) DEEP=1 ;;
    -h | --help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
run() { # run a command, or just print it in dry-run mode
  if [ "$APPLY" = 1 ]; then "$@" || echo "   (failed, continuing: $*)"; else echo "   would run: $*"; fi
}
has() { command -v "$1" >/dev/null 2>&1; }
size() { du -sh "$@" 2>/dev/null | sort -rh; }

[ "$APPLY" = 1 ] || echo "DRY RUN — nothing is deleted. Re-run with --yes to clean."

# ---------------------------------------------------------------- Docker
if has docker && docker info >/dev/null 2>&1; then
  say "Docker (before)"
  docker system df
  run docker container prune -f
  run docker builder prune -af
  if [ "$DEEP" = 1 ]; then
    run docker image prune -af   # every image no container uses (re-pulled on demand)
    run docker volume prune -f   # anonymous, unused volumes only — named volumes survive
  else
    run docker image prune -f    # dangling layers only
  fi

  # Leaked per-run test databases (tests recreate them on demand). Plain DROP,
  # no FORCE: a database a test run is still connected to fails and is kept.
  DB_CTR="$(docker compose -f docker-compose.dev.yml ps -q db 2>/dev/null)"
  if [ -n "$DB_CTR" ]; then
    say "Leaked solus_test_* databases"
    PSQL=(docker exec "$DB_CTR" psql -U solus -d postgres -Atq)
    DBS="$("${PSQL[@]}" -c "select datname from pg_database where datname like 'solus\_test\_%' order by 1")"
    if [ -z "$DBS" ]; then
      echo "   none"
    else
      TOTAL="$("${PSQL[@]}" -c "select pg_size_pretty(sum(pg_database_size(datname))) from pg_database where datname like 'solus\_test\_%'")"
      echo "   $(echo "$DBS" | wc -l | tr -d ' ') databases, $TOTAL total"
      while IFS= read -r db; do
        run "${PSQL[@]}" -c "DROP DATABASE \"$db\""
      done <<<"$DBS"
    fi
  else
    echo "   (dev Postgres not running — skipping test-database sweep)"
  fi
else
  say "Docker"
  echo "   engine not running — skipped"
fi

# ---------------------------------------------------------------- Project caches
say "Project caches"
CACHE_DIRS=()
while IFS= read -r d; do CACHE_DIRS+=("$d"); done < <(
  find . \( -name node_modules -o -name .venv -o -name .git -o -path ./.claude/worktrees \) -prune -o \
    -type d \( -name .mypy_cache -o -name .pytest_cache -o -name .ruff_cache -o -name __pycache__ \
    -o -name .hypothesis -o -name htmlcov -o -name .vite -o -name test-results -o -name playwright-report \) \
    -prune -print 2>/dev/null
)
[ -f .coverage ] && CACHE_DIRS+=(./.coverage)
if [ "$DEEP" = 1 ]; then
  for d in apps/desktop/native/solus-input/.build apps/desktop/out apps/desktop/dist apps/desktop/release apps/web/.next; do
    [ -e "$d" ] && CACHE_DIRS+=("./$d")
  done
fi
if [ "${#CACHE_DIRS[@]}" -gt 0 ]; then
  size "${CACHE_DIRS[@]}" | head -15
  echo "   (${#CACHE_DIRS[@]} paths)"
  if [ "$APPLY" = 1 ]; then rm -rf "${CACHE_DIRS[@]}"; else echo "   would remove all ${#CACHE_DIRS[@]} paths"; fi
else
  echo "   nothing to remove"
fi

# ---------------------------------------------------------------- Toolchain caches
say "Toolchain caches"
has pnpm && { size "$(pnpm store path 2>/dev/null)"; run pnpm store prune; }
has uv && { size "$(uv cache dir 2>/dev/null)"; run uv cache prune; }
if has npm; then
  size "$(npm config get cache 2>/dev/null)"
  if [ "$DEEP" = 1 ]; then run npm cache clean --force; else run npm cache verify; fi
fi

# ---------------------------------------------------------------- Report only
say "Worktrees (report only — remove with 'git worktree remove <path>' when done)"
git worktree list --porcelain | awk '/^worktree /{print substr($0,10)}' | while IFS= read -r wt; do
  [ "$wt" = "$ROOT" ] && continue
  printf '   %s\t%s\n' "$(du -sh "$wt" 2>/dev/null | cut -f1)" "$wt"
done

if has orb; then
  say "OrbStack"
  echo "   Freed disk returns to macOS automatically. The VM's RAM (guest page cache)"
  echo "   is only released by restarting it: orb stop && orb start, then"
  echo "   docker compose -f docker-compose.dev.yml up -d db redis"
fi

if [ "$APPLY" = 1 ] && has docker && docker info >/dev/null 2>&1; then
  say "Docker (after)"
  docker system df
fi
