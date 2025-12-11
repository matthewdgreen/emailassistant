from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """
    Application configuration loaded from environment variables and .env file.
    """

    # Data directory and file paths
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")

    known_senders_path: Path = Field(
        default=Path("data") / "known_senders.json",
        alias="KNOWN_SENDERS_PATH",
    )
    tasks_path: Path = Field(
        default=Path("data") / "tasks.json",
        alias="TASKS_PATH",
    )
    state_path: Path = Field(
        default=Path("data") / "state.json",
        alias="STATE_PATH",
    )
    daily_summary_output_path: Path = Field(
        default=Path("data") / "daily_summary.md",
        alias="DAILY_SUMMARY_OUTPUT_PATH",
    )

    # New: instructions file
    instructions_path: Path = Field(
        default=Path("data") / "instructions.txt",
        alias="INSTRUCTIONS_PATH",
    )

    # Gmail OAuth
    gmail_credentials_path: Path = Field(
        default=Path("credentials.json"),
        alias="GMAIL_CREDENTIALS_PATH",
    )
    gmail_token_path: Path = Field(
        default=Path("token.json"),
        alias="GMAIL_TOKEN_PATH",
    )

    # LLM
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    model_name: str = Field(default="gpt-4.1-mini", alias="MODEL_NAME")

    # Email triage
    max_emails_per_run: int = Field(
        default=50,
        alias="MAX_EMAILS_PER_RUN",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def load_config() -> "Config":
    return Config()
