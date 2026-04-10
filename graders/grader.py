"""
graders/grader.py
Deterministic graders for CodeReview OpenEnv.

Public API:
    grade(state)               -> Reward   ((0.0, 1.0), terminal)
    intermediate_reward(state) -> float    ((0.0, 0.30), per-step)

Matching:
    comment matches issue when BOTH:
      1. abs(comment.line - issue["line"]) <= TOLERANCE (line proximity)
      2. any keyword from issue["keywords"] in comment.message (case-insensitive)

Scores vary continuously based on:
    - how many issues the agent found
    - false positives (hallucinated issues)
    - severity usage
    - final review decision
    - step efficiency
"""
from __future__ import annotations
from typing import Any, Dict, List
from server.models import EnvironmentState, Reward

TOLERANCE = 3
MIN_TERMINAL_SCORE = 0.0001
MAX_TERMINAL_SCORE = 0.9999
MIN_INTERMEDIATE_SCORE = 0.0001
MAX_INTERMEDIATE_SCORE = 0.2999


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def kw_match(text: str, keywords: List[str]) -> bool:
    """True if any keyword is a substring of text (case-insensitive)."""
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def matched_ids(comments, ground_truth: List[Dict[str, Any]]) -> List[str]:
    """Return IDs of ground-truth issues matched by agent comments (each at most once)."""
    result = []
    for issue in ground_truth:
        for c in comments:
            if abs(c.line - issue["line"]) <= TOLERANCE and kw_match(c.message, issue["keywords"]):
                result.append(issue["id"])
                break
    return result


def false_positives(comments, all_gt: List[Dict[str, Any]]) -> int:
    """Count comments that match no ground-truth issue."""
    fp = 0
    for c in comments:
        if not any(
            abs(c.line - i["line"]) <= TOLERANCE and kw_match(c.message, i["keywords"])
            for i in all_gt
        ):
            fp += 1
    return fp


def clamp_terminal_score(raw: float) -> float:
    """Keep terminal scores strictly inside (0, 1) for validator compatibility."""
    return max(MIN_TERMINAL_SCORE, min(MAX_TERMINAL_SCORE, raw))


def clamp_intermediate_score(raw: float) -> float:
    """Keep dense rewards strictly inside (0, 0.30) for validator compatibility."""
    return max(MIN_INTERMEDIATE_SCORE, min(MAX_INTERMEDIATE_SCORE, raw))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def grade(state: EnvironmentState) -> Reward:
    """Compute terminal reward. Score varies continuously - never fixed."""
    dispatch = {
        "simple-bug-detection": _grade_task1,
        "security-audit": _grade_task2,
        "architecture-review": _grade_task3,
    }
    fn = dispatch.get(state.task_name)
    if fn is None:
        raise ValueError(f"No grader for task '{state.task_name}'")
    return fn(state)


def intermediate_reward(state: EnvironmentState) -> float:
    """Dense per-step reward = current_score * 0.30, capped at 0.30."""
    r = grade(state)
    return round(clamp_intermediate_score(r.value * 0.30), 4)


# ---------------------------------------------------------------------------
# Task 1 - simple-bug-detection
# ---------------------------------------------------------------------------

def _grade_task1(state: EnvironmentState) -> Reward:
    all_gt = state.ground_truth_bugs + state.ground_truth_style
    bugs = state.ground_truth_bugs

    m_bugs = matched_ids(state.comments_made, bugs)
    fp = false_positives(state.comments_made, all_gt)

    # Bugs found score (0.0-1.0 internally), varies with each bug found
    bugs_score = len(m_bugs) / len(bugs) if bugs else 1.0

    # FP penalty varies continuously
    fp_penalty = min(0.30, fp * 0.10)

    # Decision bonus
    decision_bonus = 0.0
    if state.review_decision == "changes_requested" and m_bugs:
        decision_bonus = 0.10
    elif state.review_decision == "approved" and not bugs:
        decision_bonus = 0.10

    # Step efficiency bonus - rewards finishing faster
    step_ratio = state.step / max(state.max_steps, 1)
    efficiency = round(max(0.0, 0.10 * (1.0 - step_ratio)), 4) if state.done else 0.0

    raw = bugs_score * 0.80 + decision_bonus + efficiency - fp_penalty
    value = clamp_terminal_score(raw)

    return Reward(
        value=round(value, 4),
        done=state.done,
        bugs_found_score=round(bugs_score, 4),
        security_score=0.0,
        false_positive_penalty=round(fp_penalty, 4),
        completion_bonus=round(decision_bonus + efficiency, 4),
        step_efficiency=round(efficiency, 4),
        info={
            "matched_bugs": m_bugs,
            "total_bugs": len(bugs),
            "bugs_pct": round(bugs_score * 100, 1),
            "false_positives": fp,
            "review_decision": state.review_decision,
            "task": state.task_name,
        },
    )


# ---------------------------------------------------------------------------
# Task 2 - security-audit
# ---------------------------------------------------------------------------

def _grade_task2(state: EnvironmentState) -> Reward:
    all_gt = state.ground_truth_bugs + state.ground_truth_security
    m_sec = matched_ids(state.comments_made, state.ground_truth_security)
    m_bugs = matched_ids(state.comments_made, state.ground_truth_bugs)
    fp = false_positives(state.comments_made, all_gt)

    sec_score = len(m_sec) / len(state.ground_truth_security) if state.ground_truth_security else 1.0
    bug_score = len(m_bugs) / len(state.ground_truth_bugs) if state.ground_truth_bugs else 1.0

    # Bonus for using critical/error severity (shows agent understands risk)
    crit_count = sum(1 for c in state.comments_made if c.severity in ("critical", "error"))
    severity_bonus = min(0.10, crit_count * 0.025)

    fp_penalty = min(0.30, fp * 0.08)
    decision_bonus = 0.05 if state.review_decision == "changes_requested" else 0.0

    raw = sec_score * 0.65 + bug_score * 0.25 + severity_bonus + decision_bonus - fp_penalty
    value = clamp_terminal_score(raw)

    return Reward(
        value=round(value, 4),
        done=state.done,
        bugs_found_score=round(bug_score, 4),
        security_score=round(sec_score, 4),
        false_positive_penalty=round(fp_penalty, 4),
        completion_bonus=round(decision_bonus + severity_bonus, 4),
        step_efficiency=0.0,
        info={
            "matched_security": m_sec,
            "total_security": len(state.ground_truth_security),
            "security_pct": round(sec_score * 100, 1),
            "matched_bugs": m_bugs,
            "total_bugs": len(state.ground_truth_bugs),
            "false_positives": fp,
            "critical_flags": crit_count,
            "review_decision": state.review_decision,
            "task": state.task_name,
        },
    )


# ---------------------------------------------------------------------------
# Task 3 - architecture-review
# ---------------------------------------------------------------------------

def _grade_task3(state: EnvironmentState) -> Reward:
    all_gt = state.ground_truth_bugs + state.ground_truth_style
    m_bugs = matched_ids(state.comments_made, state.ground_truth_bugs)
    m_style = matched_ids(state.comments_made, state.ground_truth_style)
    fp = false_positives(state.comments_made, all_gt)

    total_issues = len(state.ground_truth_bugs) + len(state.ground_truth_style)
    total_found = len(m_bugs) + len(m_style)
    coverage = total_found / max(total_issues, 1)

    # Concurrency bugs get extra credit (hardest to spot)
    concurrency_bonus = sum(0.05 for b in m_bugs if b in ("bug-5", "bug-7"))
    rollback_bonus = 0.05 if "bug-6" in m_bugs else 0.0
    fp_penalty = min(0.25, fp * 0.06)
    decision_bonus = 0.05 if state.review_decision == "changes_requested" else 0.0

    raw = coverage * 0.75 + concurrency_bonus + rollback_bonus + decision_bonus - fp_penalty
    value = clamp_terminal_score(raw)

    return Reward(
        value=round(value, 4),
        done=state.done,
        bugs_found_score=round(len(m_bugs) / max(len(state.ground_truth_bugs), 1), 4),
        security_score=0.0,
        false_positive_penalty=round(fp_penalty, 4),
        completion_bonus=round(concurrency_bonus + rollback_bonus + decision_bonus, 4),
        step_efficiency=0.0,
        info={
            "matched_bugs": m_bugs,
            "matched_style": m_style,
            "total_issues": total_issues,
            "total_found": total_found,
            "coverage_pct": round(coverage * 100, 1),
            "concurrency_bonus": concurrency_bonus,
            "rollback_bonus": rollback_bonus,
            "false_positives": fp,
            "review_decision": state.review_decision,
            "task": state.task_name,
        },
    )
