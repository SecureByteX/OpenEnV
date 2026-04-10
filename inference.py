#!/usr/bin/env python3
"""
inference.py  —  Baseline inference script for CodeReview OpenEnv.

MANDATORY environment variables:
    OPENAI_API_KEY   — OpenAI (or compatible) API key
    API_BASE_URL     — Server base URL  (default: http://localhost:7860)
    MODEL_NAME       — Model identifier (default: gpt-4o)
    HF_TOKEN         — HuggingFace token for private Spaces (optional)
    LOCAL_IMAGE_NAME — Docker image name (optional, for validate-submission.sh)

Required stdout format (one line each, no newlines within a line):
    [START] task=<name> env=<benchmark> model=<model>
    [STEP]  step=<n> action=<json> reward=<0.0001> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> rewards=<r1,r2,...>

Usage:
    export OPENAI_API_KEY=sk-...
    export API_BASE_URL=http://localhost:7860
    export MODEL_NAME=gpt-4o
    python inference.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration (all from environment variables)
# ---------------------------------------------------------------------------

DEFAULT_ENV_BASE_URL = "http://127.0.0.1:7860"
ENV_BASE_URL: str = (
    os.getenv("ENV_BASE_URL")
    or os.getenv("OPENENV_BASE_URL")
    or DEFAULT_ENV_BASE_URL
).rstrip("/")
MODEL_NAME:   str = os.getenv("MODEL_NAME",   "gpt-4o")
LLM_API_KEY:  str = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL: Optional[str] = os.getenv("API_BASE_URL") or os.getenv("OPENAI_BASE_URL")
HF_TOKEN:     str = os.getenv("HF_TOKEN", "")
LOCAL_IMAGE_NAME: str = os.getenv("LOCAL_IMAGE_NAME", "code-review-env")
FAILURE_REWARD = 0.001

ENV_NAME = "code-review-env"
TASKS    = ["simple-bug-detection", "security-audit", "architecture-review"]

client_kwargs: Dict[str, Any] = {"api_key": LLM_API_KEY or "placeholder"}
if LLM_BASE_URL:
    client_kwargs["base_url"] = LLM_BASE_URL
client = OpenAI(**client_kwargs)


def _single_line(value: Any) -> str:
    """Normalize arbitrary values into one validator-safe log token."""
    text = str(value)
    return " ".join(text.split()) if text else "null"


# ---------------------------------------------------------------------------
# Environment HTTP helpers
# ---------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if HF_TOKEN:
        h["Authorization"] = f"Bearer {HF_TOKEN}"
    return h


def env_reset(task_name: str) -> Dict[str, Any]:
    r = requests.post(
        f"{ENV_BASE_URL}/reset",
        json={"task_name": task_name},
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def env_step(action: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(
        f"{ENV_BASE_URL}/step",
        json=action,
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def env_health() -> bool:
    try:
        r = requests.get(f"{ENV_BASE_URL}/health", timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _candidate_env_urls() -> List[str]:
    candidates = [ENV_BASE_URL]
    if ENV_BASE_URL != DEFAULT_ENV_BASE_URL:
        candidates.append(DEFAULT_ENV_BASE_URL)
    return candidates


def ensure_environment() -> Optional[subprocess.Popen]:
    """Return a server process if one was started locally, else None."""
    global ENV_BASE_URL

    for candidate in _candidate_env_urls():
        ENV_BASE_URL = candidate
        if env_health():
            return None

    host = "127.0.0.1"
    port = 7860
    if _port_open(host, port):
        ENV_BASE_URL = DEFAULT_ENV_BASE_URL
        for _ in range(10):
            if env_health():
                return None
            time.sleep(1)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.app:app",
            "--host",
            host,
            "--port",
            str(port),
            "--workers",
            "1",
            "--log-level",
            "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONPATH": os.getcwd()},
    )

    ENV_BASE_URL = DEFAULT_ENV_BASE_URL
    for _ in range(30):
        if env_health():
            return proc
        time.sleep(1)

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return None


# ---------------------------------------------------------------------------
# Agent (LLM reasoning)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior software engineer performing a thorough pull-request code review.

Your goal:
  1. Read all code files carefully.
  2. Identify bugs, security vulnerabilities, race conditions, and design flaws.
  3. Add specific inline comments on the problematic lines.
  4. Submit a final review decision.

Available actions — respond with ONLY a valid JSON object (no markdown, no explanation):

Add an inline comment:
  {"action_type": "add_comment", "line": <int>, "message": "<description>", "severity": "<info|warning|error|critical>"}

Flag a security vulnerability (auto-sets critical severity):
  {"action_type": "flag_security_issue", "line": <int>, "description": "<security issue>"}

Suggest a corrected version:
  {"action_type": "suggest_fix", "line": <int>, "suggestion": "<corrected code>"}

Approve the PR (only when no issues found):
  {"action_type": "approve", "summary": "<rationale>"}

Request changes (when issues found):
  {"action_type": "request_changes", "summary": "<summary of required changes>"}

Critical rules:
  - Lines are 1-indexed.
  - Use "critical" or "error" severity for bugs/security, "warning" for design, "info" for style.
  - Be specific: name the exact variable, function, or pattern causing the problem.
  - You MUST end the episode by calling approve or request_changes.
  - Do NOT approve a PR that has bugs or security vulnerabilities.
  - Review ALL files before making a final decision.
"""


def _build_prompt(obs: Dict[str, Any], turn: int) -> str:
    parts = [
        f"=== CODE REVIEW — Turn {turn} | Task: {obs.get('task_name')} | Step: {obs.get('step')} ===",
        f"PR Title: {obs.get('pr_title', '')}",
        f"Description: {obs.get('pr_description', '')}",
        "",
    ]

    for f in obs.get("files", []):
        parts.append(f"── FILE: {f['filename']} ──────────────────────────────")
        for i, line in enumerate(f["content"].splitlines(), start=1):
            parts.append(f"{i:4d} | {line}")
        parts.append("")

    comments = obs.get("existing_comments", [])
    if comments:
        parts.append("── Your comments so far ────────────────────────────────")
        for c in comments:
            parts.append(f"  Line {c['line']:3d} [{c['severity'].upper()}] {c['message']}")
        parts.append("")

    if obs.get("hint"):
        parts.append(f"⚠ HINT: {obs['hint']}")
    if obs.get("last_action_error"):
        parts.append(f"⚠ LAST ACTION ERROR: {obs['last_action_error']}")
        parts.append("  Please fix your action format and try again.")
    if obs.get("last_action_result"):
        parts.append(f"✓ LAST ACTION: {obs['last_action_result']}")

    parts.append("")
    parts.append("Respond with ONLY a JSON object for your next action.")
    return "\n".join(parts)


def _parse_action(raw: str) -> Dict[str, Any]:
    """Parse LLM response to action dict, with fallback to no_op."""
    text = raw.strip()
    # Strip markdown fences
    if "```" in text:
        for block in text.split("```"):
            block = block.strip().lstrip("json").strip()
            if block.startswith("{"):
                text = block
                break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e])
            except json.JSONDecodeError:
                pass
    return {"action_type": "no_op"}


def get_agent_action(
    obs: Dict[str, Any],
    history: List[Dict],
    turn: int,
) -> tuple[Dict[str, Any], str]:
    """Call LLM and return (action_dict, raw_response)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-6:])  # keep last 3 exchanges
    messages.append({"role": "user", "content": _build_prompt(obs, turn)})

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.1,
        max_tokens=512,
    )
    raw = resp.choices[0].message.content or ""
    return _parse_action(raw), raw


# ---------------------------------------------------------------------------
# Episode runner
# ---------------------------------------------------------------------------

def run_episode(task_name: str) -> None:
    """Run one complete episode and emit required stdout lines."""

    # [START]
    print(f"[START] task={task_name} env={ENV_NAME} model={MODEL_NAME}", flush=True)

    rewards: List[float] = []
    steps: int = 0
    success: bool = False
    history: List[Dict] = []

    try:
        obs = env_reset(task_name)

        for turn in range(1, 999):
            action_dict, raw_text = get_agent_action(obs, history, turn)
            history.append({"role": "assistant", "content": raw_text})

            try:
                result = env_step(action_dict)
                reward = round(float(result["reward"]), 4)
                done   = bool(result["done"])
                obs    = result["observation"]
                err    = obs.get("last_action_error") or None
            except Exception as exc:
                reward, done, err = FAILURE_REWARD, False, _single_line(exc)

            rewards.append(reward)
            steps = turn

            feedback = obs.get("last_action_result") or ""
            if err:
                feedback += f" ERROR: {err}"
            history.append({"role": "user", "content": f"[env] {feedback}"})

            # [STEP]
            action_str = json.dumps(action_dict, separators=(",", ":"))
            error_str  = _single_line(err) if err else "null"
            print(
                f"[STEP] step={turn}"
                f" action={action_str}"
                f" reward={reward:.4f}"
                f" done={'true' if done else 'false'}"
                f" error={error_str}",
                flush=True,
            )

            if done:
                success = reward >= 0.5
                break

    except Exception as exc:
        if not rewards:
            rewards.append(FAILURE_REWARD)
        print(
            f"[STEP] step={steps + 1} action={{}} reward={FAILURE_REWARD:.4f} done=false error={_single_line(exc)}",
            flush=True,
        )

    # [END]
    rewards_str = ",".join(f"{r:.4f}" for r in rewards)
    print(
        f"[END] success={'true' if success else 'false'}"
        f" steps={steps}"
        f" rewards={rewards_str}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    server_proc: Optional[subprocess.Popen] = None
    try:
        server_proc = ensure_environment()
        if not env_health():
            print(
                f"ERROR: Cannot reach environment at {ENV_BASE_URL}",
                file=sys.stderr,
            )
            print(
                "Inference will exit gracefully after failing to initialize the env.",
                file=sys.stderr,
            )
            print(f"[END] success=false steps=0 rewards={FAILURE_REWARD:.4f}", flush=True)
            return

        for task in TASKS:
            run_episode(task)
            time.sleep(1)
    finally:
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    main()
