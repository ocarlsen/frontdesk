"""Ask's <owner_notes> block stays bounded in a busy thread: most recent senders first, at most
NOTES_MAX_PEOPLE lines and NOTES_MAX_CHARS characters, and one line saying how many were left out."""
from __future__ import annotations

from frontdesk import assist
from frontdesk.items import Item, Message
from frontdesk.store import Store

ME = "owner@example.com"


def thread(s: Store, n_people: int, senders: list[int], note_len: int = 40) -> Item:
    people = [f"p{i}@example.com" for i in range(n_people)]
    for i, a in enumerate(people):
        s.save_note(a, f"note {i} " + "x" * note_len, "owner")
    msgs = [Message(f"P{i} <p{i}@example.com>", f"2026-10-30T1{k}:00:00Z", "hi")
            for k, i in enumerate(senders)]
    s.upsert_item(Item(id="gmail:busy", source="gmail", account=ME, subject="Busy",
                       participants=[ME, *people], updated_at="2026-10-30T19:00:00Z", messages=msgs))
    return s.get_item("gmail:busy")


def test_small_thread_is_unchanged(tmp_path):
    s = Store(tmp_path / "a.db")
    lines = assist.note_lines(s, thread(s, 3, [0]))
    assert len(lines) == 3 and not any("left out" in ln for ln in lines)


def test_most_recent_senders_first_then_the_rest(tmp_path):
    s = Store(tmp_path / "a.db")
    lines = assist.note_lines(s, thread(s, 4, [1, 3, 2]))   # p2 wrote last, then p3, then p1
    assert [ln.split()[0].rstrip(",") for ln in lines] == [
        "p2@example.com", "p3@example.com", "p1@example.com", "p0@example.com"]


def test_capped_by_count_with_a_left_out_line(tmp_path):
    s = Store(tmp_path / "a.db")
    n = assist.NOTES_MAX_PEOPLE + 5
    lines = assist.note_lines(s, thread(s, n, [n - 1]))
    assert len(lines) == assist.NOTES_MAX_PEOPLE + 1
    assert lines[0].startswith(f"p{n - 1}@example.com")      # the latest sender survives the cap
    assert "5 more people" in lines[-1]


def test_capped_by_characters(tmp_path):
    s = Store(tmp_path / "a.db")
    lines = assist.note_lines(s, thread(s, 6, [0], note_len=1900))
    kept = lines[:-1]
    assert sum(len(ln) for ln in kept) <= assist.NOTES_MAX_CHARS
    assert len(kept) == 3 and "3 more people" in lines[-1]


def test_the_prompt_carries_the_bounded_block(tmp_path):
    s = Store(tmp_path / "a.db")
    item = thread(s, 30, [0], note_len=1900)
    prompt = assist.build_prompt(s, item, "What now?", "", author="owner")
    block = prompt.split("<owner_notes>")[1].split("</owner_notes>")[0]
    assert len(block) < assist.NOTES_MAX_CHARS + 400
