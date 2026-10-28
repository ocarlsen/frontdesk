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
`serve_port`, `serve_display_host`, `serve_allowed_hosts`. Unknown keys are an error, not ignored.

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

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Security reports: see [SECURITY.md](SECURITY.md).
