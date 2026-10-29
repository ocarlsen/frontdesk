"""normalize.thread_to_item on synthetic, hand-written Gmail thread JSON (no real data)."""
from __future__ import annotations

import base64
from urllib.parse import quote

from frontdesk.gmail import auth
from frontdesk.gmail.normalize import BODY_CAP, thread_to_item

ME = "owner@example.com"


def b64(s: str, charset: str = "utf-8") -> str:
    return base64.urlsafe_b64encode(s.encode(charset)).decode().rstrip("=")


def part(mime: str, text: str, charset: str = "utf-8") -> dict:
    return {
        "mimeType": mime,
        "filename": "",
        "headers": [{"name": "Content-Type", "value": f'{mime}; charset="{charset}"'}],
        "body": {"data": b64(text, charset), "size": len(text)},
    }


def msg(mid: str, ms: int, frm: str, payload: dict, to: str = ME, cc: str = "",
        subject: str = "Lunch plans", labels: list[str] | None = None) -> dict:
    headers = [{"name": "From", "value": frm}, {"name": "To", "value": to},
               {"name": "Subject", "value": subject}]
    if cc:
        headers.append({"name": "Cc", "value": cc})
    payload = dict(payload)
    payload["headers"] = headers + payload.get("headers", [])
    return {"id": mid, "threadId": "t1", "internalDate": str(ms),
            "labelIds": labels if labels is not None else ["INBOX"], "payload": payload}


def thread(*messages: dict) -> dict:
    return {"id": "t1", "messages": list(messages)}


def alternative(plain: str, html: str) -> dict:
    return {"mimeType": "multipart/alternative", "filename": "", "headers": [],
            "body": {"size": 0}, "parts": [part("text/plain", plain), part("text/html", html)]}


def test_scopes_are_readonly_only():
    assert auth.SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_basic_fields_and_multipart_prefers_plain():
    t = thread(msg("m1", 1_700_000_000_000, "Alice Example <alice@example.com>",
                   alternative("Plain body here", "<p>HTML body here</p>"),
                   cc="Bob <bob@example.com>"))
    item = thread_to_item(t, ME)
    assert item.id == "gmail:t1"
    assert item.source == "gmail"
    assert item.account == ME
    assert item.subject == "Lunch plans"
    assert item.messages[0].body == "Plain body here"
    assert item.messages[0].sender == "Alice Example <alice@example.com>"
    assert item.messages[0].sent_at == "2023-11-14T22:13:20Z"
    assert item.participants == ["alice@example.com", ME, "bob@example.com"]
    assert item.labels == ["INBOX"]
    assert item.url == f"https://mail.google.com/mail/?authuser={quote(ME, safe="@")}#all/t1"


def test_nested_multipart_mixed_finds_plain_and_skips_attachment():
    attachment = part("text/plain", "attachment text")
    attachment["filename"] = "notes.txt"
    payload = {"mimeType": "multipart/mixed", "filename": "", "headers": [], "body": {},
               "parts": [attachment, alternative("Real body", "<b>Real body</b>")]}
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", payload)), ME)
    assert item.messages[0].body == "Real body"


def test_html_only_fallback_strips_tags_and_scripts():
    html = ("<html><head><style>p{color:red}</style></head><body>"
            "<p>Hello&nbsp;there</p><script>alert(1)</script>"
            "<div>Line two<br>Line three</div></body></html>")
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", part("text/html", html))), ME)
    body = item.messages[0].body
    assert "Hello there" in body
    assert "Line two\nLine three" in body
    assert "alert" not in body and "color" not in body and "<" not in body


def test_strips_on_wrote_history():
    text = ("Sounds good, see you then.\n\nOn Mon, Jan 1, 2024 at 9:00 AM Bob <bob@example.com> "
            "wrote:\n> Want to meet Tuesday?\n")
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", part("text/plain", text))), ME)
    assert item.messages[0].body == "Sounds good, see you then."


def test_strips_wrapped_on_wrote_header():
    text = "Yes.\n\nOn Mon, Jan 1, 2024 at 9:00 AM Bob Example <bob@example.com>\nwrote:\n\n> Q?\n"
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", part("text/plain", text))), ME)
    assert item.messages[0].body == "Yes."


def test_strips_angle_quotes_and_outlook_block():
    text_gt = "Agreed.\n> earlier text\n> more"
    text_ol = ("Will do.\n\n________________________________\nFrom: Bob <bob@example.com>\n"
               "Sent: Monday, January 1, 2024 9:00 AM\nTo: Alice\nSubject: RE: thing\n\nOld text")
    text_orig = "Thanks!\n-----Original Message-----\nFrom: bob@example.com\nold"
    t = thread(msg("m1", 1000, "alice@example.com", part("text/plain", text_gt)),
               msg("m2", 2000, "alice@example.com", part("text/plain", text_ol)),
               msg("m3", 3000, "alice@example.com", part("text/plain", text_orig)))
    bodies = [m.body for m in thread_to_item(t, ME).messages]
    assert bodies == ["Agreed.", "Will do.", "Thanks!"]


def test_message_that_is_only_a_quote_keeps_text():
    text = "> quoted question\nmy inline answer"
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", part("text/plain", text))), ME)
    assert "my inline answer" in item.messages[0].body


def test_collapses_blank_lines():
    text = "one\n\n\n\n\ntwo\r\n\r\n\r\n\r\nthree"
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", part("text/plain", text))), ME)
    assert item.messages[0].body == "one\n\ntwo\n\nthree"


def test_is_mine_case_insensitive():
    t = thread(msg("m1", 1000, "alice@example.com", part("text/plain", "hi")),
               msg("m2", 2000, "Owner <OWNER@Example.com>", part("text/plain", "hello"),
                   to="alice@example.com", labels=["SENT"]))
    item = thread_to_item(t, ME)
    assert [m.is_mine for m in item.messages] == [False, True]


def test_is_mine_requires_sent_label():
    """A From header can be forged by anyone; Gmail's SENT label cannot."""
    t = thread(msg("m1", 1000, "Owner <owner@example.com>", part("text/plain", "approved"),
                   labels=["INBOX"]))
    assert thread_to_item(t, ME).messages[0].is_mine is False


def test_draft_messages_skipped_and_all_draft_thread_is_none():
    t = thread(msg("m1", 1000, "alice@example.com", part("text/plain", "question")),
               msg("m2", 2000, ME, part("text/plain", "unsent reply"), labels=["DRAFT"]))
    item = thread_to_item(t, ME)
    assert [m.body for m in item.messages] == ["question"]
    assert "DRAFT" not in item.labels
    assert thread_to_item(thread(msg("m2", 2000, ME, part("text/plain", "x"),
                                     labels=["DRAFT"])), ME) is None


def test_ordering_oldest_first_and_updated_at_newest():
    t = thread(msg("m2", 2_000_000, "bob@example.com", part("text/plain", "second"),
                   subject="Re: Kickoff", labels=["INBOX", "UNREAD"]),
               msg("m1", 1_000_000, "alice@example.com", part("text/plain", "first"),
                   subject="Kickoff", labels=["INBOX", "IMPORTANT"]))
    item = thread_to_item(t, ME)
    assert [m.body for m in item.messages] == ["first", "second"]
    assert item.subject == "Kickoff"
    assert item.updated_at == item.messages[-1].sent_at == "1970-01-01T00:33:20Z"
    assert item.labels == ["INBOX", "IMPORTANT", "UNREAD"]
    assert item.participants[0] == "alice@example.com"


def test_truncation():
    text = "x" * (BODY_CAP + 500)
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", part("text/plain", text))), ME)
    body = item.messages[0].body
    assert body.endswith("[truncated]")
    assert body.count("x") == BODY_CAP


def test_charset_latin1():
    text = "Café at 3? ¡Sí!"
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com",
                                     part("text/plain", text, "iso-8859-1"))), ME)
    assert item.messages[0].body == text


def test_unknown_charset_falls_back_to_utf8():
    p = part("text/plain", "plain ascii")
    p["headers"] = [{"name": "Content-Type", "value": "text/plain; charset=x-bogus"}]
    item = thread_to_item(thread(msg("m1", 1000, "alice@example.com", p)), ME)
    assert item.messages[0].body == "plain ascii"


def test_mislabeled_utf8_decodes_as_utf8():
    from frontdesk.gmail.normalize import _decode
    raw = "AI to 10× yourself, you’ve".encode()
    part = {"headers": [{"name": "Content-Type", "value": 'text/plain; charset="iso-8859-1"'}],
            "body": {"data": base64.urlsafe_b64encode(raw).decode()}}
    assert _decode(part) == "AI to 10× yourself, you’ve"


def test_real_latin1_reads_as_cp1252():
    from frontdesk.gmail.normalize import _decode
    raw = "café ’".encode("cp1252")
    part = {"headers": [{"name": "Content-Type", "value": "text/plain; charset=iso-8859-1"}],
            "body": {"data": base64.urlsafe_b64encode(raw).decode()}}
    assert _decode(part) == "café ’"


def test_clean_html_trims_gmail_quote():
    from frontdesk.gmail.normalize import clean_html
    html = '<div>New reply</div><div class="gmail_quote">On Mon, Bob wrote: old</div>'
    payload = {"mimeType": "text/html", "headers": [],
               "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()}}
    out = clean_html(payload)
    assert "New reply" in out and "old" not in out


def test_cid_image_becomes_data_uri():
    from frontdesk.gmail.normalize import clean_html
    html = '<p>Hi</p><img src="cid:logo123@x">'
    img = base64.urlsafe_b64encode(b"\x89PNG-bytes").decode()
    payload = {"mimeType": "multipart/related", "headers": [], "parts": [
        {"mimeType": "text/html", "headers": [],
         "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()}},
        {"mimeType": "image/png", "filename": "logo.png",
         "headers": [{"name": "Content-ID", "value": "<logo123@x>"}], "body": {"data": img}}]}
    out = clean_html(payload)
    assert 'src="data:image/png;base64,' in out and "cid:" not in out


def test_stub_plain_part_falls_back_to_the_html():
    html = ("<html><body><h1>Personal brief</h1><p>Today: call with Gee at 9am. Invoice from "
            "the landlord is due Friday. Two recruiter replies are waiting.</p>"
            + "<ul>" + "".join(f"<li>Item {i}: follow up on the open thread.</li>" for i in range(8))
            + "</ul></body></html>")
    t = thread(msg("m1", 1000, "Me <owner@example.com>",
                   alternative("This message is HTML; open it in a mail client that renders HTML.",
                               html)))
    body = thread_to_item(t, ME).messages[0].body
    assert "call with Gee at 9am" in body and "This message is HTML" not in body


def test_a_real_plain_part_still_wins_over_similar_html():
    t = thread(msg("m1", 1000, "Ann <ann@example.com>",
                   alternative("Lunch at noon? Plain version.", "<p>Lunch at noon? <b>HTML</b> version.</p>")))
    assert thread_to_item(t, ME).messages[0].body == "Lunch at noon? Plain version."
