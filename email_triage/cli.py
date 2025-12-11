import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

from rich.console import Console
from rich.table import Table

from .config import load_config
from .logging_config import setup_logging
from .analysis_engine import run_daily_analysis, apply_task_operations
from .daily_runner import generate_daily_summary_text, write_daily_summary_to_file
from .storage import (
    ensure_data_files_exist,
    load_tasks,
    save_tasks,
    load_known_senders,
    save_known_senders,
    load_instructions,
    save_instructions,
)
from .models import (
    Task,
    TaskOperation,
    TaskOperationType,
    TaskStatus,
    SenderProfile,
    SenderImportance,
    SenderRole,
)
from .prompts import build_instructions_update_messages
from .llm_client import call_llm_json, LLMError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_tasks_table(tasks_file) -> None:
    console = Console()
    table = Table(title="Tasks")

    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Due Date")
    table.add_column("Description")

    for t in tasks_file.tasks:
        status = getattr(t.status, "value", str(t.status))
        due = t.due_date.isoformat() if getattr(t, "due_date", None) else ""
        table.add_row(
            t.id,
            status,
            str(t.priority),
            due,
            t.description,
        )

    console.print(table)


def _render_senders_table(known_senders) -> None:
    console = Console()
    table = Table(title="Known Senders")

    table.add_column("Email")
    table.add_column("Name")
    table.add_column("Importance")
    table.add_column("Role")
    table.add_column("Pinned")
    table.add_column("Last Seen")

    def sort_key(s: SenderProfile):
        return (
            s.importance != SenderImportance.HIGH,
            not s.pinned,
            s.email.lower(),
        )

    for s in sorted(known_senders.senders, key=sort_key):
        table.add_row(
            s.email,
            s.name or "",
            s.importance.value,
            s.role.value,
            "yes" if s.pinned else "no",
            s.last_seen_at.isoformat() if s.last_seen_at else "",
        )

    console.print(table)


def _parse_optional_date(date_str: Optional[str]):
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _interactive_instructions_update() -> None:
    """
    Ask the user for feedback, then refine instructions.txt using the LLM.
    """
    config = load_config()
    current = load_instructions(config)

    print("")
    print("=== Instructions refinement mode ===")
    print("Enter your feedback about today's results.")
    print("Example topics: which emails were mis-prioritized, which tasks were")
    print("missing or unnecessary, what 'important' means to you, etc.")
    print("")
    print("Type your feedback. End with an empty line on its own.")
    print("-------------------------------------")

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "" and lines:
            break
        lines.append(line)

    feedback = "\n".join(lines).strip()
    if not feedback:
        print("No feedback provided; leaving instructions unchanged.")
        return

    messages = build_instructions_update_messages(current_instructions=current, feedback=feedback)

    try:
        resp = call_llm_json(config, messages, max_tokens=1200, temperature=0.3)
    except LLMError as e:
        print(f"Failed to update instructions via LLM: {e}")
        return

    new_text = resp.get("instructions")
    if not isinstance(new_text, str) or not new_text.strip():
        print("LLM returned invalid instructions; leaving file unchanged.")
        return

    save_instructions(config, new_text)
    print("")
    print("Instructions updated and written to instructions.txt.")
    print("You can open that file to review/edit them further if you like.")


# ---------------------------------------------------------------------------
# Commands: daily run & tasks
# ---------------------------------------------------------------------------


def cmd_run_daily(args: argparse.Namespace) -> None:
    config = load_config()
    setup_logging()
    ensure_data_files_exist(config)

    logging.info("Running daily analysis...")
    summary = run_daily_analysis(config)
    text = generate_daily_summary_text(summary)
    path = write_daily_summary_to_file(config, text)
    print(text)
    logging.info("Daily summary written to %s", path)

    if args.instruct:
        _interactive_instructions_update()


def cmd_show_tasks() -> None:
    config = load_config()
    setup_logging()
    ensure_data_files_exist(config)

    tasks_file = load_tasks(config)
    _render_tasks_table(tasks_file)


def cmd_add_task(args: argparse.Namespace) -> None:
    config = load_config()
    setup_logging()
    ensure_data_files_exist(config)

    tasks_file = load_tasks(config)
    due_date = _parse_optional_date(args.due)

    task = Task(
        id="",
        description=args.description,
        priority=args.priority,
        status=TaskStatus.OPEN,
        due_date=due_date,
        source=args.source,
    )

    op = TaskOperation(
        op=TaskOperationType.ADD,
        task=task,
    )

    updated = apply_task_operations(tasks_file, [op])
    save_tasks(config, updated)

    new_id = task.id
    print(f"Added task {new_id!r}: {task.description}")


def cmd_complete_task(args: argparse.Namespace) -> None:
    config = load_config()
    setup_logging()
    ensure_data_files_exist(config)

    tasks_file = load_tasks(config)

    op = TaskOperation(
        op=TaskOperationType.CLOSE,
        task_id=args.id,
    )

    updated = apply_task_operations(tasks_file, [op])
    save_tasks(config, updated)

    print(f"Marked task {args.id!r} as DONE.")


# ---------------------------------------------------------------------------
# Command: rescan-days
# ---------------------------------------------------------------------------


def cmd_rescan_days(args: argparse.Namespace) -> None:
    config = load_config()
    setup_logging()
    ensure_data_files_exist(config)

    from .analysis_engine import run_daily_analysis as _run

    days = args.days
    since = datetime.now(timezone.utc) - timedelta(days=days)

    logging.info("Rescanning past %d days (since %s)...", days, since.isoformat())

    summary = _run(config, since_override=since, update_state=False)
    text = generate_daily_summary_text(summary)
    path = write_daily_summary_to_file(config, text)
    print(text)
    logging.info("Rescan summary written to %s", path)


# ---------------------------------------------------------------------------
# Commands: sender / VIP management
# ---------------------------------------------------------------------------


def cmd_list_senders() -> None:
    config = load_config()
    setup_logging()
    ensure_data_files_exist(config)

    known_senders = load_known_senders(config)
    _render_senders_table(known_senders)


def cmd_set_sender(args: argparse.Namespace) -> None:
    config = load_config()
    setup_logging()
    ensure_data_files_exist(config)

    known_senders = load_known_senders(config)

    email = args.email
    profiles = {s.email: s for s in known_senders.senders}
    profile = profiles.get(email) or SenderProfile(email=email)

    if args.name:
        profile.name = args.name

    if args.importance:
        profile.importance = SenderImportance(args.importance)

    if args.role:
        profile.role = SenderRole(args.role)

    if args.pin:
        profile.pinned = True
    if args.unpin:
        profile.pinned = False

    profiles[email] = profile
    known_senders.senders = list(profiles.values())
    save_known_senders(config, known_senders)

    print(
        f"Updated sender {email!r}: "
        f"importance={profile.importance.value}, "
        f"role={profile.role.value}, "
        f"pinned={profile.pinned}"
    )


# ---------------------------------------------------------------------------
# Main CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="email-triage",
        description="LLM-assisted email triage and task manager.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run-daily
    p_run = subparsers.add_parser("run-daily", help="Run the daily analysis and summary.")
    p_run.add_argument(
        "--instruct",
        action="store_true",
        help="After running, prompt for feedback and refine instructions.txt via the LLM.",
    )

    # show-tasks
    subparsers.add_parser("show-tasks", help="Show current tasks.")

    # add-task
    p_add = subparsers.add_parser("add-task", help="Add a new manual task.")
    p_add.add_argument(
        "description",
        type=str,
        help="Description of the task.",
    )
    p_add.add_argument(
        "-p",
        "--priority",
        type=int,
        default=5,
        help="Priority (1–10, higher means more important). Default: 5.",
    )
    p_add.add_argument(
        "--due",
        type=str,
        default=None,
        help="Optional due date in YYYY-MM-DD format.",
    )
    p_add.add_argument(
        "--source",
        type=str,
        default="manual",
        help="Task source (e.g., 'manual', 'email'). Default: 'manual'.",
    )

    # complete-task
    p_complete = subparsers.add_parser(
        "complete-task",
        help="Mark a task as DONE.",
    )
    p_complete.add_argument(
        "id",
        type=str,
        help="ID of the task to mark as done.",
    )

    # rescan-days
    p_rescan = subparsers.add_parser(
        "rescan-days",
        help="Re-run analysis over the past N days, without updating last_run_at.",
    )
    p_rescan.add_argument(
        "--days",
        type=int,
        default=3,
        help="Number of days back to scan (default: 3).",
    )

    # list-senders
    subparsers.add_parser(
        "list-senders",
        help="List known senders and their importance / pinned status.",
    )

    # set-sender
    p_set_sender = subparsers.add_parser(
        "set-sender",
        help="Create or update a sender profile (importance, role, pinned, name).",
    )
    p_set_sender.add_argument(
        "email",
        type=str,
        help="Sender email address.",
    )
    p_set_sender.add_argument(
        "--name",
        type=str,
        default=None,
        help="Optional human-readable name for the sender.",
    )
    p_set_sender.add_argument(
        "--importance",
        type=str,
        choices=["high", "normal", "low"],
        default=None,
        help="Importance level: high, normal, or low.",
    )
    p_set_sender.add_argument(
        "--role",
        type=str,
        choices=[
            "student",
            "collaborator",
            "admin",
            "family",
            "notification",
            "other",
        ],
        default=None,
        help="Role of the sender.",
    )
    p_set_sender.add_argument(
        "--pin",
        action="store_true",
        help="Mark this sender as pinned (VIP).",
    )
    p_set_sender.add_argument(
        "--unpin",
        action="store_true",
        help="Unpin this sender.",
    )

    args = parser.parse_args()

    if args.command == "run-daily":
        cmd_run_daily(args)
    elif args.command == "show-tasks":
        cmd_show_tasks()
    elif args.command == "add-task":
        cmd_add_task(args)
    elif args.command == "complete-task":
        cmd_complete_task(args)
    elif args.command == "rescan-days":
        cmd_rescan_days(args)
    elif args.command == "list-senders":
        cmd_list_senders()
    elif args.command == "set-sender":
        cmd_set_sender(args)
    else:
        parser.error(f"Unknown command: {args.command!r}")


if __name__ == "__main__":
    main()
