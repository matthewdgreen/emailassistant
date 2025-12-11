"""
Pydantic models for email summaries, senders, tasks, and daily summaries.
"""

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


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
    ACTIVE = "active"
    COLD = "cold"
    ARCHIVED = "archived"


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SNOOZED = "snoozed"


class TaskSource(str, Enum):
    EMAIL = "email"
    MANUAL = "manual"
    OTHER = "other"


class TaskOperationType(str, Enum):
    ADD = "add"
    UPDATE = "update"
    CLOSE = "close"


# ---------------------------------------------------------------------------
# Core email models
# ---------------------------------------------------------------------------


class EmailSummary(BaseModel):
    """
    Minimal information about an email used in the first LLM pass.
    """

    id: str
    thread_id: str

    sender_name: Optional[str] = None
    sender_email: str

    received_at: datetime

    subject: str
    snippet: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class EmailBody(BaseModel):
    """
    Full email body for messages the LLM has requested to expand.
    """

    id: str
    thread_id: str

    body_text: str
    body_html: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# Sender and thread metadata
# ---------------------------------------------------------------------------


class SenderProfile(BaseModel):
    """
    Persistent profile for a sender: importance, role, notes, etc.
    """

    email: str
    name: Optional[str] = None

    importance: SenderImportance = SenderImportance.NORMAL
    role: SenderRole = SenderRole.OTHER

    notes: str = ""
    last_seen_at: Optional[datetime] = None

    pinned: bool = False  # for VIPs you never want downgraded by the model

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# Sender and thread metadata
# ---------------------------------------------------------------------------


class SenderProfile(BaseModel):
    """
    Persistent profile for a sender: importance, role, notes, etc.
    """

    email: str
    name: Optional[str] = None

    importance: SenderImportance = SenderImportance.NORMAL
    role: SenderRole = SenderRole.OTHER

    notes: str = ""
    last_seen_at: Optional[datetime] = None

    pinned: bool = False  # for VIPs you never want downgraded by the model

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class ThreadPolicy(BaseModel):
    """
    Per-thread metadata, usually tied to a project or deadline.
    """

    thread_id: str
    project: Optional[str] = None

    # "ME", "THEM", "NONE" (string for flexibility; could be enum later)
    expected_next_action: Optional[str] = None

    due_date: Optional[date] = None
    status: ThreadStatus = ThreadStatus.ACTIVE

    notes: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# Tasks and operations
# ---------------------------------------------------------------------------


class Task(BaseModel):
    """
    Persistent task object, possibly linked to an email thread.
    """

    id: str

    source: TaskSource = TaskSource.EMAIL
    email_thread_id: Optional[str] = None  # Gmail thread ID

    description: str
    status: TaskStatus = TaskStatus.OPEN

    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Integer priority (1–10), higher means more important.",
    )

    due_date: Optional[date] = None
    tags: List[str] = Field(default_factory=list)

    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        description="When the task was created (UTC).",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        description="When the task was last updated (UTC).",
    )

    origin_email_id: Optional[str] = None  # message that gave rise to this task

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class TaskOperation(BaseModel):
    """
    Operation emitted by the LLM to modify the task list.

    - ADD:    provide 'task'
    - UPDATE: provide 'task_id' and 'fields'
    - CLOSE:  provide 'task_id'
    """

    op: TaskOperationType

    task_id: Optional[str] = None
    task: Optional[Task] = None
    fields: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,  # allow arbitrary update fields; validate later
    )


# ---------------------------------------------------------------------------
# Daily summary models
# ---------------------------------------------------------------------------


class CriticalEmailEntry(BaseModel):
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
    email_id: str

    draft_outline: List[str] = Field(default_factory=list)
    full_draft: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )

class DailySummary(BaseModel):
    """
    High-level summary produced each day for the human.
    """

    summary_date: date = Field(default_factory=date.today)

    critical_emails: List[CriticalEmailEntry] = Field(default_factory=list)
    suggested_responses: List[SuggestedResponse] = Field(default_factory=list)

    other_notes: Optional[str] = None

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ---------------------------------------------------------------------------
# File container models
# ---------------------------------------------------------------------------


class KnownSendersFile(BaseModel):
    """
    Container model for known_senders.json.
    """

    senders: List[SenderProfile] = Field(default_factory=list)
    thread_policies: List[ThreadPolicy] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class TasksFile(BaseModel):
    """
    Container model for tasks.json.
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
