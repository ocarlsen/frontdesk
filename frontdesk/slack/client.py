"""A deliberately small Slack Web API client: the read calls ingest needs, with retry on rate
limits and server errors. The token travels only in the Authorization header, never in a URL
(URLs end up in proxy and server logs). Errors carry the method and Slack's error code only,
never a response body, since bodies can echo message text into logs."""
from __future__ import annotations

import time

import requests

BASE = "https://slack.com/api"
RETRY_STATUSES = {429, 500, 502, 503, 504}
CONVERSATION_TYPES = "im,mpim,private_channel,public_channel"


class SlackError(RuntimeError):
    def __init__(self, method: str, error: str):
        self.method = method
        self.error = error
        super().__init__(f"Slack API {method}: {error}")


class SlackClient:
    def __init__(self, token: str, retries: int = 4, backoff: float = 1.0,
                 timeout: float = 30.0):
        self._token = token
        self.session = requests.Session()
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self._users: dict[str, dict] = {}

    def __repr__(self) -> str:  # keep the token out of tracebacks and debug prints
        return "SlackClient(token=***)"

    def _call(self, method: str, params: dict | None = None) -> dict:
        """One GET. Slack reports most failures as HTTP 200 with ok=false; those raise
        SlackError with Slack's own error code. 429 waits Retry-After; 5xx backs off."""
        url = f"{BASE}/{method}"
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(self.retries + 1):
            resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            if resp.status_code in RETRY_STATUSES and attempt < self.retries:
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else self.backoff * 2 ** attempt
                time.sleep(delay)
                continue
            if resp.status_code != 200:
                raise SlackError(method, f"http_{resp.status_code}")
            try:
                data = resp.json()
            except ValueError:
                raise SlackError(method, "invalid_json") from None
            if not data.get("ok"):
                raise SlackError(method, str(data.get("error", "unknown_error"))[:100])
            return data
        raise AssertionError("unreachable")

    def _paginate(self, method: str, params: dict, key: str) -> list[dict]:
        out: list[dict] = []
        cursor = ""
        while True:
            page = dict(params, cursor=cursor) if cursor else dict(params)
            data = self._call(method, page)
            out.extend(data.get(key, []))
            cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                return out

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> dict:
        """chat.postMessage as the owner (user token, chat:write). One attempt, never retried:
        a timeout may already have posted it."""
        body: dict = {"channel": channel, "text": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
        resp = self.session.post(f"{BASE}/chat.postMessage", json=body, timeout=self.timeout,
                                 headers={"Authorization": f"Bearer {self._token}"})
        if resp.status_code != 200:
            raise SlackError("chat.postMessage", f"http_{resp.status_code}")
        data = resp.json()
        if not data.get("ok"):
            raise SlackError("chat.postMessage", str(data.get("error", "unknown_error"))[:100])
        return data

    def auth_test(self) -> dict:
        data = self._call("auth.test")
        return {k: data.get(k, "") for k in ("user_id", "team_id", "url", "team", "user")}

    def list_conversations(self) -> list[dict]:
        """Conversations the owner is in. Group DMs are kept explicitly as well, in case Slack
        omits is_member on mpim objects."""
        convs = self._paginate("conversations.list",
                               {"types": CONVERSATION_TYPES, "exclude_archived": "true",
                                "limit": 200}, "channels")
        return [c for c in convs if c.get("is_member") or c.get("is_im") or c.get("is_mpim")]

    def history(self, channel: str, oldest_ts: str) -> list[dict]:
        """Top-level messages (thread roots, not their replies) since oldest_ts, newest first."""
        return self._paginate("conversations.history",
                              {"channel": channel, "oldest": oldest_ts, "limit": 200}, "messages")

    def replies(self, channel: str, thread_ts: str) -> list[dict]:
        """A thread's root and replies. Pages may repeat the root; normalize dedupes by ts."""
        return self._paginate("conversations.replies",
                              {"channel": channel, "ts": thread_ts, "limit": 200}, "messages")

    def user(self, user_id: str) -> dict:
        if user_id not in self._users:
            self._users[user_id] = self._call("users.info", {"user": user_id})["user"]
        return self._users[user_id]
