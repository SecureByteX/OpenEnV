#!/usr/bin/env bash
#
# scripts/validate-submission.sh — OpenEnv Submission Validator
#
# Usage:
#   ./scripts/validate-submission.sh <hf_space_url> [repo_dir]
#
# Example:
#   ./scripts/validate-submission.sh https://your-team.hf.space
#   ./scripts/validate-submission.sh https://your-team.hf.space /path/to/repo

set -uo pipefail

DOCKER_BUILD_TIMEOUT=600
if [ -t 1 ]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BOLD=''; NC=''
fi

run_with_timeout() {
  local secs="$1"; shift
  if command -v timeout &>/dev/null; then
    timeout "$secs" "$@"
  elif command -v gtimeout &>/dev/null; then
    gtimeout "$secs" "$@"
  else
    "$@" &
    local pid=$!
    ( sleep "$secs" && kill "$pid" 2>/dev/null ) &
    local watcher=$!
    wait "$pid" 2>/dev/null; local rc=$?
    kill "$watcher" 2>/dev/null; wait "$watcher" 2>/dev/null
    return $rc
  fi
}

CLEANUP_FILES=()
cleanup() { rm -f "${CLEANUP_FILES[@]+"${CLEANUP_FILES[@]}"}"; }
trap cleanup EXIT

PING_URL="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${2:-$(dirname "$SCRIPT_DIR")}"

if [ -z "$PING_URL" ]; then
  echo "Usage: $0 <ping_url> [repo_dir]"
  echo "  ping_url   HuggingFace Space URL (e.g. https://your-space.hf.space)"
  exit 1
fi

if ! REPO_DIR="$(cd "$REPO_DIR" 2>/dev/null && pwd)"; then
  echo "Error: directory '$REPO_DIR' not found"
  exit 1
fi

PING_URL="${PING_URL%/}"
PASS=0

log()  { printf "[%s] %b\n" "$(date -u +%H:%M:%S)" "$*"; }
pass() { log "${GREEN}PASSED${NC} -- $1"; PASS=$((PASS + 1)); }
fail() { log "${RED}FAILED${NC} -- $1"; }
hint() { printf "  ${YELLOW}Hint:${NC} %b\n" "$1"; }
stop_at() {
  printf "\n${RED}${BOLD}Stopped at %s.${NC} Fix the above issue and retry.\n" "$1"
  exit 1
}

printf "\n${BOLD}========================================${NC}\n"
printf "${BOLD}  OpenEnv Submission Validator${NC}\n"
printf "${BOLD}========================================${NC}\n"
log "Repo:     $REPO_DIR"
log "Ping URL: $PING_URL"
printf "\n"

# Step 1: Ping HF Space
log "${BOLD}Step 1/3: Pinging HF Space${NC} ($PING_URL/reset) ..."
CURL_OUT="$(mktemp /tmp/validate-XXXXXX)"
CLEANUP_FILES+=("$CURL_OUT")
HTTP_CODE=$(curl -s -o "$CURL_OUT" -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" -d '{}' \
  "$PING_URL/reset" --max-time 30 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
  pass "HF Space is live and /reset returns 200"
elif [ "$HTTP_CODE" = "000" ]; then
  fail "Cannot reach HF Space (connection failed or timed out)"
  hint "Check network and that the Space is running."
  stop_at "Step 1"
else
  fail "/reset returned HTTP $HTTP_CODE (expected 200)"
  hint "Make sure your Space is running. Try: curl -X POST $PING_URL/reset"
  stop_at "Step 1"
fi

# Step 2: Docker build
log "${BOLD}Step 2/3: Running docker build${NC} ..."
if ! command -v docker &>/dev/null; then
  fail "docker not found. Install: https://docs.docker.com/get-docker/"
  stop_at "Step 2"
fi

if [ -f "$REPO_DIR/Dockerfile" ]; then
  DOCKER_CONTEXT="$REPO_DIR"
elif [ -f "$REPO_DIR/server/Dockerfile" ]; then
  DOCKER_CONTEXT="$REPO_DIR/server"
else
  fail "No Dockerfile found in $REPO_DIR"
  stop_at "Step 2"
fi

log "  Dockerfile: $DOCKER_CONTEXT"
BUILD_OK=false
BUILD_OUT=$(run_with_timeout "$DOCKER_BUILD_TIMEOUT" docker build "$DOCKER_CONTEXT" 2>&1) && BUILD_OK=true

if [ "$BUILD_OK" = true ]; then
  pass "Docker build succeeded"
else
  fail "Docker build failed"
  printf "%s\n" "$BUILD_OUT" | tail -20
  stop_at "Step 2"
fi

# Step 3: openenv validate
log "${BOLD}Step 3/3: Running openenv validate${NC} ..."
if ! command -v openenv &>/dev/null; then
  fail "openenv not found. Install: pip install openenv-core"
  stop_at "Step 3"
fi

VALIDATE_OK=false
VALIDATE_OUT=$(cd "$REPO_DIR" && openenv validate 2>&1) && VALIDATE_OK=true

if [ "$VALIDATE_OK" = true ]; then
  pass "openenv validate passed"
  [ -n "$VALIDATE_OUT" ] && log "  $VALIDATE_OUT"
else
  fail "openenv validate failed"
  printf "%s\n" "$VALIDATE_OUT"
  stop_at "Step 3"
fi

printf "\n${BOLD}========================================${NC}\n"
printf "${GREEN}${BOLD}  All 3/3 checks passed!${NC}\n"
printf "${GREEN}${BOLD}  Your submission is ready.${NC}\n"
printf "${BOLD}========================================${NC}\n\n"
exit 0
