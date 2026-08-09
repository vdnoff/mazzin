#!/bin/bash
# Mazzin rollback — resets main to an earlier commit and force-pushes.
#
# Usage: ~/mazzin/rollback.sh
#
# Destructive. Read the warning it prints before answering.

set -uo pipefail

REPO_DIR="$HOME/mazzin"
WSGI_FILE="/var/www/mazzin_com_wsgi.py"
ERROR_LOG="$HOME/logs/mazzin.com.error.log"
BASE_URL="https://mazzin.com"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'

die() { echo "${RED}ERROR:${NC} $*" >&2; exit 1; }
info() { echo "${GREEN}==>${NC} $*"; }

cd "$REPO_DIR" || die "cannot cd to $REPO_DIR"

git checkout main >/dev/null 2>&1 || die "cannot checkout main"

echo ""
echo "${RED}##############################################################${NC}"
echo "${RED}#                        ROLLBACK                            #${NC}"
echo "${RED}#                                                            #${NC}"
echo "${RED}#  This will HARD RESET main and FORCE PUSH to origin.       #${NC}"
echo "${RED}#  Uncommitted changes will be destroyed.                    #${NC}"
echo "${RED}#  Purchases and events in MySQL are NOT touched.            #${NC}"
echo "${RED}##############################################################${NC}"
echo ""

echo "Recent commits on main:"
git log --oneline -5
echo ""

DEFAULT=$(git rev-list --min-parents=2 --max-count=2 --format='%H' HEAD \
  | grep -v '^commit' | sed -n '2p')
[ -n "$DEFAULT" ] || DEFAULT=$(git rev-parse HEAD~1)

read -r -p "Target commit to reset to [$DEFAULT]: " TARGET
TARGET="${TARGET:-$DEFAULT}"

git rev-parse --verify "$TARGET^{commit}" >/dev/null 2>&1 || die "not a commit: $TARGET"

echo ""
echo "About to reset main to:"
git log --oneline -1 "$TARGET"
echo ""
read -r -p "Type ROLLBACK to confirm: " CONFIRM
[ "$CONFIRM" = "ROLLBACK" ] || die "aborted"

info "Resetting to $TARGET"
git reset --hard "$TARGET" || die "reset failed"

info "Syncing funnel configs to static/"
mkdir -p "$REPO_DIR/static/funnels"
cp "$REPO_DIR"/funnels/*.json "$REPO_DIR/static/funnels/" 2>/dev/null \
  || echo "${YELLOW}!!${NC} no funnel configs to copy"

info "Reloading WSGI app"
touch "$WSGI_FILE" || echo "${YELLOW}!!${NC} could not touch $WSGI_FILE"
sleep 5

info "Health check"
HEALTH_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$BASE_URL/health")
FUNNEL_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$BASE_URL/kitchen")
echo "  /health=$HEALTH_CODE  /kitchen=$FUNNEL_CODE"

if [ "$HEALTH_CODE" != "200" ] || [ "$FUNNEL_CODE" != "200" ]; then
  echo "${RED}Site still unhealthy after rollback.${NC}"
  echo "--- error log tail ---"
  tail -30 "$ERROR_LOG" 2>/dev/null || echo "(no error log at $ERROR_LOG)"
  echo "----------------------"
  echo "Not force-pushing. Investigate, then push manually when the site is up."
  exit 1
fi

info "Force-pushing main"
git push --force-with-lease origin main || die "force push rejected — origin/main moved, re-run after fetching"

echo ""
echo "${GREEN}ROLLED BACK${NC} to $(git log --oneline -1)"
echo "${YELLOW}Reminders:${NC} Cloudflare purge if static changed; test on PHONE."
