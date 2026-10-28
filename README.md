# FrontDesk

A local-first inbox agent. It reads your mail, ranks what actually needs you, explains why in one
line, and has a reply drafted for the threads that want one, like walking into an agent session
that already has all the context.

![Ranked inbox: Needs you, FYI, Ignore](docs/screenshot-list.jpg)

## Try it in 30 seconds (no Google account, no API key, no network)

```
git clone https://github.com/ocarlsen/frontdesk && cd frontdesk
python3.12 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/frontdesk demo        # then open http://127.0.0.1:8766/index.html
```

The demo loads 20 synthetic threads (all `example.com`) through the **real** Gmail normalizer and
triage pipeline, with recorded model answers in place of live calls. It includes a phishing mail
and two prompt-injection attempts so you can see how they are handled:

![An injection attempt inside a real request: still ranked Needs you, reply drafted with placeholders](docs/screenshot-thread.jpg)

## What it does

- **Sync** your Gmail inbox with a read-only token.
- **Triage** each thread with the model you choose: `needs_you` / `fyi` / `ignore`, urgency 1 to 5,
  a one-line reason, and a proposed reply when one is warranted. Replies never invent facts: where
  only you know the answer they carry a placeholder like `[time that works]`.
- **Show** a ranked page with each thread rendered like Gmail (the mail's own HTML, safely
  sandboxed), copy-ready replies, and a Sync button.

FrontDesk does not send, archive or change mail yet. Those actions are designed (see Roadmap) and
will arrive behind separate, explicit permissions.

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
| Gmail scope | `gmail.readonly` only. The token cannot send, delete or modify, whatever the model says. |
| Prompt | Mail is passed as JSON inside `<untrusted_thread>`, with `<` escaped so a body cannot close the tag. The instructions say embedded instructions are signals about the sender, not commands. |
| Output | A fixed JSON schema, re-validated in code. A proposed reply is forced empty unless the thread is `needs_you`. The model has no tools. |
| Rendering | Email HTML is served from its own route under a CSP with no script, no remote loads (tracking pixels stay blocked), no forms, `<meta http-equiv>` stripped, inside a sandboxed iframe without `allow-scripts`. All other text is rendered with `textContent`. |
| Network | Binds `127.0.0.1` by default. Every request must carry a `Host` of localhost, an IP literal or a configured name (blocks DNS rebinding). Binding beyond loopback requires a random token (HttpOnly, SameSite=Strict cookie). POST requires a custom header and a same-host `Origin`. |

What this does **not** claim: prompt injection is not solved. These layers limit what a malicious
mail can achieve (it cannot act, exfiltrate through tools, or run code in the page), but it can
still try to sway a ranking or a draft. A measured red-team suite is on the roadmap.

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

1. **Measured quality:** a labeled synthetic eval set (headline metric: recall on `needs_you`,
   since a missed one is the costly error), a red-team suite of injection attempts with a published
   pass rate per model and prompt version, and cost and cache-hit numbers per run.
2. **Inspectable decisions:** each ranking shows why, which model and prompt version made it, and
   what it cost; any decision can be replayed against another model.
3. **Actions:** Archive, then Reply. A reply becomes a Gmail draft first; Send confirms the exact
   text and recipients (derived from the thread, never from the model), records the action before
   it happens so a double-click cannot send twice, refuses if a new message arrived, and holds for
   a short undo window. These use a separate token, so sync stays read-only.
4. **More sources and models:** Slack (your own internal app), a second model adapter with a
   parity test.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Security reports: see [SECURITY.md](SECURITY.md).
