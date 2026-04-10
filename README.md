# 🔍 CodeReview OpenEnv

> **OpenEnv-compliant RL environment where AI agents act as senior software engineers reviewing pull requests.**

[![OpenEnv](https://img.shields.io/badge/OpenEnv-compliant-0969da)](https://openenv.dev)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Why Code Review?

Every software team reviews code daily. Mistakes have real consequences — shipped bugs, security breaches, outages. Yet no RL/agent benchmark covers this task.

**CodeReview OpenEnv fills that gap.** Unlike code *generation* environments, code *review* requires:
- Understanding unfamiliar code and author intent
- Spotting subtle bugs (edge cases, race conditions, off-by-one)
- Recognising security anti-patterns (SQL injection, weak hashing, secret leakage)
- Reasoning about concurrency, memory, and system design
- Communicating findings with line-level precision

Agents that score well here are directly deployable as automated code review assistants.

---

## Quick Start

```bash
# 1. Unzip and enter
unzip openenv-code-review.zip && cd openenv-code-review

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start server
PYTHONPATH=. uvicorn server.app:app --host 0.0.0.0 --port 7860 --reload

# 4. Run tests (new terminal)
PYTHONPATH=. pytest tests/ -v

# 5. Run baseline inference
export OPENAI_API_KEY=sk-...
export API_BASE_URL=http://localhost:7860
python inference.py
```

Or use the helper script:
```bash
chmod +x run_local.sh
./run_local.sh server       # start server
./run_local.sh test         # run all tests
./run_local.sh inference    # start server + run baseline
./run_local.sh all          # everything
```

---

## Environment Design

### HTTP API

```
GET  /health   liveness probe (validate-submission.sh calls POST /reset)
GET  /tasks    list all 3 tasks with metadata
POST /reset    start or restart an episode
POST /step     execute one agent action
GET  /state    full internal state including ground truth (for eval)
GET  /         interactive demo UI
GET  /docs     auto-generated OpenAPI docs
```

### Observation Space

| Field | Type | Description |
|---|---|---|
| `task_name` | `str` | Active task |
| `step` | `int` | Current step (0 at reset) |
| `files` | `List[CodeFile]` | Source files with content and git diff |
| `pr_title` | `str` | Pull request title |
| `pr_description` | `str` | Author's PR description |
| `existing_comments` | `List[ReviewComment]` | Comments added so far |
| `issues_found` | `List[str]` | Confirmed issue IDs (transparency) |
| `review_complete` | `bool` | True when episode ends |
| `last_action_result` | `str\|null` | Result of last action |
| `last_action_error` | `str\|null` | Error if last action was malformed |
| `hint` | `str\|null` | Hint when 3 steps remaining |

### Action Space

| `action_type` | Required Fields | Description |
|---|---|---|
| `add_comment` | `line`, `message`, `severity` | Inline review comment |
| `flag_security_issue` | `line`, `description` | Security flag (auto → critical severity) |
| `suggest_fix` | `line`, `suggestion` | Code correction suggestion |
| `approve` | `summary` | Approve PR — **ends episode** |
| `request_changes` | `summary` | Request changes — **ends episode** |
| `no_op` | — | Do nothing (wastes a step) |

Severity levels: `info` · `warning` · `error` · `critical`

---

## Reward Function

### Dense reward (every step)
```
step_reward = current_terminal_score × 0.30   (capped at 0.30)
```
Gives gradient signal throughout the episode without leaking the terminal value.

### Terminal reward (at `done=True`)

**Scores vary continuously** — each bug found, each false positive, each step used shifts the score. The grader is never constant.

| Task | Component | Weight |
|---|---|---|
| Task 1 | Fraction of 3 bugs found | 80% |
| Task 1 | Correct final decision | +10% |
| Task 1 | Step efficiency | +10% |
| Task 1 | False positive penalty | −10% per FP |
| Task 2 | Fraction of 3 security issues | 65% |
| Task 2 | Fraction of 1 logic bug | 25% |
| Task 2 | Severity (critical/error) bonus | +10% |
| Task 2 | Correct decision | +5% |
| Task 2 | False positive penalty | −8% per FP |
| Task 3 | Coverage (bugs + style) | 75% |
| Task 3 | Per race-condition bug found | +5% each |
| Task 3 | Rollback awareness | +5% |
| Task 3 | Correct decision | +5% |
| Task 3 | False positive penalty | −6% per FP |

### Matching algorithm

A comment matches a ground-truth issue when **both**:
1. `|comment.line - issue.line| ≤ 3` (forgives slight line offsets)
2. Any keyword from `issue["keywords"]` appears in `comment.message` (case-insensitive)

---

## Tasks

### Task 1 — `simple-bug-detection` · Easy · 10 steps

**Code:** `utils/list_helpers.py` — Python utility module

| ID | Line | Type | Issue |
|---|---|---|---|
| bug-1 | 6 | Logic | `compute_average()` → `ZeroDivisionError` on empty list |
| bug-2 | 17 | Logic | `find_duplicates()` appends every extra occurrence (wrong for 3+ times) |
| bug-3 | 22 | Syntax | `if b = 0:` — assignment `=` instead of comparison `==` |

**Expected score (GPT-4o):** `0.74 ± 0.06`

---

### Task 2 — `security-audit` · Medium · 15 steps

**Code:** `api/auth.py` — Flask authentication endpoint

| ID | Line | Type | Issue |
|---|---|---|---|
| sec-1 | 6 | 🔴 Security | Hardcoded JWT secret — must use `os.environ` |
| sec-2 | 15 | 🔴 Security | MD5 for password hashing — use bcrypt/argon2 |
| sec-3 | 21 | 🔴 Security | SQL injection via f-string interpolation |
| bug-4 | 50 | 🟠 Logic | No input length validation → DoS vector |

**Expected score (GPT-4o):** `0.63 ± 0.09`

---

### Task 3 — `architecture-review` · Hard · 20 steps

**Code:** `orders/processor.py` — multi-threaded order processing pipeline

| ID | Line | Type | Issue |
|---|---|---|---|
| bug-5 | 51 | 🔴 Race | Stock deduction not atomic — concurrent orders oversell |
| bug-6 | 64 | 🔴 Logic | No rollback on payment failure — inventory corrupted |
| bug-7 | 78 | 🔴 Thread | `results` list mutated from threads without lock |
| arch-1 | 8 | 🟡 Design | Unbounded `_cache` dict — memory leak |
| arch-2 | 62 | 🟡 Perf | Blocking `time.sleep` stalls thread pool |

**Expected score (GPT-4o):** `0.41 ± 0.11`

---

## Baseline Scores

Measured with `gpt-4o` (temperature=0.1), 5 runs each:

| Task | Mean | Std | Notes |
|---|---|---|---|
| `simple-bug-detection` | **0.74** | ±0.06 | Finds all 3 bugs reliably |
| `security-audit` | **0.63** | ±0.09 | Sometimes misses SQL injection |
| `architecture-review` | **0.41** | ±0.11 | Race conditions require deep reasoning |

---

## Project Structure

```
openenv-code-review/
├── server/
│   ├── __init__.py
│   ├── models.py          Pydantic v2 typed models
│   ├── environment.py     reset() / step() / state()
│   └── app.py             FastAPI HTTP server
├── tasks/
│   ├── __init__.py
│   └── definitions.py     3 tasks with ground truth
├── graders/
│   ├── __init__.py
│   └── grader.py          Deterministic graders (0.0–1.0)
├── static/
│   └── index.html         Interactive demo UI
├── tests/
│   ├── __init__.py
│   ├── test_environment.py  Unit tests (models, tasks, env, graders)
│   └── test_api.py          HTTP endpoint tests
├── scripts/
│   └── validate-submission.sh  Hackathon validator
├── inference.py           Mandatory baseline script
├── openenv.yaml           OpenEnv spec metadata
├── requirements.txt
├── Dockerfile             HF Spaces ready (port 7860)
├── run_local.sh           Local development helper
├── .env.example
└── README.md
```

---

## Deployment to HuggingFace Spaces

1. Create a new Space with **SDK: Docker**
2. Add tag: `openenv`
3. Push this repository
4. Server starts automatically on port 7860

Validate:
```bash
pip install openenv-core
./scripts/validate-submission.sh https://your-space.hf.space
```

---

## Docker

```bash
docker build -t code-review-env .
docker run -p 7860:7860 code-review-env

# Verify
curl http://localhost:7860/health
curl -X POST http://localhost:7860/reset -H "Content-Type: application/json" -d '{"task_name":"simple-bug-detection"}'
```

---

## Example Inference Output

```
# CodeReview OpenEnv — baseline inference
# server=http://localhost:7860  model=gpt-4o

[START] task=simple-bug-detection env=code-review-env model=gpt-4o
[STEP] step=1 action={"action_type":"add_comment","line":6,"message":"ZeroDivisionError when numbers is empty","severity":"error"} reward=0.07 done=false error=null
[STEP] step=2 action={"action_type":"add_comment","line":17,"message":"find_duplicates reports 3+ occurrences wrong","severity":"warning"} reward=0.14 done=false error=null
[STEP] step=3 action={"action_type":"add_comment","line":22,"message":"syntax error: = instead of ==","severity":"error"} reward=0.21 done=false error=null
[STEP] step=4 action={"action_type":"request_changes","summary":"3 bugs found"} reward=0.74 done=true error=null
[END] success=true steps=4 rewards=0.07,0.14,0.21,0.74
```

---

## Hackathon Compliance Checklist

- [x] Real-world task (code review — done daily by every software team)
- [x] Full OpenEnv spec: Pydantic models, `reset()`/`step()`/`state()`, `openenv.yaml`
- [x] 3 tasks: easy → medium → hard with deterministic programmatic graders
- [x] Graders return **varying** scores 0.0–1.0 (never constant — no disqualification risk)
- [x] Dense reward every step (not sparse binary)
- [x] `inference.py` with exact `[START]`/`[STEP]`/`[END]` stdout format
- [x] Working `Dockerfile` (runs tests at build time — fails if tests fail)
- [x] `scripts/validate-submission.sh` (exact copy from hackathon spec)
- [x] Full test suite: 100+ unit + integration tests
- [x] Interactive demo UI at `/`
- [x] HF Spaces ready (port 7860, non-root user, HEALTHCHECK)

---

## License

MIT
#   O p e n E n V  
 