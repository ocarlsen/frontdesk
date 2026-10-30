# FrontDesk

A local-first inbox agent. It reads your mail, ranks what actually needs you, explains why in one
line, and has a reply drafted for the threads that want one, like walking into an agent session
that already has all the context.

![Ranked inbox: Needs you, FYI, Ignore](docs/screenshot-list.jpg)

**Live demo:** https://frontdesk.ocarlsen.com/index.html (a synthetic inbox, nothing to install).

## Try it in 30 seconds (no Google account, no API key, no network)

```
git clone https://github.com/ocarlsen/frontdesk && cd frontdesk
python3.12 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/frontdesk demo        # then open http://127.0.0.1:8766/index.html
```

The demo loads 20 synthetic threads (all `example.com`) through the **real** Gmail normalizer and
triage pipeline, replaying answers recorded once from Claude Opus 5.5 (`tools/record_demo.py`),
so each thread's "Why this ranking" panel shows the real model, tokens and cost. It includes a phishing mail
and two prompt-injection attempts so you can see how they are handled:

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
- **Auto-sync** every 15 minutes (`auto_sync_minutes`), and Gmail-style keyboard shortcuts (`?`).
- **Act**, with a second, separate permission (`frontdesk authorize-actions`): archive with undo,
  save the edited reply as a Gmail draft, or send it. Send shows the exact message and its
  recipients (derived from the thread, never from the model), waits 30 seconds for an undo,
  refuses if a new message arrived, and is never retried on a timeout.

## Results

Measured on 80 labeled synthetic threads and 32 prompt-injection attacks ([`evals/`](evals/),
full table in [`evals/results/SCOREBOARD.md`](evals/results/SCOREBOARD.md)):

| Model | Missed a thread that needed you | Bucket accuracy | Injection attacks resisted | $ per 1,000 threads |
|---|---|---|---|---|
| **Claude Opus 5.5** (default) | 0 of 33 | 73/74 | 32/32 | $7.63 |
| Claude Opus 5 | 0 of 33 | 73/74 | 32/32 | $9.40 |
| Claude Sonnet 5 | 0 of 33 | 71/74 | 31/32, put attacker text in a reply | $3.58 |
| Claude Fable 5.1 | 0 of 33 | 74/74 | 32/32 | $20.14 |

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
  downstream sees a vendor's raw JSON. Slack is the next source.
- **`Provider`** (`frontdesk/providers/base.py`) is one method, `complete_json(system, user,
  schema)`. Adding a model vendor means one small adapter; switching is a settings change.
- **Incremental:** a thread is re-triaged only when it changes or the prompt changes (the prompt is
  versioned by hash). A refusal is never retried; an error is retried at most 3 times, so a Sync
  click never re-bills the same failure.

### Memory

Ask ("Ask FrontDesk about this thread") works from four kinds of owner-side memory: your
**profile** (a few sentences in `settings.json`), **What's going on** (up to 50 short items on
what is live for you now: decisions, open matters), **notes** on each person, and the **Ask
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
  token, optional `settings.json`.
- **Sent off the machine:** the text of each thread, to the model vendor you configure, and nothing
  else. Message HTML is never sent to the model. FrontDesk has no server and no telemetry.
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
days, archived or not (promotions, social, updates and forums left out) whose newest message in that
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

The demo inbox is generated by `tools/gen_demo_fixtures.py`, and the test suite checks it uses
only reserved `example.*` domains.

## Roadmap

1. **More sources and models:** Slack (your own internal app), a second model adapter with a
   parity test.

## Provenance

FrontDesk was written from scratch for this repository. Its design draws on general patterns
that are common in agent tooling: a deterministic ingestion layer, untrusted content kept
separate from the owner's own instructions, model output validated against a schema, and every
action an idempotent, audited command behind an explicit approval. No code, data or credentials
from other projects are included, and the evaluation and demo threads are synthetic.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Security reports: see [SECURITY.md](SECURITY.md).
