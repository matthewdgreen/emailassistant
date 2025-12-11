"""
Gmail client integration.

Provides:
- build_gmail_service: OAuth2 login + service construction
- list_unread_summaries_since: get EmailSummary objects for unread mail
- fetch_email_bodies: get EmailBody objects for selected messages
"""

import base64
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from .config import Config
from .models import EmailSummary, EmailBody

logger = logging.getLogger(__name__)

# For now we only need read-only access
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# ---------------------------------------------------------------------------
# OAuth + service
# ---------------------------------------------------------------------------


def build_gmail_service(config: Config):
    """
    Build and return an authorized Gmail API service.

    Uses:
    - config.gmail_credentials_path: client secret JSON from Google Cloud Console
    - config.gmail_token_path: where to store the user's access/refresh token

    First run will open a browser window for OAuth consent.
    """
    creds: Optional[Credentials] = None
    token_path = config.gmail_token_path
    credentials_path = config.gmail_credentials_path

    if token_path.exists():
        logger.info("Loading Gmail credentials from %s", token_path)
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # If no valid credentials, run the OAuth flow.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail credentials.")
            creds.refresh(Request())
        else:
            logger.info("Running new Gmail OAuth flow using %s", credentials_path)
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        token_path.write_text(creds.to_json(), encoding="utf-8")

    service = build("gmail", "v1", credentials=creds)
    return service


# ---------------------------------------------------------------------------
# Helpers for parsing Gmail message payloads
# ---------------------------------------------------------------------------


def _parse_header(headers: List[dict], name: str) -> Optional[str]:
    """Extract a header value (case-insensitive) from Gmail message headers."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _parse_from_header(from_value: str) -> (Optional[str], str):
    """
    Parse the From header into (name, email).

    We keep it simple: if it contains '<...>', we treat the part in angle brackets
    as the email, and everything before as the name.
    """
    if not from_value:
        return None, ""

    # Example: "Alice Smith <alice@example.org>"
    if "<" in from_value and ">" in from_value:
        name_part, email_part = from_value.split("<", 1)
        email_part = email_part.split(">", 1)[0].strip()
        name_part = name_part.strip().strip('"')
        name_part = name_part or None
        return name_part, email_part

    # Otherwise treat the whole thing as an email address
    return None, from_value.strip()


def _parse_date_header(date_value: str) -> datetime:
    """
    Parse RFC 2822 date header into an aware UTC datetime.

    If parsing fails, fall back to UTC 'now'.
    """
    if not date_value:
        return datetime.now(timezone.utc)

    try:
        dt = parsedate_to_datetime(date_value)
        if dt.tzinfo is None:
            # Assume UTC if no timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        logger.warning("Failed to parse Date header %r; using now().", date_value)
        return datetime.now(timezone.utc)


def _extract_bodies_from_payload(payload: dict) -> (str, Optional[str]):
    """
    Extract plain-text and HTML bodies from a Gmail message payload.

    Returns (body_text, body_html). Either may be empty/None.
    """
    def decode_body(body: dict) -> str:
        data = body.get("data")
        if not data:
            return ""
        try:
            decoded_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))
            return decoded_bytes.decode("utf-8", errors="replace")
        except Exception:
            logger.exception("Error decoding message body.")
            return ""

    mime_type = payload.get("mimeType", "")
    body_text = ""
    body_html = None

    if mime_type == "text/plain":
        body_text = decode_body(payload.get("body", {}))
    elif mime_type == "text/html":
        body_html = decode_body(payload.get("body", {}))
    elif mime_type.startswith("multipart/"):
        # Recursively search parts
        parts = payload.get("parts", []) or []
        text_chunks: List[str] = []
        html_chunks: List[str] = []
        for part in parts:
            part_text, part_html = _extract_bodies_from_payload(part)
            if part_text:
                text_chunks.append(part_text)
            if part_html:
                html_chunks.append(part_html)
        body_text = "\n".join(text_chunks).strip()
        if html_chunks:
            body_html = "\n".join(html_chunks).strip()
    else:
        # Fallback: try decoding the body directly
        body_text = decode_body(payload.get("body", {}))

    return body_text, body_html


# ---------------------------------------------------------------------------
# Listing unread summaries
# ---------------------------------------------------------------------------


def list_unread_summaries_since(
    service,
    since_datetime: Optional[datetime],
    max_results: int = 50,
) -> List[EmailSummary]:
    """
    Return a list of EmailSummary objects for unread messages in INBOX
    since the given datetime (UTC).

    If since_datetime is None, we simply query for unread in INBOX and rely on
    max_results to limit volume.
    """
    query_parts = ["label:INBOX", "is:unread"]
    if since_datetime is not None:
        # Gmail 'after' uses seconds since epoch UTC
        ts = int(since_datetime.replace(tzinfo=timezone.utc).timestamp())
        query_parts.append(f"after:{ts}")
    query = " ".join(query_parts)

    logger.info("Listing unread summaries with query=%r max_results=%d", query, max_results)

    results: List[EmailSummary] = []

    try:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
    except HttpError as e:
        logger.exception("Error listing messages from Gmail: %s", e)
        return results

    message_refs = response.get("messages", []) or []
    if not message_refs:
        return results

    for msg_ref in message_refs:
        msg_id = msg_ref.get("id")
        if not msg_id:
            continue

        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
        except HttpError as e:
            logger.exception("Error fetching message %s: %s", msg_id, e)
            continue

        thread_id = msg.get("threadId", msg_id)
        snippet = msg.get("snippet", "")

        payload = msg.get("payload", {}) or {}
        headers = payload.get("headers", []) or []

        h_from = _parse_header(headers, "From") or ""
        h_subject = _parse_header(headers, "Subject") or "(no subject)"
        h_date = _parse_header(headers, "Date") or ""

        sender_name, sender_email = _parse_from_header(h_from)
        received_at = _parse_date_header(h_date)

        summary = EmailSummary(
            id=msg_id,
            thread_id=thread_id,
            sender_name=sender_name,
            sender_email=sender_email,
            received_at=received_at,
            subject=h_subject,
            snippet=snippet,
        )
        results.append(summary)

    return results


# ---------------------------------------------------------------------------
# Fetching full bodies
# ---------------------------------------------------------------------------


def fetch_email_bodies(service, message_ids: List[str]) -> List[EmailBody]:
    """
    Fetch full bodies for the given message IDs and return EmailBody objects.
    """
    bodies: List[EmailBody] = []

    for msg_id in message_ids:
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except HttpError as e:
            logger.exception("Error fetching full message %s: %s", msg_id, e)
            continue

        thread_id = msg.get("threadId", msg_id)
        payload = msg.get("payload", {}) or {}

        body_text, body_html = _extract_bodies_from_payload(payload)

        email_body = EmailBody(
            id=msg_id,
            thread_id=thread_id,
            body_text=body_text,
            body_html=body_html,
        )
        bodies.append(email_body)

    return bodies
