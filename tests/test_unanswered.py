"""`frontdesk unanswered`, fully offline: imaplib is replaced by a stub that subclasses
imaplib.IMAP4 and answers at _simple_command, so imaplib's own select/uid/login code runs and the
call log holds the real IMAP command names. No network, no Keychain."""
from __future__ import annotations

import imaplib
import json
import re
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest

from frontdesk import __main__ as cli
from frontdesk import config, providers
from frontdesk.gmail import imap_unanswered as iu

OWNER = "owner@example.com"
PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 29, 17, 0, tzinfo=UTC)
FORBIDDEN = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "CLOSE"}


def msg(uid, thrid, when, frm, subject="Hello", cand=True, headers=(), flags="\\Seen"):
    """cand: whether the candidate X-GM-RAW search returns it. The owner's messages are found by
    the stub's from:me search whatever `cand` says."""
    return {"uid": uid, "thrid": thrid, "when": when, "from": frm, "subject": subject,
            "cand": cand, "headers": list(headers), "flags": flags}


def at(days_ago: float, tz=PDT) -> datetime:
    return (NOW - timedelta(days=days_ago)).astimezone(tz)


def idate(d: datetime) -> str:
    off = d.utcoffset() // timedelta(minutes=1)
    sign = "+" if off >= 0 else "-"
    return (f"{d.day:02d}-{d.strftime('%b')}-{d.year} {d:%H:%M:%S} "
            f"{sign}{abs(off) // 60:02d}{abs(off) % 60:02d}")


class StubImap(imaplib.IMAP4):
    def __init__(self, msgs, *, login_reply=None, all_mail="[Gmail]/All Mail", sleep_on=None,
                 bad_fetch=False):
        # Deliberately no super().__init__: it would open a socket.
        self.debug = 0
        self.state = "NONAUTH"
        self.literal = None
        self.tagged_commands = {}
        self.untagged_responses = {}
        self.continuation_response = ""
        self.is_readonly = False
        self.tagnum = 0
        self._tls_established = False
        self._mode_ascii()
        self.msgs, self.login_reply, self.all_mail = msgs, login_reply, all_mail
        self.sleep_on, self.bad_fetch = sleep_on, bad_fetch
        self.calls: list[tuple] = []

    def shutdown(self):
        pass

    def _simple_command(self, name, *args):
        self.calls.append((name, *args))
        if self.sleep_on and (name, *args[:1]) == self.sleep_on:
            time.sleep(5)
        if name == "LOGIN":
            return self.login_reply or ("OK", [b"LOGIN completed"])
        if name == "LIST":
            self.untagged_responses["LIST"] = [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren \\All) "/" "' + self.all_mail.encode() + b'"']
            return "OK", [b"LIST completed"]
        if name in ("EXAMINE", "SELECT"):
            self.untagged_responses["EXISTS"] = [str(len(self.msgs)).encode()]
            return "OK", [b"[READ-ONLY] done" if name == "EXAMINE" else b"[READ-WRITE] done"]
        if name == "UID" and args[0] == "SEARCH":
            if args[1] != "X-GM-RAW":
                return "BAD", [b"stub only answers X-GM-RAW searches"]
            if args[2].startswith('"from:me'):
                hits = [m for m in self.msgs
                        if OWNER in m["from"].lower().replace(" ", "")]
            else:
                hits = [m for m in self.msgs if m["cand"]]
            self.untagged_responses["SEARCH"] = [" ".join(str(m["uid"]) for m in hits).encode()]
            return "OK", [b"SEARCH completed"]
        if name == "UID" and args[0] == "FETCH":
            uids = {int(u) for u in args[1].split(",")}
            out: list = []
            for m in self.msgs:
                if m["uid"] not in uids:
                    continue
                if "BODY" not in args[2]:
                    out.append(f'{m["uid"]} (UID {m["uid"]} X-GM-THRID {m["thrid"]} INTERNALDATE '
                               f'"{idate(m["when"])}" FLAGS ({m["flags"]}))'.encode())
                    continue
                hdr = f"From: {m['from']}\r\nSubject: {m['subject']}\r\n"
                hdr += "".join(f"{k}: {v}\r\n" for k, v in m["headers"]) + "\r\n"
                raw = hdr.encode()
                pre = (f'{m["uid"]} (UID {m["uid"]} X-GM-THRID {m["thrid"]} INTERNALDATE '
                       f'"{idate(m["when"])}" FLAGS ({m["flags"]}) BODY[HEADER.FIELDS '
                       f'({iu.HEADER_FIELDS})] {{{len(raw)}}}')
                out += [(pre.encode(), raw), b")"]
            if self.bad_fetch:
                out = [b"garbage"]
            self.untagged_responses["FETCH"] = out
            return "OK", [b"FETCH completed"]
        if name == "LOGOUT":
            return "BYE", [b"bye"]
        return "OK", [b"done"]


def cfg():
    return iu.ImapConfig(host="imap.example.com", account=OWNER, password="app-pw")


def run(msgs, **kw):
    stub = StubImap(msgs, **{k: v for k, v in kw.items() if k != "days"})
    items = iu.find_unanswered(cfg(), days=kw.get("days", 14), now=NOW,
                               connect=lambda h, p, t: stub)
    return items, stub


def ids(items):
    return [it["thread_id"] for it in items]


# ------------------------------------------------------------------ the unanswered rule


def test_last_sender_decides_and_owner_reply_in_all_mail_counts():
    items, _ = run([
        msg(1, 101, at(3), "Alice <alice@example.org>"),                       # unanswered
        msg(2, 102, at(4), "Bob <bob@example.org>"),
        msg(3, 102, at(2), f"Me <{OWNER}>", cand=False),                      # sent reply
        msg(4, 103, at(6), f"Me <{OWNER}>", cand=False),
        msg(5, 103, at(1), "Carol <carol@example.org>"),                       # replied to me
        msg(6, 104, at(5), f"Me <{OWNER}>"),                                   # mine is last
    ])
    assert ids(items) == ["101", "103"]
    assert [it["n_messages"] for it in items] == [1, 2]


def test_owner_match_is_case_insensitive_and_drafts_are_not_replies():
    items, _ = run([
        msg(1, 201, at(3), "Alice <alice@example.org>"),
        msg(2, 201, at(2), "Me <Owner@Example.COM>", cand=False),             # answered
        msg(3, 202, at(3), "Dan <dan@example.org>"),
        msg(4, 202, at(1), f"Me <{OWNER}>", cand=False, flags="\\Seen \\Draft"),  # a draft
    ])
    assert ids(items) == ["202"]
    assert items[0]["n_messages"] == 1 and items[0]["from_addr"] == "dan@example.org"


@pytest.mark.parametrize("headers", [
    [("List-Unsubscribe", "<mailto:u@example.org>")],
    [("List-Id", "news <news.example.org>")],
    [("Precedence", "bulk")], [("Precedence", "list")], [("Precedence", "Junk")],
    [("Auto-Submitted", "auto-generated")], [("Auto-Submitted", "auto-replied")],
])
def test_each_automated_header_skips(headers):
    items, _ = run([msg(1, 301, at(2), "Svc <svc@example.org>", headers=headers),
                    msg(2, 302, at(2), "Eve <eve@example.org>")])
    assert ids(items) == ["302"]


@pytest.mark.parametrize("local", ["noreply", "no-reply", "No_Reply", "donotreply",
                                   "do-not-reply", "notifications", "mailer-daemon",
                                   "postmaster"])
def test_each_automated_local_part_skips(local):
    items, _ = run([msg(1, 401, at(2), f"X <{local}@example.org>"),
                    msg(2, 402, at(2), "Eve <eve@example.org>")])
    assert ids(items) == ["402"]


def test_auto_submitted_no_is_a_person():
    items, _ = run([msg(1, 501, at(2), "Eve <eve@example.org>",
                        headers=[("Auto-Submitted", "no")])])
    assert ids(items) == ["501"]


def test_rfc2047_subject_and_name_are_decoded():
    items, _ = run([msg(1, 601, at(2), "=?UTF-8?Q?Ren=C3=A9e_M?= <renee@example.org>",
                        subject="=?UTF-8?B?Q2Fmw6kgbWHDsWFuYT8=?=")])
    assert items[0]["subject"] == "Café mañana?"
    assert items[0]["from_name"] == "Renée M"


def test_gmail_url_uses_lowercase_hex_thread_id_and_decimal_thread_id():
    thrid = 1278455344230334865
    items, _ = run([msg(1, thrid, at(2), "Eve <eve@example.org>")])
    assert items[0]["thread_id"] == "1278455344230334865"
    assert items[0]["gmail_url"] == (
        f"https://mail.google.com/mail/u/?authuser={OWNER}#all/11bdfc5cae0c8191")


def test_oldest_first_cap_and_total():
    msgs = [msg(i, 700 + i, at(d), f"P{i} <p{i}@example.org>")
            for i, d in enumerate([2, 9, 0.5, 5, 7], 1)]
    items, _ = run(msgs)
    assert ids(items) == ["702", "705", "704", "701", "703"]
    rep = iu.report(items, 2)
    assert rep["total"] == 5 and ids(rep["items"]) == ["702", "705"]


def test_newest_is_by_time_not_uid_and_age_floors():
    items, _ = run([msg(9, 801, at(1), f"Me <{OWNER}>", cand=False),
                    msg(3, 801, at(2.99), "Eve <eve@example.org>")])
    assert ids(items) == []                       # the owner's later message wins
    items, _ = run([msg(1, 802, at(2.99), "Eve <eve@example.org>")])
    assert items[0]["age_days"] == 2


def test_localized_all_mail_from_the_all_flag():
    _, stub = run([msg(1, 901, at(1), "Eve <eve@example.org>")],
                  all_mail="[Google Mail]/All Mail")
    assert ("EXAMINE", '"[Google Mail]/All Mail"') in stub.calls


def test_candidate_and_owner_queries():
    _, stub = run([msg(1, 1001, at(1), "Eve <eve@example.org>")], days=21)
    raw = [c for c in stub.calls if c[:3] == ("UID", "SEARCH", "X-GM-RAW")]
    assert raw == [("UID", "SEARCH", "X-GM-RAW",
                    '"{in:inbox is:unread} newer_than:21d -in:chats -in:drafts '
                    '-category:promotions -category:social '
                    '-category:updates -category:forums"'),
                   ("UID", "SEARCH", "X-GM-RAW", '"from:me newer_than:21d -in:chats -in:drafts"')]


def test_owner_reply_in_another_thread_does_not_count():
    items, _ = run([msg(1, 1501, at(3), "Alice <alice@example.org>"),
                    msg(2, 1502, at(1), f"Me <{OWNER}>", cand=False)])
    assert ids(items) == ["1501"] and items[0]["n_messages"] == 1


def test_owner_message_older_than_last_inbound_does_not_count():
    items, _ = run([msg(1, 1601, at(5), f"Me <{OWNER}>", cand=False),
                    msg(2, 1601, at(2), "Alice <alice@example.org>")])
    assert ids(items) == ["1601"]
    assert items[0]["n_messages"] == 2           # messages seen in the window, owner's included


def test_owner_only_thread_is_not_listed():
    items, _ = run([msg(1, 1701, at(2), f"Me <{OWNER}>")])
    assert items == []


def test_exact_command_sequence_no_per_thread_searches():
    _, stub = run([msg(1, 1801, at(3), "Alice <alice@example.org>"),
                   msg(2, 1801, at(2), f"Me <{OWNER}>", cand=False),
                   msg(3, 1802, at(1), "Bob <bob@example.org>"),
                   msg(4, 1803, at(1), "Cy <cy@example.org>")])
    assert [c[:2] if c[0] == "UID" else c[:1] for c in stub.calls] == [
        ("LOGIN",), ("LIST",), ("EXAMINE",),
        ("UID", "SEARCH"), ("UID", "FETCH"),          # candidates, with headers
        ("UID", "SEARCH"), ("UID", "FETCH"),          # owner's messages, no headers
        ("LOGOUT",)]
    fetches = [c for c in stub.calls if c[:2] == ("UID", "FETCH")]
    assert fetches == [("UID", "FETCH", "1,3,4", iu.FETCH_ITEMS),
                       ("UID", "FETCH", "2", "(UID X-GM-THRID INTERNALDATE FLAGS)")]
    assert not any("X-GM-THRID" in " ".join(c[1:3]) for c in stub.calls if c[:2] == ("UID", "SEARCH"))


def test_fetches_are_chunked(monkeypatch):
    monkeypatch.setattr(iu, "FETCH_CHUNK", 2)
    msgs = [msg(i, 1900 + i, at(1), f"P{i} <p{i}@example.org>") for i in range(1, 6)]
    msgs += [msg(10 + i, 1900 + i, at(0.5), f"Me <{OWNER}>", cand=False) for i in (1, 2, 3)]
    items, stub = run(msgs)
    assert ids(items) == ["1904", "1905"]
    fetch_sets = [c[2] for c in stub.calls if c[:2] == ("UID", "FETCH")]
    assert fetch_sets == ["1,2", "3,4", "5", "11,12", "13"]
    assert len([c for c in stub.calls if c[:2] == ("UID", "SEARCH")]) == 2


def test_no_candidates_is_an_empty_result():
    items, stub = run([msg(1, 1101, at(1), "Eve <eve@example.org>", cand=False)])
    assert items == []
    assert not [c for c in stub.calls if c[:2] == ("UID", "FETCH")]


# ------------------------------------------------------------------ read-only


def test_read_only_command_log():
    _, stub = run([msg(1, 1201, at(3), "Alice <alice@example.org>"),
                   msg(2, 1201, at(2), f"Me <{OWNER}>", cand=False),
                   msg(3, 1202, at(1), "Bob <bob@example.org>")])
    names = {c[0] for c in stub.calls}
    subs = {c[1] for c in stub.calls if c[0] == "UID"}
    assert "EXAMINE" in names
    assert not (names | subs) & FORBIDDEN, stub.calls
    assert subs == {"SEARCH", "FETCH"}
    for c in stub.calls:
        if c[:2] == ("UID", "FETCH") and "BODY" in c[3]:
            assert "BODY.PEEK[HEADER.FIELDS" in c[3] and "BODY[" not in c[3]
    assert stub.is_readonly


# ------------------------------------------------------------------ failures


def test_parse_failure_is_named():
    with pytest.raises(iu.UnansweredError) as e:
        run([msg(1, 1301, at(1), "Eve <eve@example.org>")], bad_fetch=True)
    assert str(e.value).startswith("parse: ")


def test_overall_timeout_names_the_step():
    stub = StubImap([msg(1, 1401, at(1), "Eve <eve@example.org>")],
                    sleep_on=("UID", "SEARCH"))
    t0 = time.monotonic()
    with pytest.raises(iu.UnansweredError) as e:
        iu.find_unanswered(cfg(), now=NOW, connect=lambda h, p, t: stub, timeout=0.3)
    assert time.monotonic() - t0 < 3
    assert str(e.value).startswith("imap search: timed out")


def test_connect_timeout_is_passed_to_the_socket():
    seen = {}

    def connect(h, p, t):
        seen.update(host=h, port=p, timeout=t)
        raise OSError("nodename nor servname provided")
    with pytest.raises(iu.UnansweredError, match=r"^imap connect: nodename"):
        iu.find_unanswered(cfg(), connect=connect)
    assert seen == {"host": "imap.example.com", "port": 993, "timeout": 60}


# ------------------------------------------------------------------ config


def test_missing_account_names_the_setting():
    with pytest.raises(iu.UnansweredError, match=r"^config: imap_account is not set"):
        iu.resolve_config(dict(config.DEFAULTS), environ={})


def test_missing_password_names_the_setting():
    s = {**config.DEFAULTS, "imap_account": OWNER}
    with pytest.raises(iu.UnansweredError, match=r"^config: imap_keychain_service is not set"):
        iu.resolve_config(s, environ={}, keychain=lambda *a, **k: pytest.fail("no read"))


def test_keychain_read_uses_service_and_account():
    calls = []
    s = {**config.DEFAULTS, "imap_account": OWNER, "imap_keychain_service": "my-imap"}
    c = iu.resolve_config(s, environ={},
                          keychain=lambda svc, account: calls.append((svc, account)) or "pw")
    assert calls == [("my-imap", OWNER)]
    assert (c.host, c.account, c.password) == ("imap.gmail.com", OWNER, "pw")


def test_keychain_failure_is_named():
    def locked(service, account):
        raise providers.ProviderError("Keychain locked for this shell")
    s = {**config.DEFAULTS, "imap_account": OWNER, "imap_keychain_service": "my-imap"}
    with pytest.raises(iu.UnansweredError, match=r"^keychain: Keychain locked"):
        iu.resolve_config(s, environ={}, keychain=locked)


def test_env_overrides_settings():
    s = {**config.DEFAULTS, "imap_account": "settings@example.com",
         "imap_keychain_service": "my-imap"}
    c = iu.resolve_config(s, environ={"IMAP_ACCOUNT": "env@example.com",
                                      "IMAP_APP_PASSWORD": "env-pw"},
                          keychain=lambda *a, **k: pytest.fail("env wins, no Keychain read"))
    assert (c.account, c.password) == ("env@example.com", "env-pw")


def test_imap_settings_are_inert_defaults():
    assert config.DEFAULTS["imap_account"] == ""
    assert config.DEFAULTS["imap_keychain_service"] == ""
    assert config.DEFAULTS["imap_host"] == "imap.gmail.com"


# ------------------------------------------------------------------ the CLI and its contract


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Run the real `frontdesk unanswered` path with the stub in place of IMAP4_SSL."""
    for k in ("IMAP_ACCOUNT", "IMAP_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    holder = {}

    def use(msgs, **kw):
        stub = StubImap(msgs, **kw)
        holder["stub"] = stub

        def ssl(host, port, timeout=None):
            holder["connect"] = (host, port, timeout)
            return stub
        monkeypatch.setattr(iu.imaplib, "IMAP4_SSL", ssl)
        return stub
    return use, holder


def settings_file(**kw):
    config.HOME.mkdir(parents=True, exist_ok=True)
    config.SETTINGS_PATH.write_text(json.dumps(kw))


def test_json_contract(wired, monkeypatch, capsys):
    use, holder = wired
    monkeypatch.setenv("IMAP_ACCOUNT", OWNER)
    monkeypatch.setenv("IMAP_APP_PASSWORD", "app-pw")
    use([msg(1, 1278455344230334865, datetime.now(UTC) - timedelta(days=3, hours=5),
             "=?UTF-8?Q?Ren=C3=A9e?= <renee@example.org>", subject="Lunch?"),
         msg(2, 77, datetime.now(UTC) - timedelta(days=1), "Bob <bob@example.org>"),
         msg(3, 78, datetime.now(UTC) - timedelta(hours=2), "Cy <cy@example.org>")])
    assert cli.main(["unanswered", "--json", "--limit", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out) == ["total", "items"] and out["total"] == 3 and len(out["items"]) == 2
    it = out["items"][0]
    assert list(it) == ["thread_id", "gmail_url", "from_name", "from_addr", "subject",
                        "last_at", "age_days", "n_messages"]
    types = {"thread_id": str, "gmail_url": str, "from_name": str, "from_addr": str,
             "subject": str, "last_at": str, "age_days": int, "n_messages": int}
    for item in out["items"]:
        assert {k: type(v) for k, v in item.items()} == types
    assert it["thread_id"] == "1278455344230334865"
    assert it["from_name"] == "Renée" and it["age_days"] == 3 and it["n_messages"] == 1
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", it["last_at"])
    assert datetime.fromisoformat(it["last_at"]).utcoffset() is not None
    assert [x["thread_id"] for x in out["items"]] == ["1278455344230334865", "77"]
    assert holder["connect"] == ("imap.gmail.com", 993, 60)
    assert ("LOGIN", OWNER, '"app-pw"') in holder["stub"].calls


def test_cli_auth_failure_is_loud(wired, monkeypatch, capsys):
    use, _ = wired
    monkeypatch.setenv("IMAP_ACCOUNT", OWNER)
    monkeypatch.setenv("IMAP_APP_PASSWORD", "wrong")
    use([msg(1, 1, at(1), "Eve <eve@example.org>")],
        login_reply=("NO", [b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)"]))
    assert cli.main(["unanswered", "--json"]) != 0
    cap = capsys.readouterr()
    assert cap.out == ""                                      # never an empty list
    lines = cap.err.strip().splitlines()
    assert len(lines) == 1
    assert lines[0] == ("frontdesk unanswered: imap login: [AUTHENTICATIONFAILED] "
                        "Invalid credentials (Failure)")


def test_cli_missing_config_is_loud_and_creates_nothing(wired, capsys):
    assert cli.main(["unanswered", "--json"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.strip() == ("frontdesk unanswered: config: imap_account is not set (your "
                               "Gmail address, in settings.json or IMAP_ACCOUNT)")
    assert not config.HOME.exists()


def test_cli_reads_settings_and_keychain(wired, monkeypatch, capsys):
    use, holder = wired
    settings_file(imap_account=OWNER, imap_keychain_service="my-imap", imap_host="imap.test")
    reads = []
    monkeypatch.setattr(providers, "keychain_secret",
                        lambda svc, account=None: reads.append((svc, account)) or "kc-pw")
    use([msg(1, 5, at(1), "Eve <eve@example.org>")])
    assert cli.main(["unanswered", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1
    assert reads == [("my-imap", OWNER)]
    assert holder["connect"][0] == "imap.test"
    assert ("LOGIN", OWNER, '"kc-pw"') in holder["stub"].calls


def test_keychain_helper_passes_account(monkeypatch):
    seen = []

    class R:
        returncode, stdout = 0, "secret\n"
    monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/security")
    monkeypatch.setattr(providers.subprocess, "run", lambda argv, **k: seen.append(argv) or R())
    assert providers.keychain_secret("svc", account="a@example.com") == "secret"
    assert providers.keychain_secret("svc") == "secret"
    assert seen == [["security", "find-generic-password", "-s", "svc", "-a", "a@example.com",
                     "-w"],
                    ["security", "find-generic-password", "-s", "svc", "-w"]]


# ------------------------------------------------------------------ ignore list (owner-configured)

def test_ignored_matches_addresses_and_domains():
    ign = ("reports@example.com", "@example.org", "example.net")
    assert iu.ignored("reports@example.com", ign)
    assert not iu.ignored("person@example.com", ign)
    assert iu.ignored("ann@example.org", ign) and iu.ignored("ann@mail.example.org", ign)
    assert iu.ignored("bo@example.net", ign)
    assert not iu.ignored("ann@notexample.org", ign)


def test_ignored_senders_are_not_listed():
    msgs = [msg(1, 101, at(3), "Reports <reports@example.com>"),
            msg(2, 102, at(2), "Alice <alice@example.org>")]
    stub = StubImap(msgs)
    c = iu.ImapConfig(host="imap.example.com", account=OWNER, password="app-pw",
                      ignore=("reports@example.com",))
    items = iu.find_unanswered(c, days=14, now=NOW, connect=lambda h, p, t: stub)
    assert ids(items) == ["102"]


@pytest.mark.parametrize("bad", ["reports@example.com", [""], [3]])
def test_ignore_list_must_be_a_list_of_text(bad):
    with pytest.raises(iu.UnansweredError, match="unanswered_ignore_senders"):
        iu.resolve_config({"imap_host": "h", "imap_account": OWNER,
                           "unanswered_ignore_senders": bad}, environ={"IMAP_APP_PASSWORD": "x"})


def test_ignore_list_from_settings_is_lowercased():
    c = iu.resolve_config({"imap_host": "h", "imap_account": OWNER,
                           "unanswered_ignore_senders": [" Reports@Example.com "]},
                          environ={"IMAP_APP_PASSWORD": "x"})
    assert c.ignore == ("reports@example.com",)
