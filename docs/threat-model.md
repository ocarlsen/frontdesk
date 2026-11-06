# Threat model and data handling

The design assumes **inbound mail is hostile**: anyone can email you, and the text is read by a model.

| Layer | What it enforces |
|---|---|
| Gmail scope | Sync uses `gmail.readonly`. Actions use a separate `gmail.modify` token, loaded only by the action path; the model has no access to it. |
| Prompt | Mail is passed as JSON inside `<untrusted_thread>`, with `<` escaped so a body cannot close the tag. The instructions say embedded instructions are signals about the sender, not commands. |
| Output | A fixed JSON schema, re-validated in code. A proposed reply is forced empty unless the thread is `needs_you`. The model has no tools. |
| Rendering | Email HTML is served from its own route under a CSP with no script, no remote loads (tracking pixels stay blocked) until you click Show images for that message or choose to always show a sender's images (https only, no referrer), no forms, `<meta http-equiv>` stripped, inside a sandboxed iframe without `allow-scripts`. All other text is rendered with `textContent`. |
| Network | Binds `127.0.0.1` by default. Every request must carry a `Host` of localhost, an IP literal or a configured name (blocks DNS rebinding). Binding beyond loopback requires a random token (HttpOnly, SameSite=Strict cookie that lasts 90 days, Secure behind an https proxy). POST requires a custom header and a same-host `Origin`. Google's redirect to `/oauth/callback` is the one route that takes no cookie (the redirect is cross-site, so the browser withholds it): it needs a single-use `state`, valid 10 minutes, that FrontDesk issued to the signed-in page, and PKCE ties the code to this server. A token granted with other scopes than asked, or without a refresh token, is refused. |

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
- **Sent off the machine:** the text of each thread, with your profile and up to 2,500 characters
  of What's going on, to the model vendor you configure (Ask also sends your notes on that
  thread's people, your other threads with them and the Ask conversation); and the
  searches you run against all of Gmail, to Google (results are shown, never stored or sent to a
  model). Nothing else. Message HTML is never sent to the model. FrontDesk has no server and no telemetry.
- The model API key is read at call time from the vendor's environment variable
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`) or, on macOS, its Keychain item
  (`frontdesk-anthropic`, `frontdesk-openai`, `frontdesk-gemini`). It is never written to disk by
  FrontDesk.
