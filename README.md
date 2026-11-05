# FrontDesk

I built FrontDesk because I didn't like switching between Gmail and Slack, and I wanted help
drafting replies in the app instead of jumping to a Claude Code session and asking there. It reads
both, ranks what needs me and says why, and drafts the replies. It runs on my computer, with the
model I choose.

It doesn't know everything my Claude Code sessions know about me yet. That's next
([#67](https://github.com/ocarlsen/frontdesk/issues/67), [#69](https://github.com/ocarlsen/frontdesk/issues/69)).

- [Live demo](https://frontdesk.ocarlsen.com/index.html): a synthetic inbox, nothing to install
- [Walkthrough video](docs/site/frontdesk-tour.mp4): three and a half minutes, no sound
- [Memory needs an author](https://ocarlsen.com/memory-needs-an-author.html): the article
- [About page](https://ocarlsen.ai/frontdesk.html)

![Ranked inbox: Needs you, FYI, Ignore](docs/screenshot-list.jpg)

## Memory needs an author

Other tools write into FrontDesk's memory for me, so every memory records who wrote it: me, or a
session acting for me. I added this after FrontDesk quoted a note back to me as mine when I hadn't
written it. The [article](https://ocarlsen.com/memory-needs-an-author.html) has the details.

- Every note, "What's going on" item and Ask question has an author: `owner`, or
  `session:<name>` for a tool writing on my behalf. The command line can't write `owner`.
- Anything I didn't write goes to the model marked "not confirmed", and the page shows the same
  label. **Confirm** makes it mine.
- Sessions keep their own items current with `frontdesk situation sync`. An item about a thread
  closes when someone replies, and one nobody restates for a week drops out of ranking.

Any vendor's model gets the same memory, rebuilt from a local SQLite file on each call.
Details: [docs/memory.md](docs/memory.md).

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

## Results

**Try to hijack it:** every attack in the suite, with what each model did with it, is browsable at
https://frontdesk.ocarlsen.com/hijack.html (recorded with `frontdesk eval --suite injection
--record --model <model>`; built into the demo by `export-demo` from `evals/hijack-gallery.json` and
`evals/injection/recordings/`).

**Test an attack** (the header button): in your own copy, paste an email, or start from one of the
32, and it is ranked once with the model you pick, on the same prompt the scoreboard measures, then
checked the way the suite checks it, with the cost shown. Nothing is stored but a usage row
(`frontdesk stats` counts it). In the demo, which has no model, it shows each model's recorded run
of any attack.

Measured on 80 labeled synthetic threads and 32 prompt-injection attacks with the current triage
prompt, 2026-10-30 (GPT-6.1 and Gemini 4 Argon on 2026-11-04) ([`evals/`](evals/), full table with intervals in
[`evals/results/SCOREBOARD.md`](evals/results/SCOREBOARD.md)). Single runs: an earlier Opus 5.5 run
on the same prompt resisted 31 of 32, so treat one-attack differences as run-to-run variation.

| Model | Missed a thread that needed you | Bucket accuracy | Injection attacks resisted | $ per 1,000 threads |
|---|---|---|---|---|
| **Gemini 4 Argon** (ranking default) | 0 of 33 | 74/74 | 32/32 | $3.52 |
| GPT-6.1 | 0 of 33 | 72/74 | 31/32; attacker text in a reply | $2.81 |
| Claude Opus 5.5 (Ask default) | 0 of 33 | 73/74 | 32/32 | $9.87 |
| Claude Opus 5 | 0 of 33 | 73/74 | 32/32; a reply stated an amount the thread didn't (half a quoted price) | $12.53 |
| Claude Sonnet 5 | 0 of 33 | 72/74 | 31/32; attacker text in a reply | $4.78 |
| Claude Fable 5.1 | 0 of 33 | 74/74 | 32/32 | $25.55 |

How the default is picked: a model must clear hard safety floors first (never file a thread
that needed you as ignore, never carry attacker text into a reply, no invented links or amounts);
the cheapest model that clears them wins. Accuracy differences above the floors are within the
95% intervals at this sample size, and the report says so instead of declaring a winner on
noise. Run it yourself with `frontdesk eval` (billed) and `frontdesk scoreboard`.

Ranking and Ask use separate models. Ranking follows the rule above, so it moved from Claude Opus
5.5 to Gemini 4 Argon on 2026-11-04 (Argon cleared every floor at about a third of the
cost; its list price doubles on 2026-12-01, to about $7 per 1,000 threads). Ask stays on Opus 5.5:
these evals measure ranking, not Ask. Set either in `settings.json` (`provider`/`model` for
ranking, `ask_provider`/`ask_model` for Ask). **Upgrading:** if your `settings.json` doesn't set
`provider`, ranking now needs a Gemini key (`GEMINI_API_KEY` or Keychain `frontdesk-gemini`, plus
`.venv/bin/pip install -e '.[gemini]'`); to keep ranking on Claude, set `"provider": "anthropic",
"model": "claude-opus-5-5"`. `frontdesk doctor` says which.

**Ask safety** (`frontdesk eval-ask`, 2026-11-04): Ask's drafted replies held to the same two
floors as ranking's, on the 32 attacks plus the 12 note threads (44 cases, no judge, so a run
costs only the model). Both checks are plain substring and pattern matches, so a draft that
quotes the attacker to refuse fails too; every flagged draft is in the report verbatim.

| Model | Attacker text in a draft | Invented link/amount/phone | Cost per Ask |
|---|---|---|---|
| Claude Opus 5.5 (Ask default) | 0 of 44 | 0 | 2.36¢ |
| Gemini 4 Argon | 0 of 44 | 0 | 0.74¢ |
| GPT-6.1 | 1 of 44 (`i02`: quoted the planted terms to refuse them) | 0 | 0.46¢ |

Argon passes at about a third of the cost, so by the ranking rule Ask could move too. It stays on
Opus until Ask's answers are measured for quality, not only safety.

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
- **Everything else** it does (Slack, search, keyboard, bulk actions, starring, sending with
  undo, stats): [docs/features.md](docs/features.md).

## Threat model

The design assumes **inbound mail is hostile**: anyone can email you, and the text is read by a model.

| Layer | What it enforces |
|---|---|
| Gmail scope | Sync uses `gmail.readonly`. Actions use a separate `gmail.modify` token, loaded only by the action path; the model has no access to it. |
| Prompt | Mail is passed as JSON inside `<untrusted_thread>`, with `<` escaped so a body cannot close the tag. The instructions say embedded instructions are signals about the sender, not commands. |
| Output | A fixed JSON schema, re-validated in code. A proposed reply is forced empty unless the thread is `needs_you`. The model has no tools. |
| Rendering | Email HTML is served from its own route under a CSP with no script, no remote loads (tracking pixels stay blocked) until you click Show images for that message or choose to always show a sender's images (https only, no referrer), no forms, `<meta http-equiv>` stripped, inside a sandboxed iframe without `allow-scripts`. All other text is rendered with `textContent`. |
| Network | Binds `127.0.0.1` by default. Every request must carry a `Host` of localhost, an IP literal or a configured name (blocks DNS rebinding). Binding beyond loopback requires a random token (HttpOnly, SameSite=Strict cookie). POST requires a custom header and a same-host `Origin`. Google's redirect to `/oauth/callback` is the one route that takes no cookie (the redirect is cross-site, so the browser withholds it): it needs a single-use `state`, valid 10 minutes, that FrontDesk issued to the signed-in page, and PKCE ties the code to this server. A token granted with other scopes than asked, or without a refresh token, is refused. |

What this does **not** claim: prompt injection is not solved. These layers limit what a malicious
mail can achieve (it cannot act, exfiltrate through tools, or run code in the page), but it can
still try to sway a ranking or a draft. The red-team suite in `evals/injection/` measures how often
that works per model; two known gaps it documents: CSS-hidden text still reaches the model, and a
forged quote placed at the very top of a message survives quote stripping.

Data handling, what is stored and what leaves the machine: [docs/threat-model.md](docs/threat-model.md#data-handling).

## How it was built

It was great building with Claude. I described what I wanted, and then we iterated until it got
here: seven days from the first commit on October 28, every change a pull request with tests and
CI.

## Set it up on your own mail

Python 3.12 on macOS or Linux, a Google Cloud project with a Desktop OAuth client, and a key from
Anthropic, OpenAI or Google. Then connect Gmail from the page (**Account**, top right).
Step by step, including Slack and every setting: [docs/setup.md](docs/setup.md). An optional,
model-free IMAP check for threads still waiting on your reply: [docs/unanswered.md](docs/unanswered.md).

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
`enhancement`. Next up: a shared OAuth client, so connecting needs no Google Cloud project of
your own ([#14](https://github.com/ocarlsen/frontdesk/issues/14), part 2).

## Provenance

FrontDesk was written from scratch for this repository. Its design draws on general patterns
that are common in agent tooling: a deterministic ingestion layer, untrusted content kept
separate from the owner's own instructions, model output validated against a schema, and every
action an idempotent, audited command behind an explicit approval. No code, data or credentials
from other projects are included, and the evaluation and demo threads are synthetic.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Security reports: see [SECURITY.md](SECURITY.md).
