"""
tests/test_environment.py
Complete unit and integration tests for CodeReview OpenEnv.

Run:  PYTHONPATH=. pytest tests/ -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from server.models import (
    Action, Observation, Reward,
    EnvironmentState, CodeFile, ReviewComment,
    VALID_ACTION_TYPES,
)
from server.environment import CodeReviewEnv
from graders.grader import (
    grade, intermediate_reward,
    kw_match, matched_ids, false_positives,
)
from tasks.definitions import get_task, TASKS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env():
    return CodeReviewEnv()


@pytest.fixture
def env_easy(env):
    env.reset("simple-bug-detection")
    return env


@pytest.fixture
def env_medium(env):
    env.reset("security-audit")
    return env


@pytest.fixture
def env_hard(env):
    env.reset("architecture-review")
    return env


def _make_state(task_name="simple-bug-detection", comments=None, decision=None, step=5):
    """Helper to build a terminal EnvironmentState for grader tests."""
    task = get_task(task_name)
    return EnvironmentState(
        task_name=task_name,
        step=step,
        max_steps=task["max_steps"],
        done=True,
        ground_truth_bugs=task["ground_truth_bugs"],
        ground_truth_security=task["ground_truth_security"],
        ground_truth_style=task["ground_truth_style"],
        comments_made=comments or [],
        review_decision=decision,
        files=[CodeFile(**f) for f in task["files"]],
        pr_title=task["pr_title"],
        pr_description=task["pr_description"],
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_action_add_comment(self):
        a = Action(action_type="add_comment", line=5, message="Bug here", severity="error")
        assert a.action_type == "add_comment"
        assert a.line == 5
        assert a.severity == "error"

    def test_action_approve(self):
        a = Action(action_type="approve", summary="LGTM")
        assert a.action_type == "approve"
        assert a.line is None

    def test_action_all_valid_types(self):
        for at in VALID_ACTION_TYPES:
            a = Action(action_type=at)
            assert a.action_type == at

    def test_reward_valid_range(self):
        for v in (0.0, 0.5, 1.0):
            r = Reward(value=v)
            assert 0.0 <= r.value <= 1.0

    def test_reward_too_high_raises(self):
        with pytest.raises(Exception):
            Reward(value=1.01)

    def test_reward_too_low_raises(self):
        with pytest.raises(Exception):
            Reward(value=-0.01)

    def test_review_comment_default_severity(self):
        c = ReviewComment(line=1, message="test")
        assert c.severity == "warning"

    def test_review_comment_severity_set(self):
        c = ReviewComment(line=1, message="critical bug", severity="critical")
        assert c.severity == "critical"

    def test_observation_defaults(self):
        obs = Observation(
            task_name="simple-bug-detection", step=0,
            files=[], pr_title="T", pr_description="D",
        )
        assert obs.existing_comments == []
        assert obs.review_complete is False
        assert obs.hint is None

    def test_environment_state_defaults(self):
        s = EnvironmentState(task_name="simple-bug-detection")
        assert s.step == 0
        assert s.done is False
        assert s.review_decision is None
        assert s.comments_made == []

    def test_valid_action_types_set(self):
        assert "add_comment" in VALID_ACTION_TYPES
        assert "approve" in VALID_ACTION_TYPES
        assert "request_changes" in VALID_ACTION_TYPES
        assert "flag_security_issue" in VALID_ACTION_TYPES
        assert "suggest_fix" in VALID_ACTION_TYPES
        assert "no_op" in VALID_ACTION_TYPES


# ---------------------------------------------------------------------------
# Task definition tests
# ---------------------------------------------------------------------------

class TestTasks:
    def test_all_three_tasks_exist(self):
        for name in ("simple-bug-detection", "security-audit", "architecture-review"):
            t = get_task(name)
            assert t["name"] == name

    def test_unknown_task_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown task"):
            get_task("nonexistent-task")

    def test_required_fields_present(self):
        required = [
            "name", "difficulty", "max_steps", "pr_title", "pr_description",
            "files", "ground_truth_bugs", "ground_truth_security", "ground_truth_style"
        ]
        for name, task in TASKS.items():
            for field in required:
                assert field in task, f"Task '{name}' missing field '{field}'"

    def test_each_task_has_files_with_content(self):
        for name, task in TASKS.items():
            assert len(task["files"]) >= 1, f"'{name}' has no files"
            for f in task["files"]:
                assert f["content"].strip() != "", f"'{name}' file has empty content"

    def test_ground_truth_issues_have_required_fields(self):
        for name, task in TASKS.items():
            all_issues = (
                task["ground_truth_bugs"]
                + task["ground_truth_security"]
                + task["ground_truth_style"]
            )
            for issue in all_issues:
                for key in ("id", "line", "description", "keywords"):
                    assert key in issue, f"Issue {issue.get('id', '?')} in '{name}' missing '{key}'"
                assert len(issue["keywords"]) >= 2, \
                    f"Issue {issue['id']} needs at least 2 keywords"

    def test_difficulty_values_correct(self):
        assert TASKS["simple-bug-detection"]["difficulty"] == "easy"
        assert TASKS["security-audit"]["difficulty"] == "medium"
        assert TASKS["architecture-review"]["difficulty"] == "hard"

    def test_max_steps_increase_with_difficulty(self):
        e = TASKS["simple-bug-detection"]["max_steps"]
        m = TASKS["security-audit"]["max_steps"]
        h = TASKS["architecture-review"]["max_steps"]
        assert e < m < h

    def test_task1_has_exactly_3_bugs(self):
        assert len(TASKS["simple-bug-detection"]["ground_truth_bugs"]) == 3

    def test_task2_has_exactly_3_security_issues(self):
        assert len(TASKS["security-audit"]["ground_truth_security"]) == 3

    def test_task3_has_3_bugs_and_2_style(self):
        assert len(TASKS["architecture-review"]["ground_truth_bugs"]) == 3
        assert len(TASKS["architecture-review"]["ground_truth_style"]) == 2

    def test_task2_has_1_logic_bug(self):
        assert len(TASKS["security-audit"]["ground_truth_bugs"]) == 1

    def test_no_security_issues_in_task1(self):
        assert len(TASKS["simple-bug-detection"]["ground_truth_security"]) == 0

    def test_no_security_issues_in_task3(self):
        assert len(TASKS["architecture-review"]["ground_truth_security"]) == 0


# ---------------------------------------------------------------------------
# Environment reset() tests
# ---------------------------------------------------------------------------

class TestReset:
    def test_returns_observation_type(self, env):
        obs = env.reset()
        assert isinstance(obs, Observation)

    def test_step_is_zero(self, env):
        assert env.reset().step == 0

    def test_no_comments_on_reset(self, env):
        assert env.reset().existing_comments == []

    def test_has_files(self, env):
        obs = env.reset()
        assert len(obs.files) >= 1

    def test_not_complete_on_reset(self, env):
        assert env.reset().review_complete is False

    def test_no_hint_on_reset(self, env):
        assert env.reset().hint is None

    def test_pr_metadata_present(self, env):
        obs = env.reset("architecture-review")
        assert obs.pr_title != ""
        assert obs.pr_description != ""

    def test_clears_previous_episode(self, env):
        env.reset("simple-bug-detection")
        env.step(Action(action_type="add_comment", line=6,
                        message="zero division empty list", severity="error"))
        obs = env.reset("simple-bug-detection")
        assert obs.step == 0
        assert obs.existing_comments == []
        assert env.state()["review_decision"] is None

    def test_all_three_tasks_reset_ok(self, env):
        for name in TASKS:
            obs = env.reset(name)
            assert obs.task_name == name
            assert obs.step == 0

    def test_invalid_task_raises_value_error(self, env):
        with pytest.raises(ValueError):
            env.reset("not-a-real-task")


# ---------------------------------------------------------------------------
# Environment step() tests
# ---------------------------------------------------------------------------

class TestStep:
    def test_step_before_reset_raises(self, env):
        with pytest.raises(RuntimeError, match="reset"):
            env.step(Action(action_type="no_op"))

    def test_step_increments_counter(self, env_easy):
        obs, _, _, _ = env_easy.step(Action(action_type="no_op"))
        assert obs.step == 1

    def test_reward_in_range(self, env_easy):
        _, r, _, _ = env_easy.step(Action(action_type="no_op"))
        assert 0.0 < r < 1.0

    def test_add_comment_stored_correctly(self, env_easy):
        obs, _, _, _ = env_easy.step(Action(
            action_type="add_comment", line=6,
            message="ZeroDivisionError when numbers is empty",
            severity="error",
        ))
        assert len(obs.existing_comments) == 1
        assert obs.existing_comments[0].line == 6
        assert obs.existing_comments[0].severity == "error"

    def test_approve_ends_episode(self, env_easy):
        _, _, done, _ = env_easy.step(Action(action_type="approve", summary="ok"))
        assert done is True

    def test_request_changes_ends_episode(self, env_easy):
        _, _, done, _ = env_easy.step(
            Action(action_type="request_changes", summary="bugs found")
        )
        assert done is True

    def test_step_after_done_raises(self, env_easy):
        env_easy.step(Action(action_type="approve", summary="ok"))
        with pytest.raises(RuntimeError, match="done"):
            env_easy.step(Action(action_type="no_op"))

    def test_max_steps_terminates_episode(self, env):
        env.reset("simple-bug-detection")  # max_steps=10
        done = False
        for _ in range(10):
            _, _, done, _ = env.step(Action(action_type="no_op"))
        assert done is True

    def test_flag_security_always_critical(self, env_medium):
        obs, _, _, _ = env_medium.step(Action(
            action_type="flag_security_issue",
            line=6,
            description="Hardcoded secret key must use environment variable",
        ))
        assert obs.existing_comments[0].severity == "critical"

    def test_suggest_fix_stores_suggestion(self, env_easy):
        obs, _, _, _ = env_easy.step(Action(
            action_type="suggest_fix",
            line=6,
            suggestion="if not numbers: return 0.0",
        ))
        assert len(obs.existing_comments) == 1
        assert "suggest" in obs.existing_comments[0].message.lower()

    def test_no_op_adds_no_comment(self, env_easy):
        obs, _, _, _ = env_easy.step(Action(action_type="no_op"))
        assert len(obs.existing_comments) == 0

    def test_add_comment_missing_line_returns_error(self, env_easy):
        obs, _, _, _ = env_easy.step(
            Action(action_type="add_comment", message="something wrong")
        )
        assert obs.last_action_error is not None

    def test_add_comment_empty_message_returns_error(self, env_easy):
        obs, _, _, _ = env_easy.step(
            Action(action_type="add_comment", line=5, message="  ")
        )
        assert obs.last_action_error is not None

    def test_flag_security_missing_description_returns_error(self, env_medium):
        obs, _, _, _ = env_medium.step(
            Action(action_type="flag_security_issue", line=6)
        )
        assert obs.last_action_error is not None

    def test_suggest_fix_missing_line_returns_error(self, env_easy):
        obs, _, _, _ = env_easy.step(
            Action(action_type="suggest_fix", suggestion="x = 1")
        )
        assert obs.last_action_error is not None

    def test_suggest_fix_missing_suggestion_returns_error(self, env_easy):
        obs, _, _, _ = env_easy.step(
            Action(action_type="suggest_fix", line=6)
        )
        assert obs.last_action_error is not None

    def test_partial_reward_capped_at_0_30(self, env_easy):
        _, r, done, _ = env_easy.step(Action(action_type="no_op"))
        if not done:
            assert r <= 0.30 + 1e-6

    def test_info_dict_contains_step(self, env_easy):
        _, _, _, info = env_easy.step(Action(action_type="no_op"))
        assert "step" in info
        assert info["step"] == 1

    def test_info_dict_contains_task(self, env_easy):
        _, _, _, info = env_easy.step(Action(action_type="no_op"))
        assert info["task"] == "simple-bug-detection"

    def test_multiple_comments_accumulate(self, env_easy):
        for line in (6, 17, 22):
            env_easy.step(Action(
                action_type="add_comment",
                line=line,
                message=f"issue at line {line}",
                severity="error",
            ))
        obs, _, _, _ = env_easy.step(Action(action_type="no_op"))
        assert len(obs.existing_comments) == 3

    def test_hint_shown_at_3_remaining(self, env):
        env.reset("simple-bug-detection")  # max_steps=10
        obs = None
        for i in range(7):
            obs, _, done, _ = env.step(Action(action_type="no_op"))
            if done:
                break
        # After 7 steps, 3 remaining, hint should appear
        if obs and not obs.review_complete:
            assert obs.hint is not None

    def test_no_hint_early_in_episode(self, env_easy):
        obs, _, _, _ = env_easy.step(Action(action_type="no_op"))
        assert obs.hint is None


# ---------------------------------------------------------------------------
# Environment state() tests
# ---------------------------------------------------------------------------

class TestState:
    def test_state_before_reset_returns_not_initialized(self, env):
        s = env.state()
        assert s["status"] == "not_initialized"

    def test_state_after_reset(self, env):
        env.reset("simple-bug-detection")
        s = env.state()
        assert s["task_name"] == "simple-bug-detection"
        assert s["step"] == 0
        assert s["done"] is False

    def test_state_exposes_ground_truth(self, env):
        env.reset("simple-bug-detection")
        s = env.state()
        assert "ground_truth_bugs" in s
        assert len(s["ground_truth_bugs"]) == 3

    def test_state_updates_after_step(self, env_easy):
        env_easy.step(Action(
            action_type="add_comment", line=6,
            message="zero division", severity="error"
        ))
        s = env_easy.state()
        assert s["step"] == 1
        assert len(s["comments_made"]) == 1

    def test_state_shows_review_decision(self, env_easy):
        env_easy.step(Action(action_type="approve", summary="ok"))
        assert env_easy.state()["review_decision"] == "approved"

    def test_state_shows_changes_requested(self, env_easy):
        env_easy.step(Action(action_type="request_changes", summary="bugs"))
        assert env_easy.state()["review_decision"] == "changes_requested"


# ---------------------------------------------------------------------------
# Grader helper function tests
# ---------------------------------------------------------------------------

class TestGraderHelpers:
    def test_kw_match_exact(self):
        assert kw_match("ZeroDivisionError when list is empty", ["zero", "division"])

    def test_kw_match_case_insensitive(self):
        assert kw_match("SQL INJECTION detected", ["sql", "injection"])

    def test_kw_match_no_match(self):
        assert not kw_match("looks good LGTM", ["sql", "injection", "race"])

    def test_kw_match_partial_substring(self):
        assert kw_match("use bcrypt for password hashing", ["bcrypt"])

    def test_kw_match_single_keyword_sufficient(self):
        assert kw_match("race condition here", ["race"])

    def test_matched_ids_exact_line(self):
        gt = [{"id": "x", "line": 10, "keywords": ["bug"]}]
        c = [ReviewComment(line=10, message="found a bug here")]
        assert "x" in matched_ids(c, gt)

    def test_matched_ids_within_tolerance(self):
        gt = [{"id": "x", "line": 10, "keywords": ["bug"]}]
        c = [ReviewComment(line=12, message="found a bug here")]
        assert "x" in matched_ids(c, gt)

    def test_matched_ids_just_outside_tolerance(self):
        gt = [{"id": "x", "line": 10, "keywords": ["bug"]}]
        c = [ReviewComment(line=14, message="found a bug here")]
        assert "x" not in matched_ids(c, gt)

    def test_matched_ids_wrong_keyword(self):
        gt = [{"id": "x", "line": 10, "keywords": ["race", "atomic"]}]
        c = [ReviewComment(line=10, message="this code looks wrong")]
        assert "x" not in matched_ids(c, gt)

    def test_matched_ids_counted_at_most_once(self):
        gt = [{"id": "x", "line": 10, "keywords": ["bug"]}]
        c = [
            ReviewComment(line=10, message="big bug here"),
            ReviewComment(line=10, message="another bug here"),
        ]
        result = matched_ids(c, gt)
        assert result.count("x") == 1

    def test_false_positives_count(self):
        gt = [{"id": "x", "line": 10, "keywords": ["bug"]}]
        c = [
            ReviewComment(line=10, message="found a bug"),    # TP
            ReviewComment(line=50, message="this is wrong"),  # FP
            ReviewComment(line=51, message="also bad"),       # FP
        ]
        assert false_positives(c, gt) == 2

    def test_false_positives_zero_when_all_match(self):
        gt = [{"id": "x", "line": 10, "keywords": ["bug"]}]
        c = [ReviewComment(line=10, message="found a bug")]
        assert false_positives(c, gt) == 0

    def test_false_positives_all_fp(self):
        gt = [{"id": "x", "line": 10, "keywords": ["bug"]}]
        c = [
            ReviewComment(line=50, message="wrong here"),
            ReviewComment(line=60, message="bad code"),
        ]
        assert false_positives(c, gt) == 2


# ---------------------------------------------------------------------------
# Grader reward computation tests
# ---------------------------------------------------------------------------

class TestGrader:
    def test_terminal_scores_are_strictly_between_zero_and_one(self):
        for task_name in TASKS:
            low = grade(_make_state(task_name, comments=[], decision="approved"))
            high = grade(_make_state(
                task_name,
                comments=[
                    ReviewComment(line=6, message="hardcoded secret key environment variable", severity="critical"),
                    ReviewComment(line=15, message="md5 broken password hashing use bcrypt", severity="critical"),
                    ReviewComment(line=21, message="sql injection parameterized query", severity="critical"),
                    ReviewComment(line=51, message="race condition stock deduction not atomic concurrent oversell lock", severity="critical"),
                    ReviewComment(line=64, message="no rollback payment fails stock inventory corrupted revert", severity="critical"),
                    ReviewComment(line=78, message="thread unsafe results list shared concurrent append mutex lock", severity="error"),
                    ReviewComment(line=8, message="unbounded memory leak cache lru eviction bounded"),
                    ReviewComment(line=62, message="blocking sleep stall retry thread pool async backoff"),
                    ReviewComment(line=6, message="ZeroDivisionError empty list division zero", severity="error"),
                    ReviewComment(line=17, message="duplicate multiple times set 3+", severity="warning"),
                    ReviewComment(line=22, message="syntax assignment instead of comparison ==", severity="error"),
                ],
                decision="changes_requested",
            ))
            assert 0.0 < low.value < 1.0
            assert 0.0 < high.value < 1.0

    def test_reward_always_in_range_all_tasks(self):
        """Critical: grader must always produce 0.0-1.0, never fixed value."""
        for task_name in TASKS:
            for n in (0, 1, 2, 5, 10, 20):
                comments = [
                    ReviewComment(line=i % 30 + 1, message="issue found here wrong")
                    for i in range(n)
                ]
                r = grade(_make_state(task_name, comments=comments, decision="request_changes"))
                assert 0.0 <= r.value <= 1.0, \
                    f"reward={r.value} out of range for {task_name} with {n} comments"

    def test_reward_varies_with_comments(self):
        """Grader must NOT always return the same score (would be disqualified)."""
        r0 = grade(_make_state(decision="approved"))
        r3 = grade(_make_state(
            comments=[
                ReviewComment(line=6, message="ZeroDivisionError empty list division zero"),
                ReviewComment(line=17, message="duplicate multiple times set 3+"),
                ReviewComment(line=22, message="syntax assignment = instead of == comparison"),
            ],
            decision="changes_requested"
        ))
        assert r0.value != r3.value, "Grader returns same score regardless of input - disqualification risk!"

    def test_task1_zero_bugs_found_low_score(self):
        r = grade(_make_state(decision="approved"))
        assert r.value < 0.20

    def test_task1_all_bugs_found_high_score(self):
        comments = [
            ReviewComment(line=6,  message="ZeroDivisionError when numbers list is empty division zero len"),
            ReviewComment(line=17, message="find_duplicates appends duplicate multiple times for 3+ occurrences use set"),
            ReviewComment(line=22, message="syntax error assignment = operator used instead of equality comparison =="),
        ]
        r = grade(_make_state(comments=comments, decision="changes_requested"))
        assert r.value >= 0.70, f"Expected >= 0.70 with all bugs found, got {r.value}"
        assert r.bugs_found_score == pytest.approx(1.0)

    def test_task1_one_bug_found_partial_score(self):
        comments = [
            ReviewComment(line=6, message="ZeroDivisionError empty list division zero")
        ]
        r = grade(_make_state(comments=comments, decision="changes_requested"))
        assert 0.20 < r.value < 0.80

    def test_task1_two_bugs_found_between_one_and_three(self):
        r1 = grade(_make_state(
            comments=[ReviewComment(line=6, message="ZeroDivisionError empty division zero")],
            decision="changes_requested"
        ))
        r2 = grade(_make_state(
            comments=[
                ReviewComment(line=6,  message="ZeroDivisionError empty division zero"),
                ReviewComment(line=17, message="duplicate multiple times set 3+"),
            ],
            decision="changes_requested"
        ))
        r3 = grade(_make_state(
            comments=[
                ReviewComment(line=6,  message="ZeroDivisionError empty division zero"),
                ReviewComment(line=17, message="duplicate multiple times set 3+"),
                ReviewComment(line=22, message="syntax = assignment instead of == comparison"),
            ],
            decision="changes_requested"
        ))
        assert r1.value < r2.value < r3.value, "Score should increase as more bugs are found"

    def test_task1_false_positive_penalty_reduces_score(self):
        fp_comments = [
            ReviewComment(line=i, message="this looks wrong bad code style issue")
            for i in range(1, 15)
        ]
        r_with_fp = grade(_make_state(comments=fp_comments, decision="request_changes"))
        r_clean = grade(_make_state(decision="request_changes"))
        assert r_with_fp.value <= r_clean.value + 0.01

    def test_task1_correct_decision_bonus(self):
        comments = [ReviewComment(line=6, message="ZeroDivisionError empty list division zero")]
        r_correct = grade(_make_state(comments=comments, decision="changes_requested"))
        r_wrong   = grade(_make_state(comments=comments, decision="approved"))
        assert r_correct.value >= r_wrong.value

    def test_task2_all_security_found(self):
        comments = [
            ReviewComment(line=6,  message="hardcoded secret key use os.environ environment variable", severity="critical"),
            ReviewComment(line=15, message="md5 broken password hashing use bcrypt argon2", severity="critical"),
            ReviewComment(line=21, message="sql injection f-string interpolation use parameterized query", severity="critical"),
        ]
        r = grade(_make_state("security-audit", comments=comments, decision="changes_requested"))
        assert r.security_score == pytest.approx(1.0)
        assert r.value >= 0.60

    def test_task2_partial_security_partial_score(self):
        comments = [
            ReviewComment(line=6, message="hardcoded secret key environment variable", severity="critical"),
        ]
        r = grade(_make_state("security-audit", comments=comments, decision="changes_requested"))
        assert 0.0 < r.value < 1.0

    def test_task2_severity_bonus_for_critical(self):
        comments = [ReviewComment(line=6, message="hardcoded secret key environment variable")]
        r_crit = grade(_make_state("security-audit",
                                   comments=[ReviewComment(line=6, message="hardcoded secret key environment variable", severity="critical")],
                                   decision="changes_requested"))
        r_info = grade(_make_state("security-audit",
                                   comments=[ReviewComment(line=6, message="hardcoded secret key environment variable", severity="info")],
                                   decision="changes_requested"))
        assert r_crit.value >= r_info.value

    def test_task3_concurrency_bonus_present(self):
        comments = [
            ReviewComment(line=51, message="race condition stock deduction not atomic concurrent oversell lock"),
            ReviewComment(line=78, message="thread unsafe results list shared concurrent append mutex lock"),
            ReviewComment(line=64, message="no rollback payment fails stock inventory corrupted revert"),
        ]
        r = grade(_make_state("architecture-review", comments=comments, decision="changes_requested"))
        assert r.info["concurrency_bonus"] > 0
        assert r.info["rollback_bonus"] > 0
        assert r.value >= 0.50

    def test_task3_memory_leak_detected(self):
        comments = [
            ReviewComment(line=8, message="unbounded memory leak cache lru eviction bounded")
        ]
        r = grade(_make_state("architecture-review", comments=comments, decision="changes_requested"))
        assert r.value > 0.0

    def test_task3_blocking_sleep_detected(self):
        comments = [
            ReviewComment(line=62, message="blocking sleep stall retry thread pool async backoff")
        ]
        r = grade(_make_state("architecture-review", comments=comments, decision="changes_requested"))
        assert r.value > 0.0

    def test_intermediate_reward_capped_at_0_30(self):
        state = _make_state(
            comments=[ReviewComment(line=6, message="zero division empty list")],
            decision=None,
        )
        state.done = False
        ir = intermediate_reward(state)
        assert 0.0 < ir < 0.30 + 1e-6

    def test_intermediate_reward_strictly_positive_for_no_progress(self):
        state = _make_state(decision=None)
        state.done = False
        ir = intermediate_reward(state)
        assert 0.0 < ir < 0.30

    def test_unknown_task_raises(self):
        state = _make_state()
        state.task_name = "invalid-task-name"
        with pytest.raises(ValueError, match="No grader"):
            grade(state)

    def test_reward_breakdown_fields_present(self):
        r = grade(_make_state(decision="approved"))
        assert hasattr(r, "bugs_found_score")
        assert hasattr(r, "security_score")
        assert hasattr(r, "false_positive_penalty")
        assert hasattr(r, "completion_bonus")
        assert hasattr(r, "step_efficiency")
        assert isinstance(r.info, dict)
        assert "task" in r.info


# ---------------------------------------------------------------------------
# Full episode integration tests
# ---------------------------------------------------------------------------

class TestFullEpisodes:
    def test_easy_perfect_episode(self, env):
        """Find all 3 bugs + request_changes => score >= 0.70."""
        env.reset("simple-bug-detection")
        env.step(Action(
            action_type="add_comment", line=6,
            message="ZeroDivisionError: compute_average crashes when numbers is empty list division zero len",
            severity="error",
        ))
        env.step(Action(
            action_type="add_comment", line=17,
            message="find_duplicates appends duplicate items multiple times for 3+ occurrences, use set instead",
            severity="warning",
        ))
        env.step(Action(
            action_type="add_comment", line=22,
            message="syntax error: assignment operator = used instead of equality comparison ==",
            severity="error",
        ))
        _, final_reward, done, _ = env.step(Action(
            action_type="request_changes",
            summary="Found 3 bugs: zero-division, bad duplicate logic, syntax error",
        ))
        assert done is True
        assert final_reward >= 0.70, f"Expected >= 0.70, got {final_reward}"

    def test_approve_without_finding_bugs_low_score(self, env):
        """Immediately approving without review should score low."""
        env.reset("simple-bug-detection")
        _, r, done, _ = env.step(Action(action_type="approve", summary="LGTM"))
        assert done is True
        assert r < 0.30

    def test_score_increases_with_more_bugs_found(self, env):
        """Finding more bugs should yield higher score."""
        env.reset("simple-bug-detection")
        env.step(Action(action_type="add_comment", line=6,
                        message="ZeroDivisionError empty list division zero", severity="error"))
        _, r1, _, _ = env.step(Action(action_type="request_changes", summary="1 bug"))

        env.reset("simple-bug-detection")
        env.step(Action(action_type="add_comment", line=6,
                        message="ZeroDivisionError empty list division zero", severity="error"))
        env.step(Action(action_type="add_comment", line=17,
                        message="duplicate multiple times set 3+", severity="warning"))
        env.step(Action(action_type="add_comment", line=22,
                        message="syntax = assignment instead of == comparison", severity="error"))
        _, r3, _, _ = env.step(Action(action_type="request_changes", summary="3 bugs"))

        assert r1 < r3, f"Finding 3 bugs ({r3}) should score higher than 1 bug ({r1})"

    def test_security_episode_all_vulns(self, env):
        """Find all 3 security issues => score >= 0.60."""
        env.reset("security-audit")
        env.step(Action(
            action_type="flag_security_issue", line=6,
            description="Hardcoded JWT secret key must use os.environ environment variable",
        ))
        env.step(Action(
            action_type="flag_security_issue", line=15,
            description="MD5 is cryptographically broken for password hashing, use bcrypt or argon2",
        ))
        env.step(Action(
            action_type="flag_security_issue", line=21,
            description="SQL injection via f-string interpolation, use parameterized query",
        ))
        _, r, done, _ = env.step(Action(
            action_type="request_changes",
            summary="3 critical security vulnerabilities",
        ))
        assert done is True
        assert r >= 0.60, f"Expected >= 0.60, got {r}"

    def test_architecture_race_conditions(self, env):
        """Find race conditions => score >= 0.50."""
        env.reset("architecture-review")
        env.step(Action(
            action_type="add_comment", line=51,
            message="Race condition: stock deduction not atomic, concurrent orders oversell lock",
            severity="critical",
        ))
        env.step(Action(
            action_type="add_comment", line=64,
            message="No rollback when payment fails, stock inventory corrupted revert",
            severity="critical",
        ))
        env.step(Action(
            action_type="add_comment", line=78,
            message="Thread-unsafe: results list shared concurrent append without mutex lock",
            severity="error",
        ))
        _, r, done, _ = env.step(Action(
            action_type="request_changes", summary="Race conditions and concurrency bugs",
        ))
        assert done is True
        assert r >= 0.50, f"Expected >= 0.50, got {r}"

    def test_partial_rewards_are_dense_and_increasing(self, env):
        """Partial rewards should increase as more bugs are found."""
        env.reset("simple-bug-detection")
        rewards = []
        for line, msg in (
            (6,  "zero division error empty list"),
            (17, "duplicate multiple times set 3+"),
            (22, "syntax = assignment instead of == comparison"),
        ):
            _, r, done, _ = env.step(Action(
                action_type="add_comment", line=line,
                message=msg, severity="error"
            ))
            if not done:
                rewards.append(r)
                assert r <= 0.31, f"Partial reward {r} exceeds 0.30 cap"

        _, final, _, _ = env.step(Action(action_type="request_changes", summary="done"))
        assert final >= 0.50
        if rewards:
            assert final > rewards[-1], "Terminal reward should be higher than last partial"

    def test_reset_gives_fully_clean_state(self, env):
        """Two episodes are fully independent."""
        env.reset("simple-bug-detection")
        env.step(Action(action_type="add_comment", line=6,
                        message="zero division", severity="error"))
        env.step(Action(action_type="approve", summary="ok"))

        obs = env.reset("simple-bug-detection")
        assert obs.step == 0
        assert obs.existing_comments == []
        s = env.state()
        assert s["review_decision"] is None
        assert s["comments_made"] == []

    def test_no_op_gives_partial_reward_not_terminal(self, env):
        """No-op should not end episode and reward should be partial."""
        env.reset("simple-bug-detection")
        _, r, done, _ = env.step(Action(action_type="no_op"))
        assert done is False
        assert 0.0 < r <= 0.31
