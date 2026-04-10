"""
server/app.py
FastAPI HTTP server for CodeReview OpenEnv.

Endpoints:
    GET  /health   liveness probe (validate-submission.sh needs POST /reset 200)
    GET  /tasks    list available tasks
    POST /reset    start/restart episode
    POST /step     execute one action
    GET  /state    full internal state (ground truth visible)
    GET  /docs     OpenAPI docs (auto)
    GET  /         demo UI
"""
from __future__ import annotations
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.environment import CodeReviewEnv
from server.models import Action

app = FastAPI(
    title="CodeReview OpenEnv",
    description=(
        "OpenEnv environment: AI agents review pull requests for bugs and security issues. "
        "POST /reset to start an episode, POST /step to act."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_env = CodeReviewEnv()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ResetRequest(BaseModel):
    task_name: str = "simple-bug-detection"


class StepRequest(BaseModel):
    action_type: str
    filename: Optional[str] = None
    line: Optional[int] = None
    message: Optional[str] = None
    severity: Optional[str] = "warning"
    summary: Optional[str] = None
    description: Optional[str] = None
    suggestion: Optional[str] = None


class StepResponse(BaseModel):
    observation: Dict[str, Any]
    reward: float
    done: bool
    info: Dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    """Liveness probe. Returns 200 OK when server is running."""
    return {"status": "ok", "env": "code-review-env", "version": "1.0.0"}


@app.get("/tasks")
async def list_tasks() -> Dict[str, Any]:
    """List all available tasks."""
    return {
        "tasks": [
            {
                "name": "simple-bug-detection",
                "difficulty": "easy",
                "max_steps": 10,
                "description": (
                    "Find 3 bugs in a Python utility module: "
                    "ZeroDivisionError, logic bug in find_duplicates, "
                    "syntax error (= vs ==)."
                ),
            },
            {
                "name": "security-audit",
                "difficulty": "medium",
                "max_steps": 15,
                "description": (
                    "Find security vulnerabilities in a Flask auth API: "
                    "hardcoded secret key, MD5 password hashing, SQL injection, "
                    "missing input validation."
                ),
            },
            {
                "name": "architecture-review",
                "difficulty": "hard",
                "max_steps": 20,
                "description": (
                    "Find race conditions and design flaws in an order processing pipeline: "
                    "non-atomic stock deduction, missing rollback, thread-unsafe list, "
                    "memory leak, blocking retry."
                ),
            },
        ]
    }


@app.post("/reset")
async def reset(request: ResetRequest = None) -> Dict[str, Any]:
    """Start or restart an episode. Body: {task_name: str}"""
    if request is None:
        request = ResetRequest()
    try:
        obs = _env.reset(task_name=request.task_name)
        return obs.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/step", response_model=StepResponse)
async def step(request: StepRequest) -> StepResponse:
    """Execute one agent action."""
    try:
        action = Action(
            action_type=request.action_type,
            filename=request.filename,
            line=request.line,
            message=request.message,
            severity=request.severity,
            summary=request.summary,
            description=request.description,
            suggestion=request.suggestion,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid action: {exc}")

    # Validate action_type before calling env
    from server.models import VALID_ACTION_TYPES
    if request.action_type not in VALID_ACTION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action_type '{request.action_type}'. "
                   f"Must be one of: {sorted(VALID_ACTION_TYPES)}"
        )

    try:
        obs, reward, done, info = _env.step(action)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return StepResponse(
        observation=obs.model_dump(),
        reward=reward,
        done=done,
        info=info,
    )


@app.get("/state")
async def state() -> Dict[str, Any]:
    """Full internal state including ground truth (for evaluation harnesses)."""
    return _env.state()


# ---------------------------------------------------------------------------
# Static demo UI
# ---------------------------------------------------------------------------

_static = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "static"))

if os.path.isdir(_static):
    app.mount("/static", StaticFiles(directory=_static), name="static")

    @app.get("/", include_in_schema=False)
    async def ui():
        return FileResponse(os.path.join(_static, "index.html"))
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return JSONResponse({
            "name": "CodeReview OpenEnv",
            "docs": "/docs",
            "tasks": "/tasks",
            "reset": "POST /reset",
            "step": "POST /step",
            "state": "GET /state",
            "health": "GET /health",
        })


def main() -> None:
    """Run the API server for local or script-based entry points."""
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "7860"))
    log_level = os.getenv("LOG_LEVEL", "info")
    uvicorn.run("server.app:app", host=host, port=port, workers=1, log_level=log_level)


if __name__ == "__main__":
    main()
