#!/usr/bin/env bash
# run_local.sh  —  CodeReview OpenEnv local development helper
#
# Usage:
#   ./run_local.sh              start server (default)
#   ./run_local.sh test         run pytest suite
#   ./run_local.sh inference    start server + run baseline inference
#   ./run_local.sh docker       docker build + docker run
#   ./run_local.sh all          start server + test + inference

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PORT=7860
IMAGE="${LOCAL_IMAGE_NAME:-code-review-env}"
PID_FILE="/tmp/openenv-cr-pid"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

log()  { printf "[%s] %s\n" "$(date -u +%H:%M:%S)" "$*"; }
ok()   { log "${GREEN}✓${NC} $1"; }
warn() { log "${YELLOW}!${NC} $1"; }
die()  { log "${RED}✗${NC} $1"; exit 1; }

install_deps() {
    log "Installing dependencies..."
    pip install -r "$REPO/requirements.txt" --quiet || die "pip install failed"
    ok "Dependencies ready"
}

start_server() {
    log "Starting server on port $PORT..."
    cd "$REPO"
    PYTHONPATH="$REPO" uvicorn server.app:app \
        --host 0.0.0.0 --port "$PORT" --log-level warning &
    echo $! > "$PID_FILE"
    for i in $(seq 1 15); do
        if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
            ok "Server ready at http://localhost:$PORT"
            ok "Demo UI  → http://localhost:$PORT/"
            ok "API docs → http://localhost:$PORT/docs"
            return 0
        fi
        sleep 1
    done
    die "Server failed to start within 15 seconds"
}

stop_server() {
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        rm -f "$PID_FILE"
        log "Server stopped"
    fi
}

run_tests() {
    log "${BOLD}Running test suite...${NC}"
    cd "$REPO"
    PYTHONPATH="$REPO" python -m pytest tests/ -v --tb=short
    ok "All tests passed"
}

run_inference() {
    log "${BOLD}Running baseline inference...${NC}"
    [ -z "${OPENAI_API_KEY:-}" ] && warn "OPENAI_API_KEY not set — LLM calls will fail"
    cd "$REPO"
    API_BASE_URL="http://localhost:$PORT" \
    MODEL_NAME="${MODEL_NAME:-gpt-4o}" \
    PYTHONPATH="$REPO" python inference.py
}

build_docker() {
    log "Building Docker image: $IMAGE"
    docker build -t "$IMAGE" "$REPO"
    ok "Docker build succeeded"
}

run_docker() {
    log "Running Docker container on port $PORT..."
    docker run --rm -p "$PORT:7860" -e PYTHONUNBUFFERED=1 "$IMAGE"
}

MODE="${1:-server}"
case "$MODE" in
    server)
        install_deps
        trap stop_server EXIT
        start_server
        log "Press Ctrl+C to stop"
        wait
        ;;
    test)
        install_deps
        run_tests
        ;;
    inference)
        install_deps
        trap stop_server EXIT
        start_server
        run_inference
        ;;
    docker)
        build_docker
        run_docker
        ;;
    all)
        install_deps
        trap stop_server EXIT
        start_server
        run_tests
        run_inference
        ok "All done!"
        ;;
    *)
        echo "Usage: $0 [server|test|inference|docker|all]"
        exit 1
        ;;
esac
