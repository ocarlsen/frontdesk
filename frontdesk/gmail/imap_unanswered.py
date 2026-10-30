"""`frontdesk unanswered`: Gmail threads still waiting on the owner's reply, read over IMAP.

Optional and separate from the OAuth sync: it logs in to IMAP with a Gmail app password
(IMAP_APP_PASSWORD, or the login Keychain item named by imap_keychain_service with account
imap_account), reads message HEADERS only, and prints JSON. No model call, nothing stored.

Read-only by construction: mailboxes are opened with EXAMINE (imaplib's select(readonly=True)),
every fetch is BODY.PEEK of a few header fields plus FLAGS / INTERNALDATE / X-GM-THRID, and no
STORE, COPY, MOVE, EXPUNGE or CLOSE is ever sent, so nothing is marked read, moved or labelled.

A thread is unanswered when its newest message in the window (the candidate messages plus the
owner's own messages in the same thread, drafts excluded) is not from the owner and looks like it
came from a person. A fixed number of round trips: two searches and chunked fetches, never one
search per thread, so a large mailbox stays inside the 30 s cap.
Any failure raises UnansweredError naming the step; there is no partial or empty result on error.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import os
import re
import signal
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr

PORT = 993
TIMEOUT_S = 60   # all mail, two searches; the brief runs unattended, so allow headroom
ALL_MAIL_FALLBACK = "[Gmail]/All Mail"
# Threads in the inbox, plus threads with an unread message anywhere in All Mail (archived
# unread still waits on the owner; archived and read was dealt with). Gmail's {a b} is OR.
CANDIDATE_QUERY = ("{{in:inbox is:unread}} newer_than:{days}d -in:chats -in:drafts "
                   "-category:promotions -category:social -category:updates -category:forums")
HEADER_FIELDS = "FROM SUBJECT LIST-UNSUBSCRIBE LIST-ID PRECEDENCE AUTO-SUBMITTED"
FETCH_ITEMS = f"(UID X-GM-THRID INTERNALDATE FLAGS BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])"
# Compared against the from-address local part with '-', '_' and '.' removed.
AUTOMATED_LOCAL_PARTS = ("noreply", "donotreply", "notification", "mailerdaemon", "postmaster")
# The owner's messages: from:me rather than in:sent, because the rule is about who SENT the
# newest message. from:me matches the From address (send-as aliases included) wherever the
# message lives, including replies sent from another client or server that only reached Gmail
# by Bcc or import and so never got the Sent label; in:sent is a label and misses those.
OWNER_QUERY = "from:me newer_than:{days}d -in:chats -in:drafts"
OWNER_FETCH_ITEMS = "(UID X-GM-THRID INTERNALDATE FLAGS)"
FETCH_CHUNK = 300          # UIDs per FETCH: bounded round trips, bounded command length
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


class _StepError(Exception):
    """Base for this module's (and imap_buckets') failures: one line, '<step>: <detail>', for
    stderr. Shared so `_step`/`_ignore_list`-style helpers work for either command's own
    exception subclass."""

    def __init__(self, step: str, detail: str):
        self.step = step
        super().__init__(f"{step}: {_one_line(detail)}")


class UnansweredError(_StepError):
    pass


def _one_line(detail) -> str:
    s = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else str(detail)
    m = re.fullmatch(r"b'(.*)'", s.strip())     # imaplib errors often wrap server bytes
    return " ".join((m.group(1) if m else s).split()) or "failed"


class _Timeout(Exception):
    pass


@contextmanager
def _step(name: str, error_cls: type[_StepError] = UnansweredError):
    """Any exception inside becomes error_cls naming this step (imap_buckets passes its own
    BucketsError so the two commands' failures stay separately typed with identical shape)."""
    try:
        yield
    except error_cls:
        raise
    except (_Timeout, TimeoutError) as e:
        raise error_cls(name, f"timed out ({e})" if str(e) else "timed out") from e
    except Exception as e:  # noqa: BLE001 - the contract is one named line, never a traceback
        raise error_cls(name, str(e) or type(e).__name__) from e


@contextmanager
def _overall_timeout(seconds: float):
    """Wall-clock cap for the whole run (SIGALRM, main thread only; elsewhere the per-socket
    timeout still applies)."""
    import threading
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return

    def fire(*_):
        raise _Timeout(f"over {seconds:g}s overall")

    old = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


# ---------------------------------------------------------------- configuration


@dataclass(frozen=True)
class ImapConfig:
    host: str
    account: str
    password: str
    ignore: tuple[str, ...] = ()   # lowercase addresses ("a@b.com") or domains ("@b.com", "b.com")


def ignored(addr: str, ignore) -> bool:
    """An exact address, or the sender's domain (a leading '@' is optional; subdomains match)."""
    addr = addr.lower()
    domain = addr.rpartition("@")[2]
    for entry in ignore:
        if "@" in entry.lstrip("@"):
            if addr == entry:
                return True
        else:
            d = entry.lstrip("@")
            if domain == d or domain.endswith("." + d):
                return True
    return False


def _validate_address_list(raw, key: str,
                           error_cls: type[_StepError] = UnansweredError) -> tuple[str, ...]:
    """Shared by unanswered_ignore_senders here and newsletter_senders in imap_buckets: a list
    of lowercase addresses or domains, same `ignored()` matching rules either way."""
    if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
        raise error_cls("config", f"{key} must be a list of addresses or domains, e.g. "
                                  "[\"reports@example.com\", \"@example.org\"]")
    return tuple(x.strip().lower() for x in raw)


def _ignore_list(settings: dict) -> tuple[str, ...]:
    return _validate_address_list(settings.get("unanswered_ignore_senders", []),
                                  "unanswered_ignore_senders")


def resolve_config(settings: dict, environ=None, keychain=None) -> ImapConfig:
    """IMAP_ACCOUNT / IMAP_APP_PASSWORD win over settings, as provider API keys do. Missing
    configuration raises naming the setting."""
    env = os.environ if environ is None else environ
    ignore = _ignore_list(settings)
    host = (settings.get("imap_host") or "").strip()
    if not host:
        raise UnansweredError("config", "imap_host is empty")
    account = env.get("IMAP_ACCOUNT", "").strip() or (settings.get("imap_account") or "").strip()
    if not account:
        raise UnansweredError("config", "imap_account is not set (your Gmail address, in "
                                        "settings.json or IMAP_ACCOUNT)")
    password = env.get("IMAP_APP_PASSWORD", "").strip()
    if not password:
        service = (settings.get("imap_keychain_service") or "").strip()
        if not service:
            raise UnansweredError("config", "imap_keychain_service is not set (the Keychain "
                                            "item holding a Gmail app password, or set "
                                            "IMAP_APP_PASSWORD)")
        if keychain is None:
            from ..providers import keychain_secret as keychain
        with _step("keychain"):
            password = keychain(service, account=account)
    return ImapConfig(host=host, account=account, password=password, ignore=ignore)


# ---------------------------------------------------------------- parsing


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _all_mail_name(list_lines) -> str:
    """The mailbox flagged \\All (its name is localized), else [Gmail]/All Mail."""
    for line in list_lines or []:
        if isinstance(line, tuple):      # a literal-encoded name; not worth handling
            continue
        s = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line or "")
        m = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', s.strip())
        if m and "\\all" in m.group("flags").lower().split():
            name = m.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            return name
    return ALL_MAIL_FALLBACK


def _uids(data) -> list[str]:
    out: list[str] = []
    for chunk in data or []:
        if chunk:
            out += (chunk.decode() if isinstance(chunk, bytes) else str(chunk)).split()
    for u in out:
        if not u.isdigit():
            raise ValueError(f"unexpected SEARCH result {u!r}")
    return out


@dataclass
class _Msg:
    uid: int
    thrid: int
    at: datetime
    flags: list[str]
    headers: email.message.Message


def _parse_internaldate(s: str) -> datetime:
    m = re.fullmatch(r"\s*(\d{1,2})-(\w{3})-(\d{4}) (\d\d):(\d\d):(\d\d) ([+-])(\d\d)(\d\d)\s*", s)
    if not m or m.group(2) not in _MONTHS:
        raise ValueError(f"bad INTERNALDATE {s!r}")
    d, mon, y, hh, mm, ss, sign, oh, om = m.groups()
    off = timedelta(hours=int(oh), minutes=int(om)) * (1 if sign == "+" else -1)
    return datetime(int(y), _MONTHS[mon], int(d), int(hh), int(mm), int(ss),
                    tzinfo=timezone(off))


def _parse_fetch(data) -> list[_Msg]:
    """imaplib FETCH data: (b'N (UID .. X-GM-THRID .. INTERNALDATE ".." FLAGS (..) BODY[..]
    {n}', header bytes) tuples, each followed by b')' (which may carry items placed after the
    literal)."""
    recs: list[list] = []
    for part in data or []:
        if isinstance(part, tuple):
            recs.append([part[0].decode("utf-8", "replace"), part[1]])
        elif isinstance(part, bytes) and re.match(rb"\d+ \(", part):   # no literal at all
            recs.append([part.decode("utf-8", "replace"), b""])
        elif isinstance(part, bytes) and recs:
            recs[-1][0] += " " + part.decode("utf-8", "replace")
        elif part is None or (isinstance(part, bytes) and not part.strip()):
            continue
        else:
            raise ValueError(f"unexpected FETCH data {part!r:.80}")
    out = []
    for meta, raw in recs:
        uid = re.search(r"\bUID (\d+)", meta)
        thrid = re.search(r"\bX-GM-THRID (\d+)", meta)
        idate = re.search(r'\bINTERNALDATE "([^"]+)"', meta)
        flags = re.search(r"\bFLAGS \(([^)]*)\)", meta)
        if not (uid and thrid and idate):
            raise ValueError(f"FETCH item missing UID/X-GM-THRID/INTERNALDATE: {meta[:80]!r}")
        out.append(_Msg(uid=int(uid.group(1)), thrid=int(thrid.group(1)),
                        at=_parse_internaldate(idate.group(1)),
                        flags=(flags.group(1).split() if flags else []),
                        headers=email.message_from_bytes(raw or b"", policy=email.policy.compat32)))
    return out


def decode_rfc2047(value) -> str:
    if value is None:
        return ""
    try:
        return " ".join(str(make_header(decode_header(str(value)))).split())
    except Exception:  # noqa: BLE001 - a malformed encoded word shows as written
        return " ".join(str(value).split())


def is_automated(headers: email.message.Message, from_addr: str) -> bool:
    if headers.get("List-Unsubscribe") is not None or headers.get("List-Id") is not None:
        return True
    if (headers.get("Precedence") or "").strip().lower() in ("bulk", "list", "junk"):
        return True
    auto = headers.get("Auto-Submitted")
    if auto is not None and auto.strip().lower() != "no":
        return True
    local = re.sub(r"[-_.]", "", from_addr.split("@", 1)[0].lower())
    return any(tok in local for tok in AUTOMATED_LOCAL_PARTS)


def gmail_url(account: str, thrid: int) -> str:
    return f"https://mail.google.com/mail/u/?authuser={account}#all/{thrid:x}"


# ---------------------------------------------------------------- the run


def _ok(typ, dat, what: str):
    if typ != "OK":
        raise RuntimeError(f"{what} returned {typ} {_one_line(dat[-1] if dat else '')}")
    return dat


def find_unanswered(cfg: ImapConfig, days: int = 14, now: datetime | None = None,
                    connect: Callable | None = None, timeout: float = TIMEOUT_S) -> list[dict]:
    """All unanswered threads, oldest first (uncapped). `connect(host, port, timeout)` returns an
    imaplib.IMAP4-like client; tests pass a stub."""
    if days < 1:
        raise UnansweredError("args", "--days must be at least 1")
    connect = connect or (lambda h, p, t: imaplib.IMAP4_SSL(h, p, timeout=t))
    owner = cfg.account.strip().lower()
    try:
        with _overall_timeout(timeout):
            with _step("imap connect"):
                client = connect(cfg.host, PORT, timeout)
            try:
                return _run(client, cfg, owner, days, now or datetime.now(UTC))
            finally:
                with suppress(Exception):   # the result (or the real error) stands
                    client.logout()
    except _Timeout as e:      # fired between steps
        raise UnansweredError("timeout", str(e)) from e


def _run(client, cfg: ImapConfig, owner: str, days: int, now: datetime) -> list[dict]:
    with _step("imap login"):
        client.login(cfg.account, cfg.password)
    with _step("imap list"):
        all_mail = _all_mail_name(_ok(*client.list(), "LIST"))
    with _step("imap examine"):
        _ok(*client.select(_quote(all_mail), readonly=True), f"EXAMINE {all_mail}")
    with _step("imap search"):
        cand = _search(client, CANDIDATE_QUERY.format(days=int(days)))
    if not cand:
        return []
    with _step("imap fetch"):
        cand_dat = _fetch(client, cand, FETCH_ITEMS)
    with _step("imap search"):
        mine = _search(client, OWNER_QUERY.format(days=int(days)))
    with _step("imap fetch"):
        mine_dat = _fetch(client, mine, OWNER_FETCH_ITEMS) if mine else []
    with _step("parse"):
        return _classify(_parse_fetch(cand_dat), _parse_fetch(mine_dat), cfg.account, owner,
                         now, cfg.ignore)


def _search(client, query: str) -> list[str]:
    return _uids(_ok(*client.uid("SEARCH", "X-GM-RAW", _quote(query)), "SEARCH"))


def _fetch(client, uids: list[str], items: str) -> list:
    out: list = []
    for i in range(0, len(uids), FETCH_CHUNK):
        out += _ok(*client.uid("FETCH", ",".join(uids[i:i + FETCH_CHUNK]), items), "FETCH")
    return out


def _is_draft(m: _Msg) -> bool:
    return "\\draft" in (f.lower() for f in m.flags)


def _classify(cand: list[_Msg], mine: list[_Msg], account: str, owner: str,
              now: datetime, ignore: tuple[str, ...] = ()) -> list[dict]:
    """Threads come from the candidates only; the owner's messages only decide whether the owner
    spoke last. n_messages counts the distinct messages seen in the window for that thread
    (candidates plus the owner's), not the thread's whole history."""
    threads: dict[int, dict[int, _Msg]] = {}
    for m in cand:
        if not _is_draft(m):
            threads.setdefault(m.thrid, {})[m.uid] = m
    owner_uids = {m.uid for m in mine}
    for m in mine:
        if m.thrid in threads and not _is_draft(m):
            threads[m.thrid].setdefault(m.uid, m)
    out = []
    for thrid, by_uid in threads.items():
        ms = list(by_uid.values())
        last = max(ms, key=lambda m: (m.at, m.uid))
        if last.uid in owner_uids:
            continue
        name, addr = parseaddr(decode_rfc2047(last.headers.get("From")))
        addr = addr.strip().lower()
        if not addr or addr == owner or is_automated(last.headers, addr) or ignored(addr, ignore):
            continue
        out.append({
            "thread_id": str(thrid),
            "gmail_url": gmail_url(account, thrid),
            "from_name": name.strip(),
            "from_addr": addr,
            "subject": decode_rfc2047(last.headers.get("Subject")),
            "last_at": last.at.isoformat(),
            "age_days": max(0, (now - last.at) // timedelta(days=1)),
            "n_messages": len(ms),
        })
    out.sort(key=lambda it: (datetime.fromisoformat(it["last_at"]), it["thread_id"]))
    return out


def report(items: list[dict], limit: int) -> dict:
    """The JSON contract: total is the uncapped count, items are the oldest `limit`."""
    if limit < 0:
        raise UnansweredError("args", "--limit must be 0 or more")
    return {"total": len(items), "items": items[:limit]}
