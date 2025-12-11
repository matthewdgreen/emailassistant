import logging
from pathlib import Path


def setup_logging(level: int = logging.INFO, log_to_file: bool = False) -> None:
    """Configure root logging for the application."""
    log_format = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]

    if log_to_file:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(logs_dir / "email_triage.log")
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=handlers,
    )
