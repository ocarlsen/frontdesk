"""A deliberately small Gmail REST client: the three read calls ingest needs, with retry on
rate limits and server errors. Exceptions carry status, endpoint and Google's own error message
only, never a raw response body, since bodies can echo mail content into logs."""
from __future__ import annotations

import time

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class GmailError(RuntimeError):
    def __init__(self, status: int, endpoint: str, message: str = ""):
        self.status = status
        self.endpoint = endpoint
        super().__init__(f"Gmail API {status} on {endpoint}" + (f": {message}" if message else ""))


def _error_message(resp) -> str:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return ""
    msg = err.get("message", "") if isinstance(err, dict) else ""
    return str(msg)[:300]


class GmailClient:
    def __init__(self, creds: Credentials, retries: int = 4, backoff: float = 1.0,
                 timeout: float = 30.0):
        self.session = AuthorizedSession(creds)
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{BASE}/{endpoint}"
        for attempt in range(self.retries + 1):
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in RETRY_STATUSES and attempt < self.retries:
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else self.backoff * 2 ** attempt
                time.sleep(delay)
                continue
            raise GmailError(resp.status_code, endpoint, _error_message(resp))
        raise AssertionError("unreachable")

    def profile_email(self) -> str:
        return self._get("profile")["emailAddress"]

    def list_thread_ids(self, query: str, max_threads: int) -> list[str]:
        ids: list[str] = []
        page_token = None
        while len(ids) < max_threads:
            params = {"q": query, "maxResults": min(500, max_threads - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            data = self._get("threads", params)
            ids.extend(t["id"] for t in data.get("threads", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return ids[:max_threads]

    def get_thread(self, thread_id: str) -> dict:
        return self._get(f"threads/{thread_id}", {"format": "full"})

    def get_attachment(self, message_id: str, attachment_id: str) -> str:
        """Base64url data of one attachment (used for inline cid: images)."""
        return self._get(f"messages/{message_id}/attachments/{attachment_id}")["data"]
