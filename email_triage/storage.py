"""
Storage helpers for JSON state files and instructions.txt.
"""

from pathlib import Path
from typing import Any

from .config import Config
from .models import KnownSendersFile, TasksFile, StateFile


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return text


def ensure_data_files_exist(config: Config) -> None:
    """
    Ensure that the data directory and core files exist.

    Creates:
      - known_senders.json
      - tasks.json
      - state.json
      - instructions.txt (new)
    """
    data_dir = config.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    # known_senders.json
    if not config.known_senders_path.exists():
        ks = KnownSendersFile()
        config.known_senders_path.write_text(
            ks.model_dump_json(indent=2),
            encoding="utf-8",
        )

    # tasks.json
    if not config.tasks_path.exists():
        tf = TasksFile()
        config.tasks_path.write_text(
            tf.model_dump_json(indent=2),
            encoding="utf-8",
        )

    # state.json
    if not config.state_path.exists():
        sf = StateFile()
        config.state_path.write_text(
            sf.model_dump_json(indent=2),
            encoding="utf-8",
        )

    # instructions.txt
    if not config.instructions_path.exists():
        default_instructions = (
            "Email triage instructions\n"
            "=========================\n\n"
            "- Prioritize emails from pinned or high-importance senders.\n"
            "- Students, collaborators, and family are generally high priority.\n"
            "- Bulk notifications, newsletters, and automated alerts are lower priority\n"
            "  unless they mention deadlines or urgent actions.\n"
            "- For each important email, create or update tasks that clearly state\n"
            "  what I need to do and by when.\n"
            "- Summaries should be concise but must include:\n"
            "    * who is writing,\n"
            "    * what they want,\n"
            "    * any deadlines, and\n"
            "    * whether I owe a reply.\n"
            "- Avoid suggesting replies to emails that are obviously spam or purely\n"
            "  informational.\n"
        )
        config.instructions_path.write_text(default_instructions, encoding="utf-8")


# ---------------------------------------------------------------------------
# Known senders
# ---------------------------------------------------------------------------


def load_known_senders(config: Config) -> KnownSendersFile:
    path = config.known_senders_path
    if not path.exists():
        return KnownSendersFile()
    text = path.read_text(encoding="utf-8")
    return KnownSendersFile.model_validate_json(text)


def save_known_senders(config: Config, known_senders: KnownSendersFile) -> None:
    path = config.known_senders_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(known_senders.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def load_tasks(config: Config) -> TasksFile:
    path = config.tasks_path
    if not path.exists():
        return TasksFile()
    text = path.read_text(encoding="utf-8")
    return TasksFile.model_validate_json(text)


def save_tasks(config: Config, tasks_file: TasksFile) -> None:
    path = config.tasks_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tasks_file.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def load_state(config: Config) -> StateFile:
    path = config.state_path
    if not path.exists():
        return StateFile()
    text = path.read_text(encoding="utf-8")
    return StateFile.model_validate_json(text)


def save_state(config: Config, state: StateFile) -> None:
    path = config.state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Instructions.txt
# ---------------------------------------------------------------------------


def load_instructions(config: Config) -> str:
    path = config.instructions_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_instructions(config: Config, text: str) -> None:
    path = config.instructions_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
