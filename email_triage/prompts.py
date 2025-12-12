"""
Prompt templates for the two-pass LLM analysis and instructions refinement.
"""

from typing import Any, Dict, List

from .models import (
    EmailSummary,
    EmailBody,
    KnownSendersFile,
    TasksFile,
    TaskOperation,
)


def _serialize_email_summaries(summaries: List[EmailSummary]) -> List[Dict[str, Any]]:
    return [s.model_dump(mode="json") for s in summaries]


def _serialize_email_bodies(bodies: List[EmailBody]) -> List[Dict[str, Any]]:
    return [b.model_dump(mode="json") for b in bodies]


def _serialize_known_senders(known_senders: KnownSendersFile) -> Dict[str, Any]:
    return known_senders.model_dump(mode="json")


def _serialize_tasks(tasks: TasksFile) -> Dict[str, Any]:
    return tasks.model_dump(mode="json")


def _serialize_task_ops(ops: List[TaskOperation]) -> List[Dict[str, Any]]:
    return [op.model_dump(mode="json") for op in ops]


def _pretty_json(obj: Any) -> str:
    import json

    return json.dumps(obj, indent=2, sort_keys=False, default=str)


# ---------------------------------------------------------------------------
# Pass 1 prompt
# ---------------------------------------------------------------------------


def build_pass1_messages(
    unread_summaries: List[EmailSummary],
    known_senders: KnownSendersFile,
    tasks: TasksFile,
    instructions_text: str,
) -> List[Dict[str, str]]:
    """
    Build messages for the first LLM pass (metadata only).
    """
    system_content = (
        "You are an email triage assistant. Your job is to examine summaries of"
        " unread emails, along with metadata about known senders and an existing"
        " task list, and decide which emails are important and which tasks should"
        " be added, updated, or closed.\n\n"
        "You will also be given a block of user instructions describing their"
        " preferences and priorities. Always follow those instructions when making"
        " decisions about importance and tasks.\n\n"
        "CRITICAL RULES:\n"
        "1. You MUST output a single JSON object, with no surrounding text.\n"
        "2. The JSON object MUST have exactly these keys:\n"
        '   - "emails_to_expand": an array of Gmail message IDs (strings)\n'
        '   - "task_ops": an array of TaskOperation objects\n'
        "3. For TaskOperation objects:\n"
        '   - op: one of "add", "update", "close" (lowercase)\n'
        "   - For op='add': provide a 'task' object with all relevant fields.\n"
        "   - For op='update': provide 'task_id' and 'fields' (partial updates).\n"
        "   - For op='close': provide 'task_id'.\n"
        "4. DO NOT include comments or explanations in the JSON.\n"
    )

    user_payload = {
        "instructions_text": instructions_text,
        "unread_summaries": _serialize_email_summaries(unread_summaries),
        "known_senders": _serialize_known_senders(known_senders),
        "tasks": _serialize_tasks(tasks),
    }

    user_content = (
        "Here is the current state, today's unread email summaries, and my current"
        " instructions/preferences.\n\n"
        "Input JSON:\n"
        + _pretty_json(user_payload)
        + "\n\n"
        "Decide which email message IDs require full text to reason about"
        " accurately today, and propose initial task operations.\n"
        "Remember: respond with ONLY the JSON object."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Pass 2 prompt
# ---------------------------------------------------------------------------


def build_pass2_messages(
    expanded_emails: List[EmailBody],
    known_senders: KnownSendersFile,
    tasks: TasksFile,
    preliminary_task_ops: List[TaskOperation],
    instructions_text: str,
) -> List[Dict[str, str]]:
    """
    Build messages for the second LLM pass (with full email bodies).
    """
    system_content = (
        "You are an email triage assistant performing a second, deeper analysis."
        " You now have the full bodies of selected emails. Based on these, plus"
        " the existing task list, known senders, and the user's instructions, you"
        " must:\n"
        "1. Refine the task operations from the first pass.\n"
        "2. Update sender profiles as needed (importance, role, notes, etc.).\n"
        "3. Produce a DailySummary of critical emails and suggested responses.\n\n"
        "Always follow the user's instructions/preferences when deciding what is"
        " important or which tasks to create or prioritize.\n\n"
        "CRITICAL RULES:\n"
        "1. You MUST output a single JSON object, with no surrounding text.\n"
        "2. The JSON object MUST have exactly these keys:\n"
        '   - "updated_senders": array of SenderProfile objects\n'
        '   - "final_task_ops": array of TaskOperation objects\n'
        '   - "daily_summary": a DailySummary object\n'
        "3. Do not invent task_ids; for new tasks in ADD operations, leave 'id'"
        " empty or null and let the system assign it.\n"
        "4. DailySummary must include:\n"
        "   - summary_date: ISO date string (YYYY-MM-DD)\n"
        "   - critical_emails: array of objects with keys\n"
        "       email_id, thread_id, summary, reason_critical,\n"
        "       recommended_action, linked_task_ids\n"
        "   - suggested_responses: array of objects with keys\n"
        "       email_id, draft_outline (array of strings), full_draft (optional)\n"
        "   - other_notes: optional string\n"
        "5. For ALL string fields (including notes, reason_critical, "
        "recommended_action, other_notes, and full_draft), you MUST NOT use raw "
        "newline characters inside the string. Each string value must be a single "
        "line. If you need line breaks, either:\n"
        "   - encode them as '\\n' characters inside the string, or\n"
        "   - represent multi-paragraph text as an array of strings "
        "(like draft_outline).\n"
        "6. DO NOT include comments or explanations in the JSON.\n"
    )

    user_payload = {
        "instructions_text": instructions_text,
        "expanded_emails": _serialize_email_bodies(expanded_emails),
        "known_senders": _serialize_known_senders(known_senders),
        "tasks": _serialize_tasks(tasks),
        "preliminary_task_ops": _serialize_task_ops(preliminary_task_ops),
    }

    user_content = (
        "Here are the full bodies of selected emails, my current instructions,"
        " and the current state plus preliminary task operations from the first"
        " pass.\n\n"
        "Input JSON:\n"
        + _pretty_json(user_payload)
        + "\n\n"
        "Refine the task operations, update sender profiles, and produce a"
        " DailySummary as specified.\n"
        "Remember: respond with ONLY the JSON object."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Instructions refinement prompt
# ---------------------------------------------------------------------------


def build_instructions_update_messages(
    current_instructions: str,
    feedback: str,
) -> List[Dict[str, str]]:
    """
    Build messages for refining the instructions.txt file based on user feedback.

    The model MUST output JSON:
        { "instructions": "<new instructions text>" }
    """
    system_content = (
        "You are helping a user refine a set of instructions for an email triage"
        " assistant. The assistant reads email summaries and bodies, uses"
        " metadata about known senders, and maintains a task list.\n\n"
        "You will be given:\n"
        "  1) The current instructions text.\n"
        "  2) The user's free-form feedback after a run.\n\n"
        "Your job is to produce a *better* instructions text that incorporates the"
        " feedback while remaining clear and concise. The instructions should be"
        " written as plain English, suitable to be stored in a text file and"
        " injected into the model's context on future runs.\n\n"
        "CRITICAL RULES:\n"
        "1. You MUST output a single JSON object of the form:\n"
        '   { "instructions": "..." }\n'
        "2. The value of \"instructions\" must be a single string containing the"
        " full new instructions.\n"
        "3. DO NOT include any commentary or additional keys.\n"
    )

    user_content = (
        "Here are the current instructions and my feedback.\n\n"
        "CURRENT INSTRUCTIONS:\n"
        "---------------------\n"
        f"{current_instructions}\n\n"
        "USER FEEDBACK:\n"
        "--------------\n"
        f"{feedback}\n\n"
        "Please produce improved instructions as described."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
