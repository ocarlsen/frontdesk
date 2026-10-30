"""`frontdesk inbox-buckets`, fully offline: reuses imaplib stub from test_unanswered.py (extended
locally with category-search support) so imaplib's own select/uid/login code runs and the call
log holds the real IMAP command names. No network, no Keychain."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from test_unanswered import StubImap, msg, settings_file

from frontdesk import __main__ as cli
from frontdesk.gmail import imap_buckets as ib
from frontdesk.gmail import imap_unanswered as iu

OWNER = "owner@example.com"
PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 29, 17, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=1)                       # 2026-10-28T17:00:00Z
EXPECTED_DAYS = 2                                      # ceil((NOW-SINCE)/1d) + 1
FORBIDDEN = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "CLOSE"}


def at(offset_days: float, tz=PDT) -> datetime:
    """SINCE plus offset_days; use a bigger offset for a later message, a negative one to land
    before --since (for the since-filtering tests)."""
    return (SINCE + timedelta(days=offset_days)).astimezone(tz)


class BucketStub(StubImap):
    """Adds Gmail-category search support on top of test_unanswered's StubImap: a message's
    `categories` field (a set of names) decides which `category:<name>` searches it matches.
    Everything else (LOGIN, LIST, EXAMINE, the from:me/general SEARCH, FETCH, LOGOUT) is
    unchanged, inherited behavior."""

    def _simple_command(self, name, *args):
        if (name == "UID" and args and args[0] == "SEARCH" and len(args) >= 3
                and args[1] == "X-GM-RAW" and args[2].strip('"').startswith("category:")):
            self.calls.append((name, *args))
            cat = args[2].strip('"').split()[0].split(":", 1)[1]
            hits = [m for m in self.msgs if cat in m.get("categories", ())]
            self.untagged_responses["SEARCH"] = [" ".join(str(m["uid"]) for m in hits).encode()]
            return "OK", [b"SEARCH completed"]
        return super()._simple_command(name, *args)


def cmsg(*a, categories=(), **kw):
    """msg() plus an optional set of Gmail categories the stub's category search matches it on."""
    m = msg(*a, **kw)
    m["categories"] = set(categories)
    return m


def cfg(ignore=()):
    return iu.ImapConfig(host="imap.example.com", account=OWNER, password="app-pw", ignore=ignore)


def run(msgs, since=SINCE, newsletter_senders=(), person_senders=(), ignore=(), other_senders=(),
        **kw):
    stub = BucketStub(msgs, **kw)
    classified = ib.find_buckets(cfg(ignore), since, newsletter_senders=newsletter_senders,
                                 person_senders=person_senders, other_senders=other_senders,
                                 now=NOW, connect=lambda h, p, t: stub)
    return classified, stub


def ids(items):
    return [it["thread_id"] for it in items]


def bucket_ids(classified, name):
    return ids(classified[2][name])


def replied_ids(classified):
    return classified[1]


def expected_ids(classified):
    return classified[0]


# ------------------------------------------------------------------ bucket rules


def test_unanswered_bucket_is_a_person_not_automated_not_ignored():
    classified = run([cmsg(1, 101, at(0.1), "Alice <alice@example.org>")])[0]
    assert bucket_ids(classified, "unanswered") == ["101"]
    assert expected_ids(classified) == {"101"} and replied_ids(classified) == set()


def test_newsletter_by_list_unsubscribe_header():
    classified = run([cmsg(1, 201, at(0.1), "News <news@example.org>",
                           headers=[("List-Unsubscribe", "<mailto:u@example.org>")])])[0]
    assert bucket_ids(classified, "newsletters") == ["201"]
    item = classified[2]["newsletters"][0]
    assert item["read_url"] == item["gmail_url"]


def test_newsletter_by_list_id_and_precedence_bulk_or_list():
    classified = run([
        cmsg(1, 301, at(0.1), "A <a@example.org>", headers=[("List-Id", "x <x.example.org>")]),
        cmsg(2, 302, at(0.1), "B <b@example.org>", headers=[("Precedence", "bulk")]),
        cmsg(3, 303, at(0.1), "C <c@example.org>", headers=[("Precedence", "list")]),
    ])[0]
    assert set(bucket_ids(classified, "newsletters")) == {"301", "302", "303"}


def test_newsletter_senders_setting_matches_address_and_domain():
    classified = run(
        [cmsg(1, 401, at(0.1), "Promo <promo@shop.example.org>"),
         cmsg(2, 402, at(0.1), "Alice <alice@example.org>")],
        newsletter_senders=("@shop.example.org",))[0]
    assert bucket_ids(classified, "newsletters") == ["401"]
    assert bucket_ids(classified, "unanswered") == ["402"]


def test_other_bucket_is_automated_and_ignore_listed():
    classified = run([
        cmsg(1, 501, at(0.1), "Svc <noreply@example.org>"),            # automated
        cmsg(2, 502, at(0.1), "Reports <reports@example.com>"),        # ignore-listed
    ], ignore=("reports@example.com",))[0]
    assert set(bucket_ids(classified, "other")) == {"501", "502"}
    assert bucket_ids(classified, "unanswered") == []
    assert bucket_ids(classified, "newsletters") == []


def test_primary_category_mail_from_a_person_is_still_unanswered():
    classified = run([cmsg(1, 601, at(0.1), "Alice <alice@example.org>")])[0]
    assert bucket_ids(classified, "unanswered") == ["601"]


# ------------------------------------------------------------------ A: Gmail categories


def test_updates_category_without_list_signals_is_other_not_unanswered():
    classified = run([cmsg(1, 1001, at(0.1), "Order <orders@amazon.example>",
                           categories={"updates"})])[0]
    assert bucket_ids(classified, "other") == ["1001"]
    assert bucket_ids(classified, "unanswered") == []
    assert bucket_ids(classified, "newsletters") == []


def test_promotions_category_with_list_unsubscribe_is_newsletters():
    classified = run([cmsg(1, 1002, at(0.1), "Deal <deal@shop.example>", categories={"promotions"},
                           headers=[("List-Unsubscribe", "<mailto:u@shop.example>")])])[0]
    assert bucket_ids(classified, "newsletters") == ["1002"]


def test_person_senders_overrides_the_category_rule():
    classified = run([cmsg(1, 1003, at(0.1), "Recruiter <jobs@greenhouse.example>",
                           categories={"updates"})],
                     person_senders=("@greenhouse.example",))[0]
    assert bucket_ids(classified, "unanswered") == ["1003"]
    assert bucket_ids(classified, "other") == []


def test_person_senders_overrides_newsletter_header_rules():
    classified = run([cmsg(1, 1004, at(0.1), "List <group@googlegroups.com>",
                           headers=[("List-Id", "x <x.googlegroups.com>")])],
                     person_senders=("@googlegroups.com",))[0]
    assert bucket_ids(classified, "unanswered") == ["1004"]
    assert bucket_ids(classified, "newsletters") == []


def test_category_searches_use_the_same_window_and_fixed_count():
    _, stub = run([cmsg(1, 1005, at(0.1), "Eve <eve@example.org>")])
    raw = [c[3] for c in stub.calls if c[:3] == ("UID", "SEARCH", "X-GM-RAW")]
    assert raw[0] == f'"in:inbox newer_than:{EXPECTED_DAYS}d -in:chats -in:drafts"'
    assert raw[1] == f'"from:me newer_than:{EXPECTED_DAYS}d -in:chats -in:drafts"'
    assert raw[2:6] == [f'"category:{c} newer_than:{EXPECTED_DAYS}d -in:chats -in:drafts"'
                       for c in ib.CATEGORIES]
    assert len(raw) == 6                                   # exactly 2 + 4, never per-thread


# ------------------------------------------------------------------ precedence


def test_replied_out_beats_every_other_rule():
    classified = run([
        cmsg(1, 701, at(0.1), "News <news@example.org>",
            headers=[("List-Unsubscribe", "<mailto:u@example.org>")]),
        cmsg(2, 701, at(0.3), f"Me <{OWNER}>", cand=False),
    ])[0]
    assert replied_ids(classified) == {"701"}
    assert all(v == [] for v in classified[2].values())


def test_newsletter_beats_unanswered_never_both():
    # A newsletter sender is never "unanswered" even though it looks like a person replying.
    classified = run([cmsg(1, 801, at(0.1), "Alice <alice@example.org>",
                           headers=[("List-Id", "x <x.example.org>")])])[0]
    assert bucket_ids(classified, "newsletters") == ["801"]
    assert bucket_ids(classified, "unanswered") == []


# ------------------------------------------------------------------ replied-out


def test_owner_reply_is_left_out_and_counted():
    classified = run([
        cmsg(1, 901, at(0.1), "Alice <alice@example.org>"),
        cmsg(2, 901, at(0.3), f"Me <{OWNER}>", cand=False),           # owner replied
        cmsg(3, 902, at(0.1), "Bob <bob@example.org>"),                # still waiting
    ])[0]
    assert replied_ids(classified) == {"901"}
    assert bucket_ids(classified, "unanswered") == ["902"]
    assert expected_ids(classified) == {"901", "902"}


# ------------------------------------------------------------------ since filtering (INTERNALDATE)


def test_message_just_before_since_is_excluded_just_after_is_included():
    just_before = SINCE - timedelta(minutes=1)
    just_after = SINCE + timedelta(minutes=1)
    classified = run([
        cmsg(1, 1101, just_before, "Alice <alice@example.org>"),
        cmsg(2, 1102, just_after, "Bob <bob@example.org>"),
    ])[0]
    assert bucket_ids(classified, "unanswered") == ["1102"]
    assert expected_ids(classified) == {"1102"}


def test_since_exactly_equal_is_included():
    classified = run([cmsg(1, 1201, SINCE, "Alice <alice@example.org>")])[0]
    assert bucket_ids(classified, "unanswered") == ["1201"]


# ------------------------------------------------------------------ G(a): mixed in/out of window


def test_thread_with_messages_before_and_after_since_counted_once():
    classified = run([
        cmsg(1, 1301, SINCE - timedelta(hours=5), "Alice <alice@example.org>"),  # out of window
        cmsg(2, 1301, SINCE + timedelta(hours=1), "Alice <alice@example.org>"),  # in window
        cmsg(3, 1301, SINCE + timedelta(hours=2), "Alice <alice@example.org>"),  # in window
    ])[0]
    assert expected_ids(classified) == {"1301"}
    assert bucket_ids(classified, "unanswered") == ["1301"]
    assert classified[2]["unanswered"][0]["n_messages"] == 2        # the pre-window one excluded


# ------------------------------------------------------------------ G(b)/(c): owner edge cases


def test_owner_draft_newer_than_inbound_does_not_count_as_replied():
    classified = run([
        cmsg(1, 1401, at(0.1), "Alice <alice@example.org>"),
        cmsg(2, 1401, at(0.3), f"Me <{OWNER}>", cand=False, flags="\\Seen \\Draft"),
    ])[0]
    assert replied_ids(classified) == set()
    assert bucket_ids(classified, "unanswered") == ["1401"]


def test_owner_message_in_window_but_older_than_inbound_does_not_count_as_replied():
    classified = run([
        cmsg(1, 1501, at(0.1), f"Me <{OWNER}>", cand=False),           # owner spoke first
        cmsg(2, 1501, at(0.3), "Alice <alice@example.org>"),            # then Alice, now newest
    ])[0]
    assert replied_ids(classified) == set()
    assert bucket_ids(classified, "unanswered") == ["1501"]


def test_owner_message_before_since_never_counts_as_replied():
    classified = run([
        cmsg(1, 1601, SINCE - timedelta(hours=1), f"Me <{OWNER}>", cand=False),  # before --since
        cmsg(2, 1601, at(0.1), "Alice <alice@example.org>"),
    ])[0]
    assert replied_ids(classified) == set()
    assert bucket_ids(classified, "unanswered") == ["1601"]
    assert classified[2]["unanswered"][0]["n_messages"] == 1


# ------------------------------------------------------------------ G(d): unparseable From


def test_from_with_no_parseable_address_lands_in_other_not_dropped():
    classified = run([cmsg(1, 1701, at(0.1), "<>")])[0]  # parseaddr gives ("", "") for this
    assert expected_ids(classified) == {"1701"}
    assert bucket_ids(classified, "other") == ["1701"]
    assert classified[2]["other"][0]["from_addr"] == ""


# ------------------------------------------------------------------ B: the count invariant


def test_count_invariant_failure_is_loud_step_named():
    # thread "1" is expected but never lands in replied or any bucket: a thread went missing.
    classified = ({"1", "2"}, {"2"}, {"unanswered": [], "newsletters": [], "other": []})
    with pytest.raises(ib.BucketsError, match=r"^count: "):
        ib.report(classified, 15, "2026-10-28T17:00:00Z")


def test_count_invariant_catches_a_thread_in_two_buckets():
    item = {"thread_id": "1", "gmail_url": "u", "from_name": "", "from_addr": "a@b.com",
           "subject": "s", "last_at": "2026-10-28T17:00:00+00:00", "age_days": 0,
           "n_messages": 1}
    classified = ({"1"}, set(), {"unanswered": [item], "newsletters": [dict(item)], "other": []})
    with pytest.raises(ib.BucketsError, match=r"^count: "):
        ib.report(classified, 15, "2026-10-28T17:00:00Z")


def test_count_invariant_holds_on_a_real_run():
    classified = run([cmsg(1, 1801, at(0.1), "Alice <alice@example.org>"),
                      cmsg(2, 1802, at(0.1), f"Me <{OWNER}>")])[0]
    rep = ib.report(classified, 15, "2026-10-28T17:00:00Z")
    assert rep["total"] == (rep["replied"] + sum(b["total"] for b in rep["buckets"].values()))


def test_cli_count_invariant_exits_2(monkeypatch, capsys, tmp_path):
    """A broken _classify (here: one that drops a thread from every bucket) must exit 2 naming
    the 'count' step, never print a short list as if nothing were wrong."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMAP_ACCOUNT", OWNER)
    monkeypatch.setenv("IMAP_APP_PASSWORD", "app-pw")
    stub = BucketStub([cmsg(1, 2001, at(0.1), "Alice <alice@example.org>")])
    monkeypatch.setattr(iu.imaplib, "IMAP4_SSL", lambda h, p, timeout=None: stub)

    def broken(cand, mine, account, owner, since, now, ignore, newsletter_senders,
              person_senders, category_uids, other_senders=()):
        return {"2001"}, set(), {"unanswered": [], "newsletters": [], "other": []}
    monkeypatch.setattr(ib, "_classify", broken)
    assert cli.main(["inbox-buckets", "--json", "--since", SINCE.isoformat()]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.strip().startswith("frontdesk inbox-buckets: count: ")


# ------------------------------------------------------------------ malformed --since


def test_malformed_since_is_rejected():
    with pytest.raises(ib.BucketsError, match=r"^args: --since is not a valid"):
        ib.parse_since("not-a-date")


def test_naive_since_is_rejected():
    with pytest.raises(ib.BucketsError, match=r"^args: --since must include a UTC offset"):
        ib.parse_since("2026-10-28T17:00:00")


def test_well_formed_since_round_trips():
    d = ib.parse_since("2026-10-28T17:00:00-07:00")
    assert d.utcoffset() == timedelta(hours=-7)


# ------------------------------------------------------------------ read-only


def test_read_only_command_log():
    _, stub = run([cmsg(1, 1901, at(0.1), "Alice <alice@example.org>"),
                   cmsg(2, 1901, at(0.3), f"Me <{OWNER}>", cand=False),
                   cmsg(3, 1902, at(0.1), "Bob <bob@example.org>")])
    names = {c[0] for c in stub.calls}
    subs = {c[1] for c in stub.calls if c[0] == "UID"}
    assert "EXAMINE" in names
    assert not (names | subs) & FORBIDDEN, stub.calls
    assert subs == {"SEARCH", "FETCH"}
    for c in stub.calls:
        if c[:2] == ("UID", "FETCH") and "BODY" in c[3]:
            assert "BODY.PEEK[HEADER.FIELDS" in c[3] and "BODY[" not in c[3]
    assert stub.is_readonly


def test_exact_command_sequence_no_per_thread_searches():
    _, stub = run([cmsg(1, 2101, at(0.1), "Alice <alice@example.org>"),
                   cmsg(2, 2101, at(0.3), f"Me <{OWNER}>", cand=False),
                   cmsg(3, 2102, at(0.1), "Bob <bob@example.org>")])
    assert [c[:2] if c[0] == "UID" else c[:1] for c in stub.calls] == [
        ("LOGIN",), ("LIST",), ("EXAMINE",),
        ("UID", "SEARCH"), ("UID", "FETCH"),          # candidates
        ("UID", "SEARCH"), ("UID", "FETCH"),          # owner's messages
        ("UID", "SEARCH"), ("UID", "SEARCH"), ("UID", "SEARCH"), ("UID", "SEARCH"),  # categories
        ("LOGOUT",)]


def test_no_candidates_skips_owner_and_category_searches():
    classified, stub = run([cmsg(1, 2201, at(0.1), "Eve <eve@example.org>", cand=False)])
    assert expected_ids(classified) == set() and replied_ids(classified) == set()
    assert all(v == [] for v in classified[2].values())
    calls = [c[:2] for c in stub.calls if c[0] == "UID"]
    assert calls == [("UID", "SEARCH")]   # the candidate search only


# ------------------------------------------------------------------ per-bucket cap, uncapped totals


def test_per_bucket_cap_leaves_total_uncapped():
    msgs = [cmsg(i, 2300 + i, at(0.1 * i), f"P{i} <p{i}@example.org>") for i in range(1, 6)]
    classified = run(msgs)[0]
    rep = ib.report(classified, 2, "2026-10-28T17:00:00Z")
    assert rep["buckets"]["unanswered"]["total"] == 5
    assert len(rep["buckets"]["unanswered"]["items"]) == 2
    assert rep["total"] == 5


# ------------------------------------------------------------------ JSON shape


def test_json_shape_exactly():
    classified = run([
        cmsg(1, 2401, at(0.1), "Alice <alice@example.org>"),
        cmsg(2, 2402, at(0.1), "News <news@example.org>",
            headers=[("List-Id", "x <x.example.org>")]),
        cmsg(3, 2403, at(0.1), "Svc <noreply@example.org>"),
        cmsg(4, 2404, at(0.1), "Carol <carol@example.org>"),
        cmsg(5, 2404, at(0.3), f"Me <{OWNER}>", cand=False),
    ])[0]
    rep = ib.report(classified, 15, "2026-10-28T17:00:00-07:00")
    assert list(rep) == ["since", "total", "replied", "buckets"]
    assert rep["since"] == "2026-10-28T17:00:00-07:00"
    assert rep["total"] == 4 and rep["replied"] == 1
    assert list(rep["buckets"]) == ["unanswered", "newsletters", "other"]
    for name in ("unanswered", "newsletters", "other"):
        assert list(rep["buckets"][name]) == ["total", "items"]
    item_keys = ["thread_id", "gmail_url", "from_name", "from_addr", "subject", "last_at",
                "age_days", "n_messages"]
    assert list(rep["buckets"]["unanswered"]["items"][0]) == item_keys
    assert list(rep["buckets"]["newsletters"]["items"][0]) == item_keys + ["read_url"]
    assert list(rep["buckets"]["other"]["items"][0]) == item_keys


# ------------------------------------------------------------------ the CLI


@pytest.fixture
def wired(monkeypatch, tmp_path):
    for k in ("IMAP_ACCOUNT", "IMAP_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    holder = {}

    def use(msgs, **kw):
        stub = BucketStub(msgs, **kw)
        holder["stub"] = stub

        def ssl(host, port, timeout=None):
            holder["connect"] = (host, port, timeout)
            return stub
        monkeypatch.setattr(iu.imaplib, "IMAP4_SSL", ssl)
        return stub
    return use, holder


def test_cli_json_contract(wired, monkeypatch, capsys):
    use, holder = wired
    monkeypatch.setenv("IMAP_ACCOUNT", OWNER)
    monkeypatch.setenv("IMAP_APP_PASSWORD", "app-pw")
    use([cmsg(1, 2501, at(0.1), "Alice <alice@example.org>")])
    since_str = SINCE.isoformat()
    assert cli.main(["inbox-buckets", "--json", "--since", since_str]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["since"] == since_str
    assert out["total"] == 1 and out["buckets"]["unanswered"]["total"] == 1


def test_cli_malformed_since_exits_2_before_any_imap_call(wired, capsys):
    use, holder = wired
    assert cli.main(["inbox-buckets", "--json", "--since", "nope"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.strip() == ("frontdesk inbox-buckets: args: --since is not a valid ISO 8601 "
                               "timestamp: 'nope'")
    assert "connect" not in holder


def test_cli_missing_config_is_loud(wired, capsys):
    assert cli.main(["inbox-buckets", "--json", "--since", "2026-10-28T17:00:00-07:00"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.strip().startswith("frontdesk inbox-buckets: config: imap_account is not set")


def test_cli_human_summary(wired, monkeypatch, capsys):
    use, holder = wired
    monkeypatch.setenv("IMAP_ACCOUNT", OWNER)
    monkeypatch.setenv("IMAP_APP_PASSWORD", "app-pw")
    use([cmsg(1, 2601, at(0.1), "Alice <alice@example.org>")])
    assert cli.main(["inbox-buckets", "--since", SINCE.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "unanswered (1)" in out
    assert "1 new, 0 already replied to" in out


# ------------------------------------------------------------------ G(f): malformed sender lists


@pytest.mark.parametrize("key", ["newsletter_senders", "person_senders"])
def test_cli_malformed_sender_list_is_a_config_failure_before_any_imap_call(wired, capsys, key):
    use, holder = wired
    settings_file(imap_account=OWNER, imap_keychain_service="my-imap", **{key: "not-a-list"})
    assert cli.main(["inbox-buckets", "--json", "--since", "2026-10-28T17:00:00-07:00"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.strip() == (f"frontdesk inbox-buckets: config: {key} must be a list of "
                               'addresses or domains, e.g. ["reports@example.com", '
                               '"@example.org"]')
    assert "connect" not in holder


def test_newsletter_and_person_senders_are_lowercased_and_trimmed():
    assert ib._newsletter_senders({"newsletter_senders": [" Shop@Example.com "]}) == \
        ("shop@example.com",)
    assert ib._person_senders({"person_senders": [" @Greenhouse.Example "]}) == \
        ("@greenhouse.example",)


# ---------- other_senders: notices that look exactly like newsletters ----------

GOOGLE_NOTICE_HEADERS = [("List-Id", "<98b5bb@google.com>"),
                         ("List-Unsubscribe", "<https://myaccount.google.com/unsubscribe>")]


def test_account_notice_with_newsletter_headers_is_a_newsletter_without_the_setting():
    classified = run([cmsg(1, 1101, at(0.1), "Google <noreply-accounts@google.com>",
                           headers=GOOGLE_NOTICE_HEADERS, categories={"updates"})])[0]
    assert bucket_ids(classified, "newsletters") == ["1101"]


def test_other_senders_pins_it_to_other_by_address_or_domain():
    for entry in ("noreply-accounts@google.com", "@google.com"):
        classified = run([cmsg(1, 1102, at(0.1), "Google <noreply-accounts@google.com>",
                               headers=GOOGLE_NOTICE_HEADERS, categories={"updates"})],
                         other_senders=(entry,))[0]
        assert bucket_ids(classified, "other") == ["1102"], entry
        assert bucket_ids(classified, "newsletters") == []


def test_person_senders_beats_other_senders():
    classified = run([cmsg(1, 1103, at(0.1), "Pat <pat@example.org>")],
                     person_senders=("pat@example.org",), other_senders=("@example.org",))[0]
    assert bucket_ids(classified, "unanswered") == ["1103"]


def test_malformed_other_senders_is_a_loud_config_failure():
    with pytest.raises(ib.BucketsError, match="other_senders"):
        ib._other_senders({"other_senders": "noreply-accounts@google.com"})
