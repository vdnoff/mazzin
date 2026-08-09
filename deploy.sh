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
ERROR_LOG="/var/log/mazzin.com.error.log"
BASE_URL="https://mazzin.com"
LOCK_MAX_AGE=600         # seconds
HEALTH_ATTEMPTS=3        # a cold start after the WSGI reload is not a failure
HEALTH_RETRY_WAIT=5      # seconds between attempts

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'

die() { echo "${RED}ERROR:${NC} $*" >&2; exit 1; }
info() { echo "${GREEN}==>${NC} $*"; }
warn() { echo "${YELLOW}!!${NC} $*"; }

probe() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$1"
}

# curl reports 000 when it got no HTTP response at all — a timeout or a
# refused connection. That is a different situation from the app answering
# with an error code, and on this host it usually just means the first
# request after a reload is still paying for the cold start.
# $1 code, $2 label, $3 "1" when another attempt follows
describe_code() {
  if [ "$1" != "000" ]; then
    echo "$2=HTTP $1"
  elif [ "${3:-0}" = "1" ]; then
    echo "$2=no response (curl 000) — likely transient; retrying"
  else
    echo "$2=no response (curl 000)"
  fi
}

# Read one key out of .env as a literal string.
#
# .env is never sourced. Sourcing runs the file as shell, which both aborts
# under `set -u` on any value referencing an unset name and silently mangles
# values containing `$` — and our database name is literally FarvaGO$mazzin,
# which a sourced .env would truncate to FarvaGO. Reading the line ourselves
# keeps the value exactly as written and leaves the Stripe keys out of the
# environment of every child process.
#
# Handles a leading `export `, surrounding single or double quotes, and CRLF
# line endings. Inline `# comments` after a value are NOT stripped — a `#` is
# treated as part of the value, since passwords may contain one.
env_value() {
  local key="$1" file="$REPO_DIR/.env" value
  [ -f "$file" ] || return 0
  value=$(sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}${key}=//p" "$file" | tail -n 1)
  value=${value%$'\r'}
  case "$value" in
    '"'*'"') value=${value#\"}; value=${value%\"} ;;
    "'"*"'") value=${value#\'}; value=${value%\'} ;;
  esac
  printf '%s' "$value"
}

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

DB_HOST=""; DB_USER=""; DB_PASSWORD=""; DB_NAME=""
for key in DB_HOST DB_USER DB_PASSWORD DB_NAME; do
  printf -v "$key" '%s' "$(env_value "$key")"
done

if [ -n "$DB_HOST" ] && [ -n "$DB_USER" ] && [ -n "$DB_NAME" ]; then
  if [ -f "$BACKUP_FILE" ]; then
    info "Backup for $STAMP already exists — skipping"
  else
    mysqldump -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" \
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

PRE_MERGE=$(git rev-parse HEAD)

info "Merging $BRANCH"
git merge --no-ff "origin/$BRANCH" -m "Merge $BRANCH: $DESCRIPTION" \
  || die "merge conflict — resolve manually, nothing has been deployed"

# Dependencies are never installed automatically — that is a decision for a
# human at a shell, not for a deploy script running unattended.
REQS_CHANGED=0
if ! git diff --quiet "$PRE_MERGE" HEAD -- requirements.txt; then
  REQS_CHANGED=1
  echo ""
  echo "${YELLOW}##############################################################${NC}"
  echo "${YELLOW}#  requirements.txt CHANGED IN THIS MERGE                     #${NC}"
  echo "${YELLOW}#                                                            #${NC}"
  echo "${YELLOW}#  Nothing has been installed. Run this, then reload:         #${NC}"
  echo "${YELLOW}#                                                            #${NC}"
  echo "${YELLOW}#    workon mazzin && pip install -r requirements.txt         #${NC}"
  echo "${YELLOW}#                                                            #${NC}"
  echo "${YELLOW}#  Until you do, the health check below may fail on a         #${NC}"
  echo "${YELLOW}#  missing or outdated package.                               #${NC}"
  echo "${YELLOW}##############################################################${NC}"
  echo ""
  git --no-pager diff "$PRE_MERGE" HEAD -- requirements.txt | sed -n '5,40p'
  echo ""
fi

# --- static sync + reload -------------------------------------------------
info "Syncing funnel configs to static/"
mkdir -p "$REPO_DIR/static/funnels"
cp "$REPO_DIR"/funnels/*.json "$REPO_DIR/static/funnels/" || die "funnel copy failed"

info "Reloading WSGI app"
touch "$WSGI_FILE" || warn "could not touch $WSGI_FILE"
sleep 5

# --- health check ---------------------------------------------------------
info "Health check"

HEALTH_OK=0
ATTEMPT=1
while [ "$ATTEMPT" -le "$HEALTH_ATTEMPTS" ]; do
  HEALTH_CODE=$(probe "$BASE_URL/health")
  FUNNEL_CODE=$(probe "$BASE_URL/kitchen")

  if [ "$HEALTH_CODE" = "200" ] && [ "$FUNNEL_CODE" = "200" ]; then
    HEALTH_OK=1
    info "Health check OK on attempt $ATTEMPT (/health=200 /kitchen=200)"
    break
  fi

  MORE=0
  [ "$ATTEMPT" -lt "$HEALTH_ATTEMPTS" ] && MORE=1
  warn "Attempt $ATTEMPT/$HEALTH_ATTEMPTS: $(describe_code "$HEALTH_CODE" /health "$MORE"), $(describe_code "$FUNNEL_CODE" /kitchen "$MORE")"
  if [ "$MORE" -eq 1 ]; then
    sleep "$HEALTH_RETRY_WAIT"
  fi
  ATTEMPT=$((ATTEMPT + 1))
done

if [ "$HEALTH_OK" -ne 1 ]; then
  echo "${RED}HEALTH CHECK FAILED${NC} after $HEALTH_ATTEMPTS attempts (/health=$HEALTH_CODE /kitchen=$FUNNEL_CODE)"
  if [ "$REQS_CHANGED" -eq 1 ]; then
    echo "${YELLOW}requirements.txt changed in this merge — missing dependencies are the"
    echo "first thing to rule out. Install them and re-run this script.${NC}"
  fi
  echo "--- error log tail ---"
  tail -30 "$ERROR_LOG" 2>/dev/null || echo "(no error log at $ERROR_LOG)"
  echo "----------------------"
  echo "${RED}main has been merged locally but NOT pushed.${NC}"
  echo "If the site is actually serving, re-run this script — the merge is"
  echo "already in place, so it will re-check and finish the deploy."
  echo "Otherwise: ~/mazzin/rollback.sh"
  exit 1
fi

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
if [ "$REQS_CHANGED" -eq 1 ]; then
  echo "  4. ${YELLOW}requirements.txt changed — run: workon mazzin && pip install -r requirements.txt, then reload${NC}"
fi
