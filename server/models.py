"""
server/models.py
Pydantic v2 models for CodeReview OpenEnv.
All severity values stored as plain strings to avoid enum serialisation issues.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CodeFile(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    filename: str
    language: str = "python"
    content: str
    diff: Optional[str] = None
    line_count: int = 0


class ReviewComment(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    line: int
    message: str
    severity: str = "warning"   # plain str: info | warning | error | critical
    author: str = "agent"


class Observation(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    task_name: str
    step: int
    files: List[CodeFile]
    pr_title: str
    pr_description: str
    existing_comments: List[ReviewComment] = Field(default_factory=list)
    issues_found: List[str] = Field(default_factory=list)
    review_complete: bool = False
    last_action_result: Optional[str] = None
    last_action_error: Optional[str] = None
    hint: Optional[str] = None


class Action(BaseModel):
    """
    Agent action. action_type must be one of:
      add_comment, flag_security_issue, suggest_fix,
      approve, request_changes, no_op
    """
    model_config = ConfigDict(use_enum_values=True)
    action_type: str
    filename: Optional[str] = None
    line: Optional[int] = None
    message: Optional[str] = None
    severity: Optional[str] = "warning"
    summary: Optional[str] = None
    description: Optional[str] = None
    suggestion: Optional[str] = None


VALID_ACTION_TYPES = {
    "add_comment", "flag_security_issue", "suggest_fix",
    "approve", "request_changes", "no_op"
}


class Reward(BaseModel):
    value: float = Field(..., ge=0.0, le=1.0)
    done: bool = False
    bugs_found_score: float = 0.0
    security_score: float = 0.0
    false_positive_penalty: float = 0.0
    completion_bonus: float = 0.0
    step_efficiency: float = 0.0
    info: Dict[str, Any] = Field(default_factory=dict)


class EnvironmentState(BaseModel):
    task_name: str
    step: int = 0
    max_steps: int = 20
    done: bool = False
    ground_truth_bugs: List[Dict[str, Any]] = Field(default_factory=list)
    ground_truth_security: List[Dict[str, Any]] = Field(default_factory=list)
    ground_truth_style: List[Dict[str, Any]] = Field(default_factory=list)
    found_bug_ids: List[str] = Field(default_factory=list)
    found_security_ids: List[str] = Field(default_factory=list)
    false_positives: int = 0
    comments_made: List[ReviewComment] = Field(default_factory=list)
    review_decision: Optional[str] = None
    files: List[CodeFile] = Field(default_factory=list)
    pr_title: str = ""
    pr_description: str = ""
