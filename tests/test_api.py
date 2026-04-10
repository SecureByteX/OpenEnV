"""
tests/test_api.py
HTTP endpoint tests using FastAPI TestClient (no network needed).

Run:  PYTHONPATH=. pytest tests/test_api.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /health and /tasks
# ---------------------------------------------------------------------------

class TestMetaEndpoints:
    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_body_correct(self):
        b = client.get("/health").json()
        assert b["status"] == "ok"
        assert b["env"] == "code-review-env"
        assert "version" in b

    def test_tasks_returns_200(self):
        assert client.get("/tasks").status_code == 200

    def test_tasks_has_exactly_3(self):
        assert len(client.get("/tasks").json()["tasks"]) == 3

    def test_tasks_names_correct(self):
        names = [t["name"] for t in client.get("/tasks").json()["tasks"]]
        assert "simple-bug-detection" in names
        assert "security-audit" in names
        assert "architecture-review" in names

    def test_tasks_have_valid_difficulties(self):
        for t in client.get("/tasks").json()["tasks"]:
            assert t["difficulty"] in ("easy", "medium", "hard")

    def test_tasks_have_max_steps(self):
        for t in client.get("/tasks").json()["tasks"]:
            assert isinstance(t["max_steps"], int)
            assert t["max_steps"] > 0


# ---------------------------------------------------------------------------
# POST /reset
# ---------------------------------------------------------------------------

class TestResetEndpoint:
    def test_reset_default_task(self):
        r = client.post("/reset", json={})
        assert r.status_code == 200
        assert r.json()["task_name"] == "simple-bug-detection"

    def test_reset_explicit_task(self):
        r = client.post("/reset", json={"task_name": "security-audit"})
        assert r.status_code == 200
        assert r.json()["task_name"] == "security-audit"

    def test_reset_step_is_zero(self):
        r = client.post("/reset", json={})
        assert r.json()["step"] == 0

    def test_reset_no_existing_comments(self):
        r = client.post("/reset", json={})
        assert r.json()["existing_comments"] == []

    def test_reset_review_not_complete(self):
        r = client.post("/reset", json={})
        assert r.json()["review_complete"] is False

    def test_reset_has_files(self):
        r = client.post("/reset", json={})
        files = r.json()["files"]
        assert len(files) >= 1
        assert files[0]["content"].strip() != ""

    def test_reset_has_pr_metadata(self):
        r = client.post("/reset", json={"task_name": "architecture-review"})
        b = r.json()
        assert b["pr_title"] != ""
        assert b["pr_description"] != ""

    def test_reset_invalid_task_returns_400(self):
        r = client.post("/reset", json={"task_name": "completely-fake-task"})
        assert r.status_code == 400

    def test_reset_all_three_tasks_succeed(self):
        for name in ("simple-bug-detection", "security-audit", "architecture-review"):
            r = client.post("/reset", json={"task_name": name})
            assert r.status_code == 200, f"Reset failed for task '{name}'"
            assert r.json()["task_name"] == name


# ---------------------------------------------------------------------------
# POST /step
# ---------------------------------------------------------------------------

class TestStepEndpoint:
    def setup_method(self):
        """Reset to a clean state before each test."""
        client.post("/reset", json={"task_name": "simple-bug-detection"})

    def test_no_op_returns_200(self):
        r = client.post("/step", json={"action_type": "no_op"})
        assert r.status_code == 200

    def test_step_response_has_required_fields(self):
        r = client.post("/step", json={"action_type": "no_op"}).json()
        assert "observation" in r
        assert "reward" in r
        assert "done" in r
        assert "info" in r

    def test_reward_is_float_in_range(self):
        r = client.post("/step", json={"action_type": "no_op"}).json()["reward"]
        assert isinstance(r, float)
        assert 0.0 <= r <= 1.0

    def test_step_counter_increments(self):
        r = client.post("/step", json={"action_type": "no_op"}).json()
        assert r["observation"]["step"] == 1

    def test_done_false_for_no_op(self):
        r = client.post("/step", json={"action_type": "no_op"}).json()
        assert r["done"] is False

    def test_add_comment_stored_in_observation(self):
        r = client.post("/step", json={
            "action_type": "add_comment",
            "line": 6,
            "message": "ZeroDivisionError when list is empty",
            "severity": "error",
        }).json()
        comments = r["observation"]["existing_comments"]
        assert len(comments) == 1
        assert comments[0]["line"] == 6
        assert comments[0]["severity"] == "error"

    def test_add_comment_missing_line_error_in_obs(self):
        r = client.post("/step", json={
            "action_type": "add_comment",
            "message": "something wrong",
        }).json()
        assert r["observation"]["last_action_error"] is not None

    def test_add_comment_missing_message_error_in_obs(self):
        r = client.post("/step", json={
            "action_type": "add_comment",
            "line": 5,
        }).json()
        assert r["observation"]["last_action_error"] is not None

    def test_flag_security_sets_critical_severity(self):
        client.post("/reset", json={"task_name": "security-audit"})
        r = client.post("/step", json={
            "action_type": "flag_security_issue",
            "line": 6,
            "description": "Hardcoded secret key in source code",
        }).json()
        comments = r["observation"]["existing_comments"]
        assert len(comments) == 1
        assert comments[0]["severity"] == "critical"

    def test_flag_security_missing_description_error(self):
        client.post("/reset", json={"task_name": "security-audit"})
        r = client.post("/step", json={
            "action_type": "flag_security_issue",
            "line": 6,
        }).json()
        assert r["observation"]["last_action_error"] is not None

    def test_suggest_fix_adds_comment(self):
        r = client.post("/step", json={
            "action_type": "suggest_fix",
            "line": 6,
            "suggestion": "if not numbers: return 0.0",
        }).json()
        comments = r["observation"]["existing_comments"]
        assert len(comments) == 1
        assert "suggest" in comments[0]["message"].lower()

    def test_approve_ends_episode(self):
        r = client.post("/step", json={"action_type": "approve", "summary": "LGTM"}).json()
        assert r["done"] is True

    def test_request_changes_ends_episode(self):
        r = client.post("/step", json={
            "action_type": "request_changes", "summary": "bugs found"
        }).json()
        assert r["done"] is True

    def test_invalid_action_type_returns_422(self):
        r = client.post("/step", json={"action_type": "totally_invalid_action"})
        assert r.status_code == 422

    def test_partial_rewards_capped_at_0_30(self):
        for line, msg in (
            (6, "zero division empty list"),
            (17, "duplicate multiple times set"),
        ):
            r = client.post("/step", json={
                "action_type": "add_comment",
                "line": line,
                "message": msg,
                "severity": "error",
            }).json()
            if not r["done"]:
                assert r["reward"] <= 0.31, f"Partial reward {r['reward']} exceeds 0.30 cap"

    def test_terminal_reward_higher_than_partials(self):
        client.post("/reset", json={"task_name": "simple-bug-detection"})
        partial_rewards = []
        for line, msg in (
            (6,  "zero division error empty list"),
            (17, "duplicate multiple times set 3+"),
            (22, "syntax = assignment instead of == comparison"),
        ):
            r = client.post("/step", json={
                "action_type": "add_comment",
                "line": line,
                "message": msg,
                "severity": "error",
            }).json()
            if not r["done"]:
                partial_rewards.append(r["reward"])

        final = client.post("/step", json={
            "action_type": "request_changes",
            "summary": "three bugs found",
        }).json()["reward"]

        for p in partial_rewards:
            assert p <= 0.31
        assert final >= 0.50

    def test_multiple_comments_accumulate(self):
        for line, msg in ((6, "zero division"), (17, "duplicate set"), (22, "syntax ==")):
            client.post("/step", json={
                "action_type": "add_comment",
                "line": line,
                "message": msg,
                "severity": "error",
            })
        r = client.post("/step", json={"action_type": "no_op"}).json()
        assert len(r["observation"]["existing_comments"]) == 3


# ---------------------------------------------------------------------------
# GET /state
# ---------------------------------------------------------------------------

class TestStateEndpoint:
    def test_state_after_reset(self):
        client.post("/reset", json={"task_name": "simple-bug-detection"})
        s = client.get("/state").json()
        assert s["task_name"] == "simple-bug-detection"
        assert s["step"] == 0
        assert s["done"] is False

    def test_state_has_ground_truth(self):
        client.post("/reset", json={"task_name": "simple-bug-detection"})
        s = client.get("/state").json()
        assert "ground_truth_bugs" in s
        assert len(s["ground_truth_bugs"]) == 3

    def test_state_updates_after_step(self):
        client.post("/reset", json={"task_name": "simple-bug-detection"})
        client.post("/step", json={
            "action_type": "add_comment",
            "line": 6,
            "message": "zero division",
            "severity": "error",
        })
        s = client.get("/state").json()
        assert s["step"] == 1
        assert len(s["comments_made"]) == 1

    def test_state_shows_approved(self):
        client.post("/reset", json={"task_name": "simple-bug-detection"})
        client.post("/step", json={"action_type": "approve", "summary": "ok"})
        assert client.get("/state").json()["review_decision"] == "approved"

    def test_state_shows_changes_requested(self):
        client.post("/reset", json={"task_name": "simple-bug-detection"})
        client.post("/step", json={"action_type": "request_changes", "summary": "bugs"})
        assert client.get("/state").json()["review_decision"] == "changes_requested"

    def test_task2_security_ground_truth(self):
        client.post("/reset", json={"task_name": "security-audit"})
        s = client.get("/state").json()
        assert len(s["ground_truth_security"]) == 3

    def test_task3_bug_and_style_ground_truth(self):
        client.post("/reset", json={"task_name": "architecture-review"})
        s = client.get("/state").json()
        assert len(s["ground_truth_bugs"]) == 3
        assert len(s["ground_truth_style"]) == 2
