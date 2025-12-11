"""
Pydantic models for email summaries, senders, tasks, and daily summaries.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SenderImportance(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class SenderRole(str, Enum):
    STUDENT = "student"
    COLLABORATOR = "collaborator"
    ADMIN = "admin"
    FAMILY = "family"
    NOTIFICATION = "notification"
    OTHER = "other"


class ThreadStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SNOOZED = "snoozed"
    IGNORED = "ignored"


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskSource(str, Enum):
    EMAIL = "email"
    MANUAL = "manual"
    OTHER = "other"


class TaskOperationType(str, Enum):
    ADD = "add"
    UPDATE = "update"
    CLOSE = "close"


# ---------------------------------------------------------------------------
# Email summaries and bodies
# ---------------------------------------------------------------------------


class EmailSummary(BaseModel):
    """
    Lightweight summary of a Gmail message.

    Used during the first pass to decide which emails to expand.
    """

    id: str
    thread_id: str
    subject: str = ""
    sender_email: str = ""
    received_at: Optional[datetime] = None

    # Optional extra metadata
    snippet: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class EmailBody(BaseModel):
    """
    Full email body and metadata for deeper analysis.

    Used in the second pass once we've decided which emails to expand.
    """

    id: str
    thread_id: str
    subject: str = ""
    sender_email: str = ""
    received_at: Optional[datetime] = None
    snippet: Optional[str] = None
    body_text: str = ""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# Sender profiles and thread policy
# ---------------------------------------------------------------------------


class SenderProfile(BaseModel):
    """
    Metadata about a sender used to drive prioritization.
    """

    email: str
    name: Optional[str] = None
    importance: SenderImportance = SenderImportance.NORMAL
    role: SenderRole = SenderRole.OTHER
    pinned: bool = False
    notes: Optional[str] = None
    last_seen_at: Optional[datetime] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class ThreadPolicy(BaseModel):
    """
    Optional per-thread policy (not heavily used yet, but kept for extensibility).
    """

    thread_id: str
    status: ThreadStatus = ThreadStatus.OPEN
    notes: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# Tasks and task operations
# ---------------------------------------------------------------------------


class Task(BaseModel):
    """
    A single task in the user's task list.

    Note: id is optional for newly created tasks coming from the LLM; the
    system will assign a concrete id before persisting.
    """

    id: Optional[str] = None
    description: str
    status: TaskStatus = TaskStatus.OPEN
    priority: int = 5
    due_date: Optional[date] = None
    source: Optional[TaskSource] = None
    email_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError("priority must be between 1 and 10")
        return v

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class TaskUpdateFields(BaseModel):
    """
    Partial set of fields that may be updated on a Task.
    """

    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[int] = None
    due_date: Optional[date] = None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not 1 <= v <= 10:
            raise ValueError("priority must be between 1 and 10")
        return v

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class TaskOperation(BaseModel):
    """
    Operation describing how to mutate the task list.

    - add:    create a new task (task.id may be omitted; assigned by system)
    - update: modify an existing task (requires task_id and fields)
    - close:  mark an existing task as done (requires task_id)
    """

    op: TaskOperationType
    task: Optional[Task] = None
    task_id: Optional[str] = None
    fields: Optional[TaskUpdateFields] = None

    @model_validator(mode="after")
    def check_consistency(self) -> "TaskOperation":
        if self.op == TaskOperationType.ADD:
            if self.task is None:
                raise ValueError("ADD operation requires 'task'")
        elif self.op == TaskOperationType.UPDATE:
            if not self.task_id:
                raise ValueError("UPDATE operation requires 'task_id'")
            if self.fields is None:
                raise ValueError("UPDATE operation requires 'fields'")
        elif self.op == TaskOperationType.CLOSE:
            if not self.task_id:
                raise ValueError("CLOSE operation requires 'task_id'")
        return self

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------


class CriticalEmailEntry(BaseModel):
    """
    One critical email entry in the daily summary.
    """

    email_id: str
    thread_id: str
    summary: str
    reason_critical: str
    recommended_action: str
    linked_task_ids: List[str] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class SuggestedResponse(BaseModel):
    """
    Suggested response for an email, possibly including a full draft.
    """

    email_id: str
    draft_outline: List[str]
    full_draft: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class DailySummary(BaseModel):
    """
    High-level summary of a day's worth of email triage.
    """

    summary_date: date
    critical_emails: List[CriticalEmailEntry] = Field(default_factory=list)
    suggested_responses: List[SuggestedResponse] = Field(default_factory=list)
    other_notes: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# File-level containers
# ---------------------------------------------------------------------------


class KnownSendersFile(BaseModel):
    """
    Container for known_senders.json.
    """

    senders: List[SenderProfile] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class TasksFile(BaseModel):
    """
    Container for tasks.json.
    """

    tasks: List[Task] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class StateFile(BaseModel):
    """
    Container for state.json (e.g., last run time).
    """

    last_run_at: Optional[datetime] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


__all__ = [
    "SenderImportance",
    "SenderRole",
    "ThreadStatus",
    "TaskStatus",
    "TaskSource",
    "TaskOperationType",
    "EmailSummary",
    "EmailBody",
    "SenderProfile",
    "ThreadPolicy",
    "Task",
    "TaskOperation",
    "CriticalEmailEntry",
    "SuggestedResponse",
    "DailySummary",
    "KnownSendersFile",
    "TasksFile",
    "StateFile",
]
