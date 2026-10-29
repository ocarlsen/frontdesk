"""Gmail thread JSON (format=full) -> Item. Pure and offline so it is fully testable on
synthetic fixtures. The model downstream sees only what this emits, so it trims what costs
tokens and adds nothing: quoted history, HTML markup, and runaway bodies."""
from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from urllib.parse import quote

from ..items import Item, Message

BODY_CAP = 8000
HTML_CAP = 400_000
TRUNCATED = "\n[truncated]"

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "hr", "section", "article", "header", "footer", "td", "th",
}
_ON_WROTE = re.compile(r"^\s*On\b.*\bwrote:\s*$")
_OUTLOOK_FROM = re.compile(r"^\s*\*?From:\*?\s")
_OUTLOOK_SENT = re.compile(r"^\s*\*?(Sent|Date):\*?\s")


def _headers(payload: dict) -> dict[str, str]:
    """First value per header, case-insensitive keys."""
    out: dict[str, str] = {}
    for h in payload.get("headers", []):
        out.setdefault(h.get("name", "").lower(), h.get("value", ""))
    return out


def _charset(part: dict) -> str:
    ctype = _headers(part).get("content-type", "")
    m = re.search(r'charset\s*=\s*"?([^";\s]+)', ctype, re.I)
    return m.group(1) if m else "utf-8"


def _decode(part: dict) -> str:
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    # Senders mislabel charsets often (Outlook declares iso-8859-1 over UTF-8 bytes). Valid
    # UTF-8 almost never arises by accident from 8-bit text, so a strict UTF-8 decode wins
    # first; otherwise trust the label, reading latin-1/ascii as cp1252 as mail clients do.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    cs = _charset(part).lower()
    if cs in ("iso-8859-1", "latin-1", "latin1", "us-ascii", "ascii"):
        cs = "cp1252"
    try:
        return raw.decode(cs, errors="replace")
    except LookupError:
        return raw.decode("cp1252", errors="replace")


def _find_part(part: dict, mime: str) -> dict | None:
    """Depth-first search for the first non-attachment part of the given type."""
    if (part.get("mimeType", "").lower() == mime and not part.get("filename")
            and part.get("body", {}).get("data")):
        return part
    for child in part.get("parts", []) or []:
        found = _find_part(child, mime)
        if found:
            return found
    return None


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(re.sub(r"[ \t\r\n\f\v]+", " ", data))


def html_to_text(html: str) -> str:
    p = _HTMLText()
    p.feed(html)
    p.close()
    lines = [ln.strip() for ln in "".join(p.out).replace("\xa0", " ").split("\n")]
    return "\n".join(lines)


def strip_quoted(text: str) -> str:
    """Cut at the first reply/forward marker. If that leaves nothing (a message that opens with
    a quote, e.g. inline-reply style), keep the original rather than emit an empty body."""
    lines = text.split("\n")
    cut = None
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if (line.lstrip().startswith(">") or line.strip() == "-----Original Message-----"
                or _ON_WROTE.match(line)):
            cut = i
        elif line.lstrip().startswith("On ") and re.search(r"\bwrote:\s*$", nxt):
            cut = i  # Gmail wraps long "On <date>, <name> <addr>\nwrote:" headers
        elif _OUTLOOK_FROM.match(line) and any(
                _OUTLOOK_SENT.match(ln) for ln in lines[i + 1:i + 4]):
            cut = i
            if i > 0 and re.fullmatch(r"\s*_{8,}\s*", lines[i - 1]):
                cut = i - 1
        if cut is not None:
            break
    if cut is None:
        return text
    head = "\n".join(lines[:cut])
    return head if head.strip() else text


# Where quoted history starts in HTML mail: Gmail, Apple Mail/Thunderbird, Outlook.
_HTML_QUOTE = re.compile(
    r'<div[^>]+class="?gmail_quote|<blockquote|<div[^>]+id="?(?:divRplyFwdMsg|appendonsend)'
    r'|<hr[^>]+id="?stopSpelling', re.I)


def _inline_images(part: dict, out: dict[str, str] | None = None) -> dict[str, str]:
    """Content-ID -> data: URI for inline images whose bytes are present (sync fetches them)."""
    out = {} if out is None else out
    cid = _headers(part).get("content-id", "").strip().strip("<>")
    data = part.get("body", {}).get("data", "")
    mime = part.get("mimeType", "").lower()
    if cid and data and mime.startswith("image/"):
        std = data.replace("-", "+").replace("_", "/") + "=" * (-len(data) % 4)
        out[cid] = f"data:{mime};base64,{std}"
    for child in part.get("parts", []) or []:
        _inline_images(child, out)
    return out


_CID = re.compile(r"cid:([^\"'\s)>]+)", re.I)


def clean_html(payload: dict) -> str:
    """The HTML part for display, quoted history trimmed like Gmail's collapsed '...'. Returns
    '' (the UI then shows the text body) when there is no HTML part or it is oversized."""
    part = _find_part(payload, "text/html")
    if not part:
        return ""
    html = _decode(part)
    m = _HTML_QUOTE.search(html)
    if m and html_to_text(html[:m.start()]).strip():
        html = html[:m.start()]
    if len(html) > HTML_CAP:
        return ""
    images = _inline_images(payload)
    return _CID.sub(lambda m: images.get(m.group(1), m.group(0)), html) if images else html


def clean_body(payload: dict) -> str:
    part = _find_part(payload, "text/plain")
    if part:
        text = _decode(part)
    else:
        part = _find_part(payload, "text/html")
        text = html_to_text(_decode(part)) if part else ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = strip_quoted(text)
    text = "\n".join(ln.rstrip() for ln in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > BODY_CAP:
        text = text[:BODY_CAP] + TRUNCATED
    return text


def _iso(ms: str | int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def thread_to_item(thread: dict, account_email: str) -> Item | None:
    """Returns None when every message in the thread is a draft (nothing anyone sent)."""
    msgs = [m for m in thread.get("messages", []) if "DRAFT" not in (m.get("labelIds") or [])]
    if not msgs:
        return None
    msgs.sort(key=lambda m: int(m.get("internalDate", 0)))
    me = account_email.lower()

    participants: list[str] = []
    labels: list[str] = []
    messages: list[Message] = []
    for m in msgs:
        payload = m.get("payload", {})
        h = _headers(payload)
        for field in ("from", "to", "cc"):
            for _, addr in getaddresses([h.get(field, "")]):
                addr = addr.strip().lower()
                if addr and "@" in addr and addr not in participants:
                    participants.append(addr)
        for lab in m.get("labelIds") or []:
            if lab not in labels:
                labels.append(lab)
        sender = h.get("from", "")
        messages.append(Message(
            sender=sender,
            sent_at=_iso(m.get("internalDate", 0)),
            body=clean_body(payload),
            # From alone is forgeable; Gmail applies SENT only to mail this account sent.
            is_mine=(parseaddr(sender)[1].lower() == me
                     and "SENT" in (m.get("labelIds") or [])),
            html=clean_html(payload),
        ))

    thread_id = thread["id"]
    return Item(
        id=f"gmail:{thread_id}",
        source="gmail",
        account=account_email,
        subject=_headers(msgs[0].get("payload", {})).get("subject", ""),
        participants=participants,
        messages=messages,
        updated_at=messages[-1].sent_at,
        labels=labels,
        url=(f"https://mail.google.com/mail/?authuser={quote(account_email, safe='@')}"
             f"#all/{thread_id}"),
    )
