#!/bin/bash
# Mazzin deploy — standalone (adapted from the FG Manager deploy.sh v2.1 pattern).
#
# Usage: ~/mazzin/deploy.sh claude/<branch> "description"
#
# Merges a claude/* branch into main on the server, refreshes the CDN copy of
# the funnel configs, reloads the WSGI app and health-checks it. On failure it
# tells you to run rollback.sh — it does not try to be clever.

set -uo pipefail

REPO_DIR="$HOME/mazzin"
LOCK_FILE="$REPO_DIR/.deploy.lock"
BACKUP_DIR="$HOME/mazzin_backups"
WSGI_FILE="/var/www/mazzin_com_wsgi.py"
ERROR_LOG="$HOME/logs/mazzin.com.error.log"
BASE_URL="https://mazzin.com"
LOCK_MAX_AGE=600   # seconds

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'

die() { echo "${RED}ERROR:${NC} $*" >&2; exit 1; }
info() { echo "${GREEN}==>${NC} $*"; }
warn() { echo "${YELLOW}!!${NC} $*"; }

BRANCH="${1:-}"
DESCRIPTION="${2:-}"

[ -n "$BRANCH" ] || die "usage: deploy.sh claude/<branch> \"description\""
[ -n "$DESCRIPTION" ] || die "usage: deploy.sh claude/<branch> \"description\""

case "$BRANCH" in
  claude/*) ;;
  *) die "branch must start with claude/ (got: $BRANCH)" ;;
esac

cd "$REPO_DIR" || die "cannot cd to $REPO_DIR"

# --- lock -----------------------------------------------------------------
if [ -f "$LOCK_FILE" ]; then
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  if [ "$LOCK_AGE" -lt "$LOCK_MAX_AGE" ]; then
    die "another deploy is running (lock is ${LOCK_AGE}s old). Wait or remove $LOCK_FILE"
  fi
  warn "stale lock (${LOCK_AGE}s old) — removing"
  rm -f "$LOCK_FILE"
fi

echo "$$ $(date -Iseconds) $BRANCH" > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# --- fetch + pre-flight ---------------------------------------------------
info "Fetching origin"
git fetch origin --prune || die "git fetch failed"

git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1 || die "origin/$BRANCH does not exist"

BEHIND=$(git rev-list --count "origin/$BRANCH..origin/main")
if [ "$BEHIND" -gt 0 ]; then
  die "$BRANCH is $BEHIND commit(s) behind origin/main.
Rebase it first:
  git checkout $BRANCH
  git fetch origin
  git rebase origin/main
  git push --force-with-lease origin $BRANCH
Then re-run this script."
fi

# --- backup ---------------------------------------------------------------
info "Backing up database"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d)
BACKUP_FILE="$BACKUP_DIR/mazzin_${STAMP}.sql.gz"

if [ -f "$REPO_DIR/.env" ]; then
  # shellcheck disable=SC1091
  set -a; . "$REPO_DIR/.env"; set +a
fi

if [ -n "${DB_HOST:-}" ] && [ -n "${DB_USER:-}" ] && [ -n "${DB_NAME:-}" ]; then
  if [ -f "$BACKUP_FILE" ]; then
    info "Backup for $STAMP already exists — skipping"
  else
    mysqldump -h "$DB_HOST" -u "$DB_USER" -p"${DB_PASSWORD:-}" \
      --single-transaction --quick "$DB_NAME" 2>/dev/null | gzip > "$BACKUP_FILE" \
      || die "mysqldump failed — aborting before touching main"
    info "Backup written: $BACKUP_FILE"
  fi
  ls -1t "$BACKUP_DIR"/mazzin_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
else
  warn "DB credentials not in .env — skipping backup"
fi

# --- merge ----------------------------------------------------------------
info "Checking out main"
git checkout main || die "cannot checkout main"
git pull origin main || die "git pull failed"

info "Merging $BRANCH"
git merge --no-ff "origin/$BRANCH" -m "Merge $BRANCH: $DESCRIPTION" \
  || die "merge conflict — resolve manually, nothing has been deployed"

# --- static sync + reload -------------------------------------------------
info "Syncing funnel configs to static/"
mkdir -p "$REPO_DIR/static/funnels"
cp "$REPO_DIR"/funnels/*.json "$REPO_DIR/static/funnels/" || die "funnel copy failed"

info "Reloading WSGI app"
touch "$WSGI_FILE" || warn "could not touch $WSGI_FILE"
sleep 5

# --- health check ---------------------------------------------------------
info "Health check"
HEALTH_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$BASE_URL/health")
FUNNEL_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$BASE_URL/kitchen")

if [ "$HEALTH_CODE" != "200" ] || [ "$FUNNEL_CODE" != "200" ]; then
  echo "${RED}HEALTH CHECK FAILED${NC} (/health=$HEALTH_CODE /kitchen=$FUNNEL_CODE)"
  echo "--- error log tail ---"
  tail -30 "$ERROR_LOG" 2>/dev/null || echo "(no error log at $ERROR_LOG)"
  echo "----------------------"
  echo "${RED}main has been merged locally but NOT pushed.${NC}"
  echo "Run: ~/mazzin/rollback.sh"
  exit 1
fi

info "Health check OK (/health=200 /kitchen=200)"

# --- publish --------------------------------------------------------------
info "Pushing main"
git push origin main || die "push failed — site is live on merged code but origin/main is stale"

info "Updating CHANGELOG.md"
{
  echo ""
  echo "## $(date +%Y-%m-%d) — $BRANCH"
  echo "- $DESCRIPTION"
} >> "$REPO_DIR/CHANGELOG.md"

git add CHANGELOG.md
git commit -m "changelog: $DESCRIPTION" && git push origin main \
  || warn "changelog commit/push failed (deploy itself succeeded)"

echo ""
echo "--- error log tail ---"
tail -20 "$ERROR_LOG" 2>/dev/null || echo "(no error log at $ERROR_LOG)"
echo "----------------------"
echo ""
echo "${GREEN}DEPLOYED:${NC} $BRANCH — $DESCRIPTION"
echo ""
echo "${YELLOW}Reminders:${NC}"
echo "  1. Sync Project Knowledge"
echo "  2. Cloudflare purge if static changed"
echo "  3. Test on PHONE"
