"""
LLM client wrapper.

This module provides a thin wrapper around an OpenAI-compatible chat
completion API using httpx. It expects the model to return *JSON* and
handles extraction / parsing (including code-fence-wrapped JSON).
"""

import json
import logging
from typing import Any, Dict, List

import httpx
from .lenient_json import parse_lenient_json
from .config import Config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Generic error raised by the LLM client."""


def _extract_json_from_text(text: str) -> str:
    """
    Extract a JSON object from raw model text.

    The model might respond with:
    - pure JSON
    - JSON wrapped in ```json ... ```
    - JSON wrapped in ``` ... ```
    - leading/trailing commentary (we try to ignore it)

    Strategy:
    - Find the first '{' and the last '}' and slice between them.
    - It's simple but robust enough for our use case.
    """
    text = text.strip()
    if not text:
        raise LLMError("Empty response from model when JSON was expected.")

    # If it contains fenced blocks, try to strip them
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            # parts[1] is after first ```, maybe "json\n{...}"
            inner = parts[1]
            # Drop a leading "json" line if present
            stripped = inner.lstrip()
            if stripped.lower().startswith("json"):
                inner = inner.split("\n", 1)[-1]
            text = inner.strip()

    # Now find the outermost braces
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        raise LLMError("Could not locate a JSON object in the model response.")

    return text[first : last + 1]


def call_llm_json(
    config: Config,
    messages: List[Dict[str, str]],
    max_tokens: int = 2000,
    temperature: float = 0.2,
    base_url: str = "https://api.openai.com/v1/chat/completions",
) -> Dict[str, Any]:
    """
    Call the LLM with a list of messages and parse a JSON response.

    Arguments:
        config: Config containing openai_api_key and model_name.
        messages: List of {'role': 'system'|'user'|'assistant', 'content': str}
        max_tokens: Maximum tokens for the response.
        temperature: Sampling temperature.
        base_url: Chat completions endpoint for an OpenAI-compatible API.

    Returns:
        Parsed JSON (as a Python dict).

    Raises:
        LLMError: on HTTP or JSON parsing errors.
    """
    if not config.openai_api_key:
        raise LLMError("OPENAI_API_KEY (or equivalent) is not set in config.")

    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": config.model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    try:
        logger.info("Calling LLM model=%s", config.model_name)
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(base_url, headers=headers, json=payload)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.exception("HTTP error calling LLM: %s", e)
        raise LLMError(f"HTTP error from LLM API: {e}") from e

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        logger.exception("Failed to decode JSON from LLM HTTP response: %s", e)
        raise LLMError("Invalid JSON from LLM HTTP response.") from e


    try:
        choices = data.get("choices")
        if not choices:
            raise LLMError("No choices in LLM response.")
        content = choices[0]["message"]["content"]
    except Exception as e:
        logger.exception("Unexpected structure in LLM response: %s", e)
        raise LLMError("Unexpected structure in LLM response.") from e

    # At this point, with response_format={"type": "json_object"}, `content`
    # should be a JSON object string. We still run it through a lenient parser
    # to survive minor syntax issues.
    try:
        snippet = content if isinstance(content, str) else repr(content)
        logger.debug("LLM raw content (first 500 chars): %s", snippet[:500])

        if isinstance(content, dict):
            # Already parsed somehow
            return content

        if not isinstance(content, str):
            raise LLMError(f"LLM content is neither string nor dict: {type(content)}")

        return parse_lenient_json(content,config=config,
            allow_llm_repair=True)

    except Exception as e:
        # Log for debugging and raise a clean error to the caller
        snippet = content if isinstance(content, str) else repr(content)
        logger.error(
            "Raw LLM content that failed lenient JSON parse (first 1000 chars): %s",
            snippet[:1000],
        )
        logger.exception("Failed to parse JSON from LLM content: %s", e)
        raise LLMError(f"Failed to parse JSON from LLM content: {e}") from e

