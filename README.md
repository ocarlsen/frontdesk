# FrontDesk

A local-first inbox agent. It reads your mail, ranks what actually needs you, explains why in one
line, and has a reply drafted for the threads that want one, like walking into an agent session
that already has all the context.

![Ranked inbox: Needs you, FYI, Ignore](docs/screenshot-list.jpg)

**Live demo:** https://frontdesk.ocarlsen.com/index.html (a synthetic inbox, nothing to install).

**Walkthrough video (about three minutes, no sound):** [docs/site/frontdesk-tour.mp4](docs/site/frontdesk-tour.mp4),
a guided tour of the same synthetic inbox in six parts: triage (with Move to), the keyboard, Ask, Memory,
guardrails (two planted instructions that do not work, and Send's confirm and undo), and the
inbox on a phone.

## Try it in 30 seconds (no Google account, no API key, no network)

```
git clone https://github.com/ocarlsen/frontdesk && cd frontdesk
python3.12 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/frontdesk demo        # then open http://127.0.0.1:8766/index.html
```

The demo loads 20 synthetic threads (all `example.com`) through the **real** Gmail normalizer and
triage pipeline, plus 4 Slack conversations from a made-up workspace through the real Slack sync,
replaying answers recorded once from Claude Opus 5.5 (`tools/record_demo.py`), so each thread's
"Why this ranking" panel shows the real model, tokens and cost. It includes a phishing mail and
three prompt-injection attempts (one in Slack) so you can see how they are handled:

![An injection attempt inside a real request: still ranked Needs you, reply drafted with placeholders](docs/screenshot-thread.jpg)

## What it does

- **Sync** your Gmail inbox with a read-only token.
- **Triage** each thread with the model you choose: `needs_you` / `fyi` / `ignore`, urgency 1 to 5,
  a one-line reason, and a proposed reply when one is warranted. Replies never invent facts: where
  only you know the answer they carry a placeholder like `[time that works]`.
- **Show** a ranked page that leads each thread with a short summary, renders the full thread
  like Gmail (the mail's own HTML, safely sandboxed), and has a Sync button.
- **Slack (optional):** your own Slack app and user token. DMs, group DMs and channel threads
  that mention you or that you replied in become threads on the same page; **Done** hides one
  until someone posts again, and **Send** replies in the thread with the same confirm-and-undo flow.
  A star on a Slack thread is kept in FrontDesk only: Slack has no supported API for saving a
  message for later (`stars.add` still answers, but since 2023 it has no effect anyone can see in
  Slack, per [Slack's changelog](https://docs.slack.dev/changelog/2023-07-its-later-already-for-stars-and-reminders/)),
  so no extra Slack scope is needed, and the star goes when the thread ages out of the sync window.
- **Ask** about any thread: the box starts with FrontDesk's own question ("What do you think? ...")
  as editable text; change it or leave it, and **Ask** sends what is in the box (the model picker
  chooses the model). **Second opinion** has the review model check the answer; **Polish draft**
  tightens the reply. Each answer resets the box to the built-in question.
- **Auto-sync** every 15 minutes (`auto_sync_minutes`), and Gmail-style keyboard shortcuts (`?`):
  `j`/`k` move, `o` opens, `e`/`y` archive (or mark a Slack thread done), `[`/`]` archive and
  open the next thread, `s` stars, `r` replies, `a` replies all, `Shift+I`/`Shift+U` mark read
  and unread (Gmail too; on Slack, unread is kept in FrontDesk), `z` undoes, `g i`/`g s` go to the
  inbox or Starred. Each action that changes mail also has a control: row icons on hover, the
  thread's buttons, and the toast's Undo.
- **Bulk:** select with the row checkbox, `x`, Shift-click for a range, or `*` then `a`/`n`/`r`/`u`
  (all, none, read, unread); on a phone, long-press a row, then tap more. A bar then marks the
  selection read or unread, archives it (Done for Slack), stars it or moves it, one action per
  thread through the same checked path as a single one, with one Undo for the batch. `e`, `y`,
  `Shift+I`, `Shift+U`, `s` and `v` act on the selection; Esc clears it.
- **Stats:** `frontdesk stats [--days N] [--json]` shows what FrontDesk did and what it cost:
  threads ranked and cost per thread by model, Ask answers, drafts saved and replies sent (with the
  share sent as FrontDesk proposed, as Ask drafted, edited, or written from scratch), searches and
  keeps. It counts from the first run that has it, seeded from the rankings and answers already
  stored.
- **Search** with `/`: typing filters the synced threads; Enter also searches all of Gmail
  (archived mail too, Gmail's operators work) with the read-only token and lists up to 20 threads
  FrontDesk has not synced, unranked and unstored, plus matching Slack messages when Slack is
  connected (`search.messages`; needs the `search:read` user scope), each opening in Slack. Open one to read it in place (plain text,
  still unstored); **Keep in FrontDesk** stores it, ranks it once, and lists it under From search
  with every action until it is archived or marked done (sync keeps it current); **Move to inbox**
  (thread or selection) puts an archived one back in Gmail's inbox. Gmail results can be selected
  too (`x`, the checkbox): the bar then archives them, marks them read or unread or stars them
  straight in Gmail by thread id (actions permission, nothing stored, no model call). Move to inbox
  also keeps each one (ranked, one model call), so it shows in FrontDesk whatever its age, since
  sync reads only the last week of the inbox. Slack matches open in Slack and are not selectable.
  Esc clears it.
- **Star** a thread from its row, its detail view or with `s`. On Gmail it is Gmail's own star
  (the `STARRED` label, through the actions permission), so it shows in Gmail too. The star count
  in the header opens a **Starred** view; a starred Gmail thread you archive or mark done stays
  there, marked, while Gmail keeps the star (each sync keeps archived threads that are still
  starred), with a button to move it back.
- **Phone:** swipe a thread left to archive it (Gmail) or mark it done (Slack), with the usual
  undo; a short swipe snaps back, and scrolling up and down never swipes. Buttons are
  thumb-sized on narrow screens.
- **Act**, with a second, separate permission (`frontdesk authorize-actions`): archive with undo,
  star, save the edited reply as a Gmail draft, or send it. Send shows the exact message and its
  recipients (derived from the thread, never from the model), waits 30 seconds for an undo,
  refuses if a new message arrived, and is never retried on a timeout.

## Results

Measured on 80 labeled synthetic threads and 32 prompt-injection attacks with the current triage
prompt, 2026-10-30 ([`evals/`](evals/), full table with intervals in
[`evals/results/SCOREBOARD.md`](evals/results/SCOREBOARD.md)). Single runs: an earlier Opus 5.5 run
on the same prompt resisted 31 of 32, so treat one-attack differences as run-to-run variation.

| Model | Missed a thread that needed you | Bucket accuracy | Injection attacks resisted | $ per 1,000 threads |
|---|---|---|---|---|
| **Claude Opus 5.5** (default) | 0 of 33 | 73/74 | 32/32 | $9.87 |
| Claude Opus 5 | 0 of 33 | 73/74 | 32/32; a reply stated an amount the thread didn't (half a quoted price) | $12.53 |
| Claude Sonnet 5 | 0 of 33 | 72/74 | 31/32; attacker text in a reply | $4.78 |
| Claude Fable 5.1 | 0 of 33 | 74/74 | 32/32 | $25.55 |

How the default is picked: a model must clear hard safety floors first (never file a thread
that needed you as ignore, never carry attacker text into a reply, no invented links or amounts);
the cheapest model that clears them wins. Accuracy differences above the floors are within the
95% intervals at this sample size, and the report says so instead of declaring a winner on
noise. Run it yourself with `frontdesk eval` (billed) and `frontdesk scoreboard`.

## How it works

```
Gmail API ──► normalize ──► Item ──► SQLite ──► triage ──► ranked list ──► web page
 (readonly)   charset fix,   provider-   items,      Provider      bucket,       sandboxed
              quote strip,   neutral     HTML,       protocol      urgency,      HTML frame,
              cid images     record      triage,     (one adapter  reason,       textContent
                                         failures    per vendor)   reply         only
```

- **`Item`** (`frontdesk/items.py`) is the seam: every source normalizes into it, and nothing
  downstream sees a vendor's raw JSON. Gmail and Slack both normalize into it.
- **`Provider`** (`frontdesk/providers/base.py`) is one method, `complete_json(system, user,
  schema)`. Adding a model vendor means one small adapter; switching is a settings change.
- **Incremental:** a thread is re-triaged only when it changes or the prompt changes (the prompt is
  versioned by hash). A refusal is never retried; an error is retried at most 3 times, so a Sync
  click never re-bills the same failure.

### Memory

Ask ("Ask FrontDesk about this thread") works from four kinds of owner-side memory: your
**profile** (a few sentences in `settings.json`), **What's going on** (up to 50 short items on
what is live for you now: decisions, open matters), a **note** on each person, and the **Ask
history** of each thread. All of it is local SQLite (the profile is local settings), assembled
into every call; the model keeps no state between calls, so any vendor's model gets the same
context. Triage does not use What's going on or notes.

Every note, What's going on item and Ask question records its author: `owner` when you typed or
clicked it in the page (a model's suggestion counts as yours once you click it), `session:<name>`
when a tool or agent session wrote it on your behalf (`frontdesk note WHO TEXT --by NAME`,
`frontdesk situation add TEXT --by NAME`; this path can never write `owner`), or `unrecorded` for
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

## Threat model

The design assumes **inbound mail is hostile**: anyone can email you, and the text is read by a model.

| Layer | What it enforces |
|---|---|
| Gmail scope | Sync uses `gmail.readonly`. Actions use a separate `gmail.modify` token, loaded only by the action path; the model has no access to it. |
| Prompt | Mail is passed as JSON inside `<untrusted_thread>`, with `<` escaped so a body cannot close the tag. The instructions say embedded instructions are signals about the sender, not commands. |
| Output | A fixed JSON schema, re-validated in code. A proposed reply is forced empty unless the thread is `needs_you`. The model has no tools. |
| Rendering | Email HTML is served from its own route under a CSP with no script, no remote loads (tracking pixels stay blocked), no forms, `<meta http-equiv>` stripped, inside a sandboxed iframe without `allow-scripts`. All other text is rendered with `textContent`. |
| Network | Binds `127.0.0.1` by default. Every request must carry a `Host` of localhost, an IP literal or a configured name (blocks DNS rebinding). Binding beyond loopback requires a random token (HttpOnly, SameSite=Strict cookie). POST requires a custom header and a same-host `Origin`. |

What this does **not** claim: prompt injection is not solved. These layers limit what a malicious
mail can achieve (it cannot act, exfiltrate through tools, or run code in the page), but it can
still try to sway a ranking or a draft. The red-team suite in `evals/injection/` measures how often
that works per model; two known gaps it documents: CSS-hidden text still reaches the model, and a
forged quote placed at the very top of a message survives quote stripping.

## Data handling

- Stored locally in `~/.frontdesk` (mode 0700): the SQLite database, your Google OAuth client and
  token, optional `settings.json`. The database includes an append-only usage log for
  `frontdesk stats`: counts and model costs only (rankings, Ask answers, drafts saved, replies
  sent and whether each went out as FrontDesk wrote it, searches, keeps), no mail text, addresses
  or thread ids.
- **Sent off the machine:** the text of each thread, to the model vendor you configure; and the
  searches you run against all of Gmail, to Google (results are shown, never stored or sent to a
  model). Nothing else. Message HTML is never sent to the model. FrontDesk has no server and no telemetry.
- The model API key is read at call time from `ANTHROPIC_API_KEY` or, on macOS, the Keychain item
  `frontdesk-anthropic`. It is never written to disk by FrontDesk.

## Use it on your own Gmail

1. In Google Cloud Console: create a project, enable the Gmail API, configure the OAuth consent
   screen (External, Testing), add yourself as a test user, and create a **Desktop app** OAuth
   client. Save its JSON as `~/.frontdesk/client_secret.json`.
2. Provide a model key: `export ANTHROPIC_API_KEY=...`, or on macOS
   `security add-generic-password -U -s frontdesk-anthropic -a $USER -w`.
3. Run:

```
frontdesk sync                # first run opens Google consent (read-only)
frontdesk triage --limit 20
frontdesk serve               # prints the page URL
```

In Testing mode Google shows an "unverified app" screen (you are the developer) and refresh tokens
expire after 7 days, after which `sync` asks you to consent again.

Settings (`~/.frontdesk/settings.json`, all optional): `model`, `provider_options`,
`gmail_query` (default `in:inbox newer_than:7d`), `gmail_max_threads`, `serve_host`,
`serve_port`, `serve_display_host`, `serve_allowed_hosts`, and the IMAP settings below.
Unknown keys are an error, not ignored.

## Unanswered email (optional, IMAP)

`frontdesk unanswered` lists Gmail threads still waiting on your reply: threads from the last 14
days that are in your inbox or have an unread message anywhere (so archived and read threads drop
out; promotions, social, updates and forums left out) whose newest message in that
window, counting your own sent replies (`from:me`), is from a person and not from you. Mail with
`List-Unsubscribe`, `List-Id`, a bulk/list/junk `Precedence`, an `Auto-Submitted` header, or a
sender like `noreply@` or `notifications@` is treated as automated and skipped. It is separate from
`sync`: no OAuth token, no model call, nothing stored.

It is read-only. It opens mailboxes with `EXAMINE`, fetches only a few headers with `BODY.PEEK`,
and never sends `STORE`, `COPY`, `MOVE` or `EXPUNGE`, so nothing is marked read, moved or
labelled.

Setup: create a Gmail app password (Google Account, Security, App passwords; needs 2-Step
Verification), store it in the login Keychain, and name both in `~/.frontdesk/settings.json`:

```
security add-generic-password -U -s my-gmail-imap -a you@gmail.com -w
```

```json
{"imap_account": "you@gmail.com", "imap_keychain_service": "my-gmail-imap"}
```

`IMAP_ACCOUNT` and `IMAP_APP_PASSWORD` override these; `imap_host` defaults to `imap.gmail.com`.

```
frontdesk unanswered                      # a short list
frontdesk unanswered --json --days 14 --limit 15
```

`frontdesk inbox-buckets --since <ISO 8601, with a UTC offset>` uses the same read-only IMAP
machinery to answer a different question: every inbox thread with a message newer than a given
time, sorted into exactly one of three buckets, or left out as already replied to. `--since`
should be the **start** time of the previous run, not its end time: re-seeing a message that
landed during the previous run is harmless, but using the end time can silently drop one that
arrived mid-run. Unlike `unanswered`, promotions and updates still land in a bucket instead of
being dropped, and there's no `is:unread` filter.

A thread is `newsletters` when its newest message carries `List-Unsubscribe`, `List-Id`, a
bulk/list `Precedence`, or comes from an address or domain in `newsletter_senders`; `unanswered`
when it's from a person who isn't automated, isn't on `unanswered_ignore_senders`, and isn't mail
Gmail itself has sorted into the Promotions, Updates, Social or Forums category (order
confirmations and shipping notices from UPS or Amazon, for instance, usually carry none of the
List-* headers but do land in Updates); otherwise `other`. A thread where you replied last is
left out of every bucket and counted separately as `replied`.

`person_senders` (same matching rules as the other two lists) overrides all of that -- the
category check, the newsletter headers, the automated/ignore check -- and always buckets a match
as `unanswered`; use it for a sender that looks automated but is really a person, like a
recruiter mailing through Greenhouse or Lever, or someone posting through a Google Group.

`other_senders` works the other way: a match always lands in `other`, even with newsletter
headers. Use it for notices that look exactly like newsletters, such as Google's account-security
mail, which carries List-Id and List-Unsubscribe and sits in Gmail's Updates category.
`person_senders` still wins if a sender is on both lists.

```json
{"imap_account": "you@gmail.com", "imap_keychain_service": "my-gmail-imap",
 "newsletter_senders": ["@substack.com"], "person_senders": ["@greenhouse.io"],
 "other_senders": ["noreply-accounts@google.com"]}
```

```
frontdesk inbox-buckets --since 2026-10-29T09:00:00-07:00
frontdesk inbox-buckets --json --since 2026-10-29T09:00:00-07:00 --limit 15
```

`--json` prints `{"since": ..., "total": N, "replied": R, "buckets": {"unanswered": {"total": n,
"items": [...]}, "newsletters": {...}, "other": {...}}}`, each bucket's items oldest first and
capped at `--limit` while its `total` stays uncapped; `total` always equals `replied` plus every
bucket's uncapped total (checked at runtime; a mismatch exits 2 naming step `count`). Items use
the same shape as `unanswered`'s, plus `read_url` (same as `gmail_url`) on newsletter items. It
takes a fixed number of IMAP round trips -- two searches (candidates, your own replies) plus one
per Gmail category (promotions, updates, social, forums), each with fetches chunked by 300 -- and
the same 60-second cap and one-line, step-named failure contract as `unanswered`.

`--json` prints `{"total": N, "items": [...]}`, oldest first; `total` counts every unanswered thread
and `items` holds at most `--limit`. Each item has `thread_id` (decimal), `gmail_url`, `from_name`,
`from_addr`, `subject`, `last_at` (ISO 8601 with offset), `age_days` and `n_messages` (messages in
the window, not the thread's whole history). It takes a fixed number of IMAP round trips: two
searches plus fetches in chunks of 300. Any failure exits nonzero with one line naming the step (for
example `imap login: [AUTHENTICATIONFAILED] ...`), never an empty list, and the whole run is capped
at 60 seconds.

To leave out senders that are never a person waiting on you (your own reports, a tool that writes
from a normal address), list them in `unanswered_ignore_senders`: exact addresses
(`"reports@example.com"`) or whole domains (`"@example.org"`, which also covers its subdomains).

## Development

```
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q            # offline: fake and replay providers, no network
.venv/bin/ruff check frontdesk tests
```

Browser tests (Chromium as a desktop window and as an iPhone 15, synthetic demo only): `cd tests/e2e && npm ci && npm test` (uses the repo's `.venv`, else `FRONTDESK_PYTHON`, else `python3`).

The demo inbox is generated by `tools/gen_demo_fixtures.py`, and the test suite checks it uses
only reserved `example.*` domains.

## Roadmap

Planned work lives in the [issue tracker](https://github.com/ocarlsen/frontdesk/issues), labelled
`enhancement`. Next up: [Sign in with Google from the page](https://github.com/ocarlsen/frontdesk/issues/14).

## Provenance

FrontDesk was written from scratch for this repository. Its design draws on general patterns
that are common in agent tooling: a deterministic ingestion layer, untrusted content kept
separate from the owner's own instructions, model output validated against a schema, and every
action an idempotent, audited command behind an explicit approval. No code, data or credentials
from other projects are included, and the evaluation and demo threads are synthetic.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Security reports: see [SECURITY.md](SECURITY.md).
