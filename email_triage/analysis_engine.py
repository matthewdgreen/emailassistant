"""
Analysis engine: orchestrates Gmail + LLM + storage into a daily run.

Core pieces:
- Task operation application
- Sender profile merging
- run_daily_analysis: the two-pass Gmail + LLM workflow
"""

from datetime import date, datetime, timezone, timedelta
import logging
from typing import Iterable, List, Optional

from pydantic import ValidationError

from .config import Config
from .models import (
    DailySummary,
    CriticalEmailEntry,
    KnownSendersFile,
    SenderProfile,
    TasksFile,
    Task,
    TaskOperation,
    TaskOperationType,
    TaskStatus,
)
from .storage import (
    load_known_senders,
    save_known_senders,
    load_tasks,
    save_tasks,
    load_state,
    save_state,
    load_instructions,
)
from .gmail_client import build_gmail_service, list_unread_summaries_since, list_unread_summaries_between, fetch_email_bodies
from .llm_client import call_llm_json, LLMError
from .prompts import build_pass1_messages, build_pass2_messages

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------------


def _generate_task_id(tasks_file: TasksFile) -> str:
    """Generate a new task ID that doesn't collide with existing ones."""
    existing_ids = {t.id for t in tasks_file.tasks}
    i = 1
    while True:
        candidate = f"task-{i:04d}"
        if candidate not in existing_ids:
            return candidate
        i += 1


def apply_task_operations(tasks_file: TasksFile, ops: Iterable[TaskOperation]) -> TasksFile:
    """
    Apply a list of TaskOperations to a TasksFile and return the updated file.

    Safeguards:
    - If an UPDATE or CLOSE refers to a non-existent task_id, we log a warning and skip it.
    - CLOSE only marks tasks as DONE; we never delete tasks.
    """
    tasks_by_id = {t.id: t for t in tasks_file.tasks}

    for op in ops:
        try:
            if op.op == TaskOperationType.ADD:
                if op.task is None:
                    logger.warning("ADD operation without task payload; skipping.")
                    continue
                task = op.task
                # Assign ID if empty or None
                if not task.id:
                    task_id = _generate_task_id(tasks_file)
                    task.id = task_id
                elif task.id in tasks_by_id:
                    logger.warning("ADD operation with existing task_id=%s; skipping.", task.id)
                    continue
                now = datetime.utcnow().replace(tzinfo=timezone.utc)
                task.created_at = now
                task.updated_at = now
                tasks_by_id[task.id] = task

            elif op.op == TaskOperationType.UPDATE:
                if not op.task_id:
                    logger.warning("UPDATE operation without task_id; skipping.")
                    continue
                if op.task_id not in tasks_by_id:
                    logger.warning("UPDATE operation for unknown task_id=%s; skipping.", op.task_id)
                    continue
                task = tasks_by_id[op.task_id]
                fields = op.fields or {}
                for key, value in fields.items():
                    if not hasattr(task, key):
                        logger.debug(
                            "Ignoring unknown field '%s' on Task during UPDATE for id=%s",
                            key,
                            op.task_id,
                        )
                        continue
                    setattr(task, key, value)
                task.updated_at = datetime.utcnow().replace(tzinfo=timezone.utc)
                tasks_by_id[op.task_id] = task

            elif op.op == TaskOperationType.CLOSE:
                if not op.task_id:
                    logger.warning("CLOSE operation without task_id; skipping.")
                    continue
                if op.task_id not in tasks_by_id:
                    logger.warning("CLOSE operation for unknown task_id=%s; skipping.", op.task_id)
                    continue
                task = tasks_by_id[op.task_id]
                task.status = TaskStatus.DONE
                task.updated_at = datetime.utcnow().replace(tzinfo=timezone.utc)
                tasks_by_id[op.task_id] = task

            else:
                logger.warning("Unknown task operation type: %s", op.op)

        except Exception as e:  # guardrail so one bad op doesn't break everything
            logger.exception("Error applying task operation %s: %s", op, e)

    updated_tasks: List[Task] = list(tasks_by_id.values())
    # Sort: non-done first, by priority desc, then created_at asc
    updated_tasks.sort(key=lambda t: (t.status == TaskStatus.DONE, -t.priority, t.created_at))
    return TasksFile(tasks=updated_tasks)


# ---------------------------------------------------------------------------
# Sender updates
# ---------------------------------------------------------------------------

def merge_sender_updates(
    known_senders: KnownSendersFile,
    updated_senders: Iterable[SenderProfile],
) -> KnownSendersFile:
    """
    Merge a list of updated SenderProfile objects into an existing KnownSendersFile.

    - If a sender email exists, we replace the profile entirely with the new one.
    - If it's new, we add it.
    """
    by_email = {s.email: s for s in known_senders.senders}

    for s in updated_senders:
        if not s.email:
            logger.warning("SenderProfile without email encountered; skipping: %s", s)
            continue

        existing = by_email.get(s.email)
        if existing is None:
            by_email[s.email] = s
        else:
            # Replace entirely; if you want a patch-style merge later, we can add that.
            by_email[s.email] = s

    merged = KnownSendersFile(
        senders=list(by_email.values()),
    )
    return merged


# ---------------------------------------------------------------------------
# Main daily analysis orchestration
# ---------------------------------------------------------------------------

def run_daily_analysis(
    config: Config,
    since_override: Optional[datetime] = None,
    update_state: bool = True,
) -> DailySummary:
    """
    Full daily analysis pipeline:

    1. Load state, known senders, and tasks.
    2. Determine 'since' timestamp (last run, override, or fallback).
    3. Fetch unread email summaries from Gmail.
    4. If none, return a trivial DailySummary.
    5. Pass 1 LLM: decide which emails to expand and propose preliminary task ops.
    6. Fetch bodies for those emails.
    7. Pass 2 LLM: refine task ops, update senders, and generate DailySummary.
    8. Apply ops, merge senders, optionally update state, persist, and return DailySummary.

    Args:
        since_override: if provided, use this as the 'since' time instead of
                        state.last_run_at or the 24-hour fallback.
        update_state:   if False, do NOT update state.last_run_at.
    """
    logger.info("Starting daily analysis.")

    # Load persistent state
    state = load_state(config)
    known_senders = load_known_senders(config)
    tasks_file = load_tasks(config)
    instructions_text = load_instructions(config)

    # Determine 'since' timestamp
    if since_override is not None:
        since = since_override
        logger.info("Using override 'since' timestamp: %s", since.isoformat())
    elif state.last_run_at is not None:
        since = state.last_run_at
        logger.info("Using last_run_at from state: %s", since.isoformat())
    else:
        # Fallback: last 24 hours
        since = datetime.now(timezone.utc) - timedelta(days=1)
        logger.info("No last_run_at in state; defaulting to last 24 hours: %s", since.isoformat())

    # Build Gmail service and list unread summaries
    service = build_gmail_service(config)
    unread_summaries = list_unread_summaries_since(
        service,
        since_datetime=since,
        max_results=config.max_emails_per_run,
    )
    logger.info("Found %d unread summaries.", len(unread_summaries))

    if not unread_summaries:
        # No new emails to process
        now = datetime.now(timezone.utc)
        if update_state:
            state.last_run_at = now
            save_state(config, state)

        summary = DailySummary(
            summary_date=date.today(),
            critical_emails=[],
            suggested_responses=[],
            other_notes="No unread emails since the selected time window.",
        )
        logger.info("No unread emails; returning trivial DailySummary.")
        return summary

    # -----------------------------
    # Pass 1: metadata-only
    # -----------------------------
    from .models import TaskOperation  # local import to avoid cycles in some IDEs

    try:
        messages1 = build_pass1_messages(
            unread_summaries,
            known_senders,
            tasks_file,
            instructions_text=instructions_text,
        )
        raw1 = call_llm_json(config, messages1, max_tokens=2000, temperature=0.2)
    except LLMError as e:
        logger.exception("Pass 1 LLM error: %s", e)
        return _fallback_summary_on_llm_error(e)

    emails_to_expand = raw1.get("emails_to_expand") or []
    raw_task_ops1 = raw1.get("task_ops") or []

    preliminary_task_ops: List[TaskOperation] = []
    for op_dict in raw_task_ops1:
        try:
            if "op" in op_dict and isinstance(op_dict["op"], str):
                op_dict["op"] = op_dict["op"].lower()
            op = TaskOperation.model_validate(op_dict)
            preliminary_task_ops.append(op)
        except ValidationError as ve:
            logger.warning(
                "Skipping invalid TaskOperation from pass1. Raw op=%r; error=%s",
                op_dict,
                ve,
            )

    logger.info(
        "Pass 1: model requested %d emails to expand and produced %d preliminary task ops.",
        len(emails_to_expand),
        len(preliminary_task_ops),
    )

    # Fetch full bodies for requested emails
    expanded_bodies = []
    if emails_to_expand:
        expanded_bodies = fetch_email_bodies(service, emails_to_expand)
        logger.info("Fetched %d email bodies for expansion.", len(expanded_bodies))
    else:
        logger.info("Model did not request any email bodies to expand.")

    # -----------------------------
    # Pass 2: with full bodies
    # -----------------------------
    from .models import DailySummary as DailySummaryModel  # for clarity

    try:
        messages2 = build_pass2_messages(
            expanded_emails=expanded_bodies,
            known_senders=known_senders,
            tasks=tasks_file,
            preliminary_task_ops=preliminary_task_ops,
            instructions_text=instructions_text,
        )
        raw2 = call_llm_json(config, messages2, max_tokens=2500, temperature=0.2)
    except LLMError as e:
        logger.exception("Pass 2 LLM error: %s", e)
        return _fallback_summary_on_llm_error(e)

    raw_updated_senders = raw2.get("updated_senders") or []
    raw_final_ops = raw2.get("final_task_ops") or []
    raw_daily_summary = raw2.get("daily_summary") or {}

    updated_sender_profiles: List[SenderProfile] = []
    for s_dict in raw_updated_senders:
        try:
            s = SenderProfile.model_validate(s_dict)
            updated_sender_profiles.append(s)
        except ValidationError as ve:
            logger.warning("Skipping invalid SenderProfile from pass2: %s", ve)

    final_task_ops: List[TaskOperation] = []
    for op_dict in raw_final_ops:
    try:
        if "operation" in op_dict and "op" not in op_dict:
            op_dict["op"] = op_dict.pop("operation")

        if "op" in op_dict and isinstance(op_dict["op"], str):
            op_dict["op"] = op_dict["op"].lower()

        task_dict = op_dict.get("task")
        if isinstance(task_dict, dict):
            for ts_key in ("created_at", "updated_at"):
                if task_dict.get(ts_key) is None:
                    task_dict.pop(ts_key, None)
            op_dict["task"] = task_dict

        op = TaskOperation.model_validate(op_dict)
        final_task_ops.append(op)


    try:
        daily_summary = DailySummaryModel.model_validate(raw_daily_summary)
    except ValidationError as ve:
        logger.exception("Failed to validate DailySummary from LLM: %s", ve)
        return _fallback_summary_on_llm_error(ve)

    # Apply task ops and sender updates
    tasks_file = apply_task_operations(tasks_file, final_task_ops)
    known_senders = merge_sender_updates(known_senders, updated_sender_profiles)

    # Persist updated tasks & senders
    save_tasks(config, tasks_file)
    save_known_senders(config, known_senders)

    # Optionally update state.last_run_at
    if update_state:
        state.last_run_at = datetime.now(timezone.utc)
        save_state(config, state)

    logger.info(
        "Daily analysis complete: %d critical emails, %d suggested responses, %d tasks total.",
        len(daily_summary.critical_emails),
        len(daily_summary.suggested_responses),
        len(tasks_file.tasks),
    )

    return daily_summary

def run_rescan_days(config: Config, days: int) -> List[DailySummary]:
    """
    Multi-day rescan: for each of the past N days, run a full one-day analysis.

    - For each day, we:
        * Fetch INBOX summaries (read + unread) for that day only.
        * Run the two-pass LLM analysis for that day's emails.
        * Apply task operations and sender updates incrementally.
    - We do NOT update state.last_run_at.
    - We return a list of DailySummary objects, one per day that had emails.
    """
    logger.info("Starting multi-day rescan for last %d days.", days)

    # Load stateful bits once
    _state = load_state(config)  # not modified here
    known_senders = load_known_senders(config)
    tasks_file = load_tasks(config)
    instructions_text = load_instructions(config)

    service = build_gmail_service(config)

    now = datetime.now(timezone.utc)
    today = now.date()

    # Build day windows from oldest to newest
    windows: List[tuple[date, datetime, datetime]] = []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset - 1)
        start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        windows.append((day, start, end))

    all_summaries: List[DailySummary] = []

    for day, start, end in windows:
        logger.info(
            "Rescan: processing window %s (%s to %s)",
            day.isoformat(),
            start.isoformat(),
            end.isoformat(),
        )

        unread_summaries = list_unread_summaries_between(
            service,
            start_datetime=start,
            end_datetime=end,
            max_results=config.max_emails_per_run,
        )

        logger.info(
            "Rescan: found %d summaries for %s",
            len(unread_summaries),
            day.isoformat(),
        )

        if not unread_summaries:
            # No emails that day; skip
            continue

        # ----- Pass 1 -----
        try:
            messages1 = build_pass1_messages(
                unread_summaries,
                known_senders,
                tasks_file,
                instructions_text=instructions_text,
            )
            raw1 = call_llm_json(config, messages1, max_tokens=2000, temperature=0.2)
        except LLMError as e:
            logger.exception("Rescan pass 1 LLM error for %s: %s", day.isoformat(), e)
            # Record a fallback summary for that day and continue
            fallback = _fallback_summary_on_llm_error(e)
            fallback.summary_date = day
            all_summaries.append(fallback)
            continue

        emails_to_expand = raw1.get("emails_to_expand") or []
        raw_task_ops1 = raw1.get("task_ops") or []

        preliminary_task_ops: List[TaskOperationModel] = []
        for op_dict in raw_task_ops1:
            try:
                # ----- normalize TaskOperation (same as run_daily_analysis) -----
                # Allow "operation" as an alias for "op"
                if "operation" in op_dict and "op" not in op_dict:
                    op_dict["op"] = op_dict.pop("operation")

                # Normalize op to lowercase string
                if "op" in op_dict and isinstance(op_dict["op"], str):
                    op_dict["op"] = op_dict["op"].lower()

                # Clean up nested task payload a bit
                task_dict = op_dict.get("task")
                if isinstance(task_dict, dict):
                    for ts_key in ("created_at", "updated_at"):
                        if task_dict.get(ts_key) is None:
                            task_dict.pop(ts_key, None)
                    op_dict["task"] = task_dict
                # ----- end normalization -----

                op = TaskOperationModel.model_validate(op_dict)
                preliminary_task_ops.append(op)
            except Exception as ve:
                logger.warning(
                    "Rescan: skipping invalid TaskOperation from pass1 (%s): %s",
                    day.isoformat(),
                    ve,
                )

        # Fetch full bodies
        expanded_bodies = []
        if emails_to_expand:
            expanded_bodies = fetch_email_bodies(service, emails_to_expand)
            logger.info(
                "Rescan: fetched %d email bodies for %s",
                len(expanded_bodies),
                day.isoformat(),
            )

        # ----- Pass 2 -----
        try:
            messages2 = build_pass2_messages(
                expanded_emails=expanded_bodies,
                known_senders=known_senders,
                tasks=tasks_file,
                preliminary_task_ops=preliminary_task_ops,
                instructions_text=instructions_text,
            )
            raw2 = call_llm_json(config, messages2, max_tokens=2500, temperature=0.2)
        except LLMError as e:
            logger.exception("Rescan pass 2 LLM error for %s: %s", day.isoformat(), e)
            fallback = _fallback_summary_on_llm_error(e)
            fallback.summary_date = day
            all_summaries.append(fallback)
            continue

        raw_updated_senders = raw2.get("updated_senders") or []
        raw_final_ops = raw2.get("final_task_ops") or []
        raw_daily_summary = raw2.get("daily_summary") or {}

        updated_sender_profiles: List[SenderProfile] = []
        for s_dict in raw_updated_senders:
            try:
                s = SenderProfile.model_validate(s_dict)
                updated_sender_profiles.append(s)
            except Exception as ve:
                logger.warning(
                    "Rescan: skipping invalid SenderProfile from pass2 (%s): %s",
                    day.isoformat(),
                    ve,
                )

        final_task_ops: List[TaskOperationModel] = []
        for op_dict in raw_final_ops:
            try:
                # ----- normalize TaskOperation (same as run_daily_analysis) -----
                if "operation" in op_dict and "op" not in op_dict:
                    op_dict["op"] = op_dict.pop("operation")

                if "op" in op_dict and isinstance(op_dict["op"], str):
                    op_dict["op"] = op_dict["op"].lower()

                task_dict = op_dict.get("task")
                if isinstance(task_dict, dict):
                    for ts_key in ("created_at", "updated_at"):
                        if task_dict.get(ts_key) is None:
                            task_dict.pop(ts_key, None)
                    op_dict["task"] = task_dict
                # ----- end normalization -----

                op = TaskOperationModel.model_validate(op_dict)
                final_task_ops.append(op)
            except Exception as ve:
                logger.warning(
                    "Rescan: skipping invalid TaskOperation from pass2 (%s): %s",
                    day.isoformat(),
                    ve,
                )

        try:
            daily_summary = DailySummary.model_validate(raw_daily_summary)
        except Exception as ve:
            logger.exception(
                "Rescan: failed to validate DailySummary for %s: %s",
                day.isoformat(),
                ve,
            )
            fallback = _fallback_summary_on_llm_error(ve)
            fallback.summary_date = day
            all_summaries.append(fallback)
            continue

        # Override the summary_date to the day we are analyzing
        daily_summary.summary_date = day

        # Apply task ops and sender updates IN-PLACE (cumulative across days)
        tasks_file = apply_task_operations(tasks_file, final_task_ops)
        known_senders = merge_sender_updates(known_senders, updated_sender_profiles)

        all_summaries.append(daily_summary)

    # Persist updated tasks & senders once at the end
    save_tasks(config, tasks_file)
    save_known_senders(config, known_senders)

    logger.info(
        "Multi-day rescan complete: %d daily summaries produced, %d tasks total.",
        len(all_summaries),
        len(tasks_file.tasks),
    )

    return all_summaries

# ---------------------------------------------------------------------------
# Fallback summary helpers
# ---------------------------------------------------------------------------


def _fallback_summary_on_llm_error(error: Exception) -> DailySummary:
    """
    Produce a minimal DailySummary if the LLM call fails.

    This keeps the CLI from crashing and gives you a clear indication of failure.
    """
    logger.error("LLM error, returning fallback DailySummary: %s", error)

    dummy_critical = CriticalEmailEntry(
        email_id="(none)",
        thread_id="(none)",
        summary="LLM call failed during daily analysis.",
        reason_critical=str(error),
        recommended_action="Check logs, API key, and model configuration.",
        linked_task_ids=[],
    )

    return DailySummary(
        summary_date=date.today(),
        critical_emails=[dummy_critical],
        suggested_responses=[],
        other_notes="Daily analysis failed due to LLM error; no changes were applied.",
    )
