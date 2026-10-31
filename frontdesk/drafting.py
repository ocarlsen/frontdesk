"""Gmail replies with links left exactly as written: drafts for the page's Save draft and for
other tools (`frontdesk draft`), and the message the page's Send flow hands to Gmail. Nothing in
this module sends; frontdesk.sending owns the one send call, behind its confirm and undo steps.

Why it exists: some draft paths rewrite every link to a google.com/url redirect. This builds the
raw MIME itself (text/plain plus a text/html alternative whose hrefs are the URLs byte for byte)
and posts it to Gmail's drafts endpoint, so what you wrote is what gets stored.

Recipients for a threaded reply come from the THREAD (Reply-To, else From, of its latest inbound
message), never from the body. In-Reply-To and References point at that message so Gmail and the
recipient's client thread it."""
from __future__ import annotations

import base64
import email
import email.policy
import html
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

from .gmail.client import GmailClient
from .gmail.normalize import clean_body, html_to_text

URL = re.compile(r"https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]]")
REDIRECT = re.compile(r"https?://(?:www\.)?google\.[a-z.]+/url\?", re.I)


class DraftError(Exception):
    pass


@dataclass
class Draft:
    draft_id: str
    message_id: str
    thread_id: str
    url: str


def text_to_html(text: str) -> str:
    """Escape the prose, link bare URLs. The href is the URL exactly as typed (the regex never
    matches a quote or angle bracket, so it needs no escaping inside a double-quoted attribute)."""
    out, last = [], 0
    for m in URL.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        out.append(f'<a href="{m.group(0)}">{html.escape(m.group(0))}</a>')
        last = m.end()
    out.append(html.escape(text[last:]))
    return ('<div dir="ltr" style="white-space:pre-wrap">' + "".join(out) + "</div>")


def build_mime(from_addr: str, to: list[str], subject: str, body: str, *, is_html: bool = False,
               cc: list[str] | None = None, in_reply_to: str = "",
               references: str = "") -> EmailMessage:
    if not to:
        raise DraftError("a draft needs at least one recipient")
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip()
    text = html_to_text(body).strip() + "\n" if is_html else body
    msg.set_content(text)
    msg.add_alternative(body if is_html else text_to_html(body), subtype="html")
    return msg


def _hdr(m: dict, name: str) -> str:
    for h in m.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def reply_context(thread: dict, me: str, reply_all: bool = False) -> dict:
    """Recipients and threading headers derived from the thread's latest INBOUND message."""
    inbound = [m for m in thread.get("messages", [])
               if not {"SENT", "DRAFT"} & set(m.get("labelIds") or [])
               and parseaddr(_hdr(m, "From"))[1].lower() != me.lower()]
    if not inbound:
        raise DraftError("no inbound message in this thread to reply to")
    last = max(inbound, key=lambda m: int(m.get("internalDate", 0)))
    reply_to = _hdr(last, "Reply-To") or _hdr(last, "From")
    to = [a for _, a in getaddresses([reply_to]) if a]
    cc: list[str] = []
    if reply_all:
        seen = {a.lower() for a in to} | {me.lower()}
        for field in ("To", "Cc"):
            for _, a in getaddresses([_hdr(last, field)]):
                if a and a.lower() not in seen:
                    cc.append(a)
                    seen.add(a.lower())
    subject = _hdr(last, "Subject") or _hdr(thread["messages"][0], "Subject")
    if not re.match(r"(?i)re:", subject):
        subject = "Re: " + subject
    msg_id = _hdr(last, "Message-ID") or _hdr(last, "Message-Id")
    if not msg_id:
        raise DraftError("the message being replied to has no Message-ID header")
    return {"to": to, "cc": cc, "subject": subject, "in_reply_to": msg_id,
            "references": _hdr(last, "References"), "thread_id": thread["id"]}


def thread_draft(thread: dict) -> dict | None:
    """The newest unsent draft in a Gmail thread (threads.get returns drafts as messages labelled
    DRAFT), as {message_id, body}; None when the thread has none. Gmail is the source of truth:
    FrontDesk keeps no copy, so an edit made in Gmail is what the reply box shows next time."""
    drafts = [m for m in thread.get("messages", []) if "DRAFT" in (m.get("labelIds") or [])]
    if not drafts:
        return None
    m = max(drafts, key=lambda m: int(m.get("internalDate", 0)))
    return {"message_id": m["id"], "body": clean_body(m.get("payload", {}))}


def draft_url(account: str, message_id: str) -> str:
    return f"https://mail.google.com/mail/?authuser={account}#drafts?compose={message_id}"


def create(gmail: GmailClient, msg: EmailMessage, thread_id: str | None = None) -> Draft:
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body: dict = {"message": {"raw": raw}}
    if thread_id:
        body["message"]["threadId"] = thread_id
    d = gmail.create_draft(body)
    me = gmail.profile_email()
    mid = d["message"]["id"]
    return Draft(d["id"], mid, d["message"].get("threadId", ""), draft_url(me, mid))


def build_reply(gmail: GmailClient, thread_id: str, body: str, *, is_html: bool = False,
                reply_all: bool = False, thread: dict | None = None) -> tuple[EmailMessage, dict]:
    """The reply message and the context it was derived from (recipients, subject, thread)."""
    me = gmail.profile_email()
    ctx = reply_context(thread or gmail.get_thread(thread_id), me, reply_all)
    msg = build_mime(me, ctx["to"], ctx["subject"], body, is_html=is_html, cc=ctx["cc"],
                     in_reply_to=ctx["in_reply_to"], references=ctx["references"])
    return msg, ctx


def draft_reply(gmail: GmailClient, thread_id: str, body: str, *, is_html: bool = False,
                reply_all: bool = False) -> Draft:
    msg, ctx = build_reply(gmail, thread_id, body, is_html=is_html, reply_all=reply_all)
    return create(gmail, msg, ctx["thread_id"])


def save_reply(gmail: GmailClient, thread_id: str, body: str, reply_all: bool = False) -> Draft:
    """Like draft_reply, but when the thread already has a draft (saved earlier, or started in
    Gmail) it replaces that draft's text instead of adding a second draft."""
    thread = gmail.get_thread(thread_id)
    existing = thread_draft(thread)
    msg, ctx = build_reply(gmail, thread_id, body, thread=thread, reply_all=reply_all)
    if existing is None:
        return create(gmail, msg, ctx["thread_id"])
    draft_id = next((d["id"] for d in gmail.list_drafts()
                     if (d.get("message") or {}).get("id") == existing["message_id"]), None)
    if draft_id is None:   # sent or discarded since the thread was read
        return create(gmail, msg, ctx["thread_id"])
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    d = gmail.update_draft(draft_id, {"id": draft_id,
                                      "message": {"raw": raw, "threadId": ctx["thread_id"]}})
    mid = d["message"]["id"]
    return Draft(d["id"], mid, d["message"].get("threadId", ""),
                 draft_url(gmail.profile_email(), mid))


def draft_new(gmail: GmailClient, to: list[str], subject: str, body: str, *,
              is_html: bool = False, cc: list[str] | None = None) -> Draft:
    return create(gmail, build_mime(gmail.profile_email(), to, subject, body, is_html=is_html,
                                    cc=cc))


def audit_raw(raw: bytes) -> dict:
    """Every href and bare URL in the decoded text parts, and any google.com/url redirect among
    them. Fails closed: a message with no non-blank text part does not pass."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    links: list[str] = []
    scanned = False
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.is_multipart() or ctype not in ("text/plain", "text/html"):
            continue
        content = part.get_content()
        if content.strip():
            scanned = True
        if ctype == "text/html":
            links += re.findall(r'href\s*=\s*"([^"]*)"', content, re.I)
            content = html_to_text(content)   # visible text, entities decoded
        links += URL.findall(content)
    redirects = sorted({u for u in links if REDIRECT.match(u)})
    return {"links": sorted(set(links)), "redirects": redirects,
            "pass": scanned and not redirects,
            "reason": "" if scanned else "no text to scan"}


def audit_draft(gmail: GmailClient, draft_id: str) -> dict:
    d = gmail.get_draft(draft_id, fmt="raw")
    raw = d["message"]["raw"]
    return audit_raw(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
