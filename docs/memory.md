# Memory and cost

How owner-side memory works, who wrote each line, and what context costs per ranking. The idea behind it: [Memory needs an author](https://ocarlsen.com/memory-needs-an-author.html).


Ask ("Ask FrontDesk about this thread") works from four kinds of owner-side memory: your
**profile** (a few sentences in `settings.json`), **What's going on** (up to 50 short items on
what is live for you now: decisions, open matters), a **note** on each person, and the **Ask
history** of each thread. All of it is local SQLite (the profile is local settings), assembled
into every call; the model keeps no state between calls, so any vendor's model gets the same
context.

Ranking reads your profile and What's going on too, never notes. It reads your own items first,
then everyone else's, newest first, whole items only, up to 2,500 characters
(`SITUATION_RANK_CHARS` in `frontdesk/triage.py`), so the cost of a ranking has a ceiling however
many items or sessions there are. Changing What's going on does not re-rank threads already
ranked: sessions restate it often, and re-ranking the whole inbox each time would re-bill every
thread. It applies to new and changed threads, and to all of them when the profile changes.

**Keeping it current.** A session that tracks what you are waiting on restates its full list
with `frontdesk situation sync --by NAME`, one item per line on stdin. Its items not in the new
list are removed, ones still there are kept, and new ones are added, so a closed matter drops out
when the session next syncs. A sync touches only items that session wrote: yours, other
sessions', and any you confirmed stay. An empty list is refused unless you pass `--clear`, so a
failed command piped into it cannot wipe the list.

**Items that close themselves.** An item about one thread can be linked to it:
`frontdesk situation add TEXT --by NAME --thread ID`, or a sync line starting `thread:ID ` (the
thread must be one FrontDesk has stored). It closes when someone other than you writes in that
thread, or you mark the thread done or archive it in FrontDesk; your own reply leaves it open.
Closed items are kept, marked on the page with the reason, and left out of Ask and ranking;
**Reopen** puts one back, and it then waits for a newer reply. Undoing a done or an archive
reopens what it closed. A thread that leaves FrontDesk another way (it ages out of the sync
window, or you archive it in Gmail) cannot close its item, and the page says so.

**Stale items.** A session's item not restated or edited for 7 days
(`SITUATION_STALE_DAYS`) is marked stale on the page and left out of ranking; Ask still reads it,
labelled unconfirmed. **Confirm** makes it yours, and your own items never go stale. A session
that syncs regularly keeps its items fresh.

Every note, What's going on item and Ask question records its author: `owner` when you typed or
clicked it in the page (a model's suggestion counts as yours once you click it), `session:<name>`
when a tool or agent session wrote it on your behalf (`frontdesk note WHO TEXT --by NAME`,
`frontdesk situation add TEXT --by NAME`, `frontdesk situation sync --by NAME`; this path can
never write `owner`), or `unrecorded` for
rows from before authors were recorded. Only `owner` counts as confirmed: the prompt labels every
other line "not confirmed", and the model is told to say so when it relies on one instead of
writing "you said". The page shows who wrote each item, and **Confirm** (or editing and saving)
makes it yours.

A **person** owns any number of addresses (Gmail addresses; on Slack, the user's stable ID, so a
renamed colleague keeps their note and two people with one name stay apart) and one note, so Ask
finds the note through whichever address a thread uses. A person has a name only when you type
one: the display name in a From header is written by the sender, so the Memory page shows it
greyed as "from mail, unconfirmed" and it never enters the prompt. Ask's notes block
lists a person as their addresses, the name only if you typed it, then the same author and date
label, e.g. `fab@example.com, f@example.org (written by the owner, 2026-10-28): Pre-seed, no pay.`
Slack display names, like From names, are the other person's text: the page shows them, the
notes block lists Slack people by ID only. Notes saved before Slack IDs were keyed by display
name; each sync links such a name to the one Slack user it belongs to, and the Memory page marks
any it cannot link (a name two users share, or one not seen since) as "Slack name, not linked to
a user". Your own address is never a person: on Gmail that is the mailbox, on Slack your own user
ID, learnt at each sync.

**Memory** (header button, or `m`; `Esc` closes) lists everything kept: your profile, What's going
on, then people, newest first, each with addresses, name, note, author and date. Edit there; only
you can **Confirm**, **Delete** or **Merge into...** another person (merge asks first and cannot be
undone; the merged note is yours only if both notes were). **Download my memory** saves it all as
JSON. In an open thread, the **People** strip under the subject has a chip per person ("· note"
or "· add note") that opens their note in place. Sessions can add a note or append to one, never
delete, merge, confirm, name, or replace a note you wrote; saving empty text is refused rather
than deleting. Ask's "Save note for ..." suggestions save only when the person they name is in
that thread, so model output never creates a person. The demo shows Memory empty and read-only.

Older databases are migrated once on open (under a write lock, so two FrontDesk processes cannot
copy twice): each per-address note becomes a person with that address, keeping its text, author
and date. A note on your own address is left out and listed on the Memory page. The old `notes`
table stays read-only for one release.

This is a record for honest writers, not a security boundary: any process on your machine can
open the database or call the local API and claim any author.

## Cost

You pay the model vendor directly; FrontDesk has no server. On my own inbox with Claude Opus 5.5,
a ranking costs about 1.5¢ per thread and an Ask about 3¢. The [Results](../README.md#results) table gives the
cost per 1,000 threads for each model. `frontdesk stats` shows what yours cost, by model, and each
ranking's "Why this ranking" panel shows its own tokens and cost. Prices are list prices in
`frontdesk/pricing.py`, with their sources and dates; a model not listed there shows no cost
rather than a guess.

Context added to a ranking is paid on every thread, so it is bounded: What's going on is capped
at 2,500 characters per ranking (about 600 input tokens; at most about 0.25¢ more per thread with
Opus 5.5 at the full budget), and notes are never sent to ranking. Prompt caching is off for
Anthropic today: the part of the prompt shared across threads is below the minimum size Anthropic
caches, so every call paid the cache-write premium and none read it back. It will be re-measured
as the shared part grows.
