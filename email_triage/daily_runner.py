"""
Daily summary formatting and output helpers.
"""

from pathlib import Path

from .models import DailySummary


def generate_daily_summary_text(summary: DailySummary) -> str:
    """Convert a DailySummary into a human-readable markdown string."""
    lines: list[str] = []

    lines.append(f"# Daily Email Triage — {summary.summary_date.isoformat()}")
    lines.append("")

    # ------------------------------------------------------------------
    # Critical Emails
    # ------------------------------------------------------------------
    lines.append("## Critical Emails")
    if not summary.critical_emails:
        lines.append("")
        lines.append("_No critical emails identified today._")
    else:
        lines.append("")
        for idx, ce in enumerate(summary.critical_emails, start=1):
            lines.append(
                f"{idx}. **Thread:** `{ce.thread_id}` — **Email ID:** `{ce.email_id}`"
            )
            lines.append(f"   - **Summary:** {ce.summary}")
            lines.append(f"   - **Reason:** {ce.reason_critical}")
            lines.append(f"   - **Recommended action:** {ce.recommended_action}")
            if ce.linked_task_ids:
                tasks_str = ", ".join(ce.linked_task_ids)
                lines.append(f"   - **Linked tasks:** {tasks_str}")
            lines.append("")

    # ------------------------------------------------------------------
    # Suggested Responses
    # ------------------------------------------------------------------
    lines.append("## Suggested Responses")
    if not summary.suggested_responses:
        lines.append("")
        lines.append("_No suggested responses for today._")
    else:
        lines.append("")
        for idx, sr in enumerate(summary.suggested_responses, start=1):
            lines.append(f"{idx}. **Email ID:** `{sr.email_id}`")
            if sr.draft_outline:
                lines.append("   - **Outline:**")
                for bullet in sr.draft_outline:
                    lines.append(f"     - {bullet}")
            lines.append("")

    # ------------------------------------------------------------------
    # Other Notes
    # ------------------------------------------------------------------
    lines.append("## Other Notes")
    lines.append("")
    if summary.other_notes:
        lines.append(summary.other_notes)
    else:
        lines.append("_No additional notes._")

    lines.append("")  # final newline

    return "\n".join(lines)


def write_daily_summary_to_file(config, summary_text: str) -> Path:
    """Write the daily summary text to the configured output path."""
    path: Path = config.daily_summary_output_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary_text, encoding="utf-8")
    return path
