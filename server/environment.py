"""
server/environment.py
Core OpenEnv-compliant environment.

Public API:
    env.reset(task_name) -> Observation
    env.step(action)     -> (Observation, float, bool, dict)
    env.state()          -> dict
"""
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple

from server.models import (
    Action, CodeFile, EnvironmentState,
    Observation, ReviewComment, VALID_ACTION_TYPES,
)
from tasks.definitions import get_task
from graders.grader import grade, intermediate_reward


class CodeReviewEnv:
    """OpenEnv environment: AI agents review pull requests."""

    def __init__(self) -> None:
        self._state: Optional[EnvironmentState] = None

    # -------------------------------------------------------------------------
    # Public OpenEnv interface
    # -------------------------------------------------------------------------

    def reset(self, task_name: str = "simple-bug-detection") -> Observation:
        """
        Start a new episode.
        Raises ValueError for unknown task names.
        Returns initial Observation.
        """
        task = get_task(task_name)
        files = [CodeFile(**f) for f in task["files"]]
        self._state = EnvironmentState(
            task_name=task_name,
            step=0,
            max_steps=task["max_steps"],
            done=False,
            ground_truth_bugs=task["ground_truth_bugs"],
            ground_truth_security=task["ground_truth_security"],
            ground_truth_style=task["ground_truth_style"],
            found_bug_ids=[],
            found_security_ids=[],
            false_positives=0,
            comments_made=[],
            review_decision=None,
            files=files,
            pr_title=task["pr_title"],
            pr_description=task["pr_description"],
        )
        return self._build_obs()

    def step(self, action: Action) -> Tuple[Observation, float, bool, Dict[str, Any]]:
        """
        Execute one agent action.
        Returns (observation, reward, done, info).
        Raises RuntimeError if called before reset() or after done=True.
        """
        if self._state is None:
            raise RuntimeError("Call reset() before step().")
        if self._state.done:
            raise RuntimeError("Episode is done. Call reset() to start a new one.")

        # Validate action type
        if action.action_type not in VALID_ACTION_TYPES:
            raise ValueError(f"Invalid action_type: '{action.action_type}'. "
                             f"Must be one of: {sorted(VALID_ACTION_TYPES)}")

        self._state.step += 1
        result_msg: Optional[str] = None
        error_msg: Optional[str] = None

        try:
            result_msg, error_msg = self._apply(action)
        except Exception as exc:
            error_msg = str(exc)

        done = self._is_done()
        self._state.done = done

        if done:
            reward_val = round(grade(self._state).value, 4)
        else:
            reward_val = intermediate_reward(self._state)

        obs = self._build_obs(result_msg, error_msg)
        info = {
            "step": self._state.step,
            "max_steps": self._state.max_steps,
            "task": self._state.task_name,
            "comments_so_far": len(self._state.comments_made),
        }
        return obs, reward_val, done, info

    def state(self) -> Dict[str, Any]:
        """Full internal state including ground truth (for eval harnesses)."""
        if self._state is None:
            return {"status": "not_initialized"}
        return self._state.model_dump()

    # -------------------------------------------------------------------------
    # Action dispatch
    # -------------------------------------------------------------------------

    def _apply(self, action: Action) -> Tuple[Optional[str], Optional[str]]:
        at = action.action_type

        if at == "add_comment":
            return self._add_comment(action)
        if at == "flag_security_issue":
            return self._flag_security(action)
        if at == "suggest_fix":
            return self._suggest_fix(action)
        if at == "approve":
            self._state.review_decision = "approved"
            return "Review submitted: APPROVED.", None
        if at == "request_changes":
            self._state.review_decision = "changes_requested"
            summary = action.summary or "(no summary)"
            return f"Review submitted: CHANGES REQUESTED — {summary}", None
        if at == "no_op":
            return "No operation performed.", None

        return None, f"Unknown action_type: '{at}'"

    def _add_comment(self, action: Action) -> Tuple[Optional[str], Optional[str]]:
        if not action.line:
            return None, "add_comment requires 'line' (integer)."
        if not action.message or not action.message.strip():
            return None, "add_comment requires a non-empty 'message'."
        self._state.comments_made.append(ReviewComment(
            line=action.line,
            message=action.message.strip(),
            severity=action.severity or "warning",
        ))
        return f"Comment added at line {action.line}.", None

    def _flag_security(self, action: Action) -> Tuple[Optional[str], Optional[str]]:
        if not action.description or not action.description.strip():
            return None, "flag_security_issue requires a non-empty 'description'."
        line = action.line or 0
        self._state.comments_made.append(ReviewComment(
            line=line,
            message=action.description.strip(),
            severity="critical",
        ))
        return f"Security issue flagged at line {line}.", None

    def _suggest_fix(self, action: Action) -> Tuple[Optional[str], Optional[str]]:
        if not action.line:
            return None, "suggest_fix requires 'line' (integer)."
        if not action.suggestion or not action.suggestion.strip():
            return None, "suggest_fix requires a non-empty 'suggestion'."
        self._state.comments_made.append(ReviewComment(
            line=action.line,
            message=f"Suggested fix: {action.suggestion.strip()}",
            severity=action.severity or "info",
        ))
        return f"Fix suggestion added at line {action.line}.", None

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _is_done(self) -> bool:
        s = self._state
        if s.review_decision in ("approved", "changes_requested"):
            return True
        if s.step >= s.max_steps:
            s.review_decision = "no_decision"
            return True
        return False

    def _build_obs(
        self,
        last_result: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> Observation:
        s = self._state
        remaining = s.max_steps - s.step
        hint = (
            f"Only {remaining} steps remaining. Submit your review soon."
            if remaining == 3 and s.review_decision is None
            else None
        )
        return Observation(
            task_name=s.task_name,
            step=s.step,
            files=s.files,
            pr_title=s.pr_title,
            pr_description=s.pr_description,
            existing_comments=list(s.comments_made),
            issues_found=s.found_bug_ids + s.found_security_ids,
            review_complete=s.done,
            last_action_result=last_result,
            last_action_error=last_error,
            hint=hint,
        )
