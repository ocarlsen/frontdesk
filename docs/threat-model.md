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

## OWASP Top 10 for LLM Applications (2025)

Each item of the [OWASP Top 10 for LLM Applications, 2025 edition](https://genai.owasp.org/llm-top-10/)
(the current list), mapped to the layer above that handles it, or marked out of scope with the reason.

| OWASP item | Where FrontDesk handles it | Proof |
|---|---|---|
| LLM01:2025 Prompt Injection | Prompt, Output and Gmail scope layers: mail reaches the model as escaped JSON inside `<untrusted_thread>`, the only output is a schema re-validated in code, and the model has no tools and no Gmail token. Not solved: a mail can still sway a ranking or a draft (above). | `evals/injection/` (32 cases, 10 attack families); `tests/test_triage.py` (`test_untrusted_body_cannot_close_the_tag`); `tests/test_attack.py` |
| LLM02:2025 Sensitive Information Disclosure | Mail text goes only to the model vendor you configure (Data handling, below). Rendering layer: no remote loads until you click Show images, so a mail or a draft cannot leak through an image URL. The model has no tools to send anything, and a reply leaves only through the confirm-and-undo send flow. OpenAI calls set `store: false`. FrontDesk never writes the API key to disk, and a provider object never prints it. | `tests/test_web.py` (`test_msg_route_serves_html_under_strict_csp`, `test_remote_images_off_until_asked`); `tests/test_sending.py` (`test_only_the_send_module_can_send`); `tests/test_adapters.py` (`test_api_key_never_in_repr_or_str`) |
| LLM03:2025 Supply Chain | Partly. No model weights, plugins or downloaded models: models are the vendors' hosted APIs, called through their official SDKs. Four runtime dependencies (`anthropic`, `google-auth`, `google-auth-oauthlib`, `requests`; `openai` and `google-genai` optional), with minimum versions only: there is no lock file or hash pinning. | `pyproject.toml` |
| LLM04:2025 Data and Model Poisoning | No training or fine-tuning, so no training data to poison. The nearest risk is memory: a hostile mail steering Ask into suggesting a note. A suggested note or What's going on item is saved only when you click it, a note can only go to someone in that thread, and every memory line records who wrote it. | `frontdesk/actions.py` (`save_suggested_note`); `tests/test_people.py` (`test_suggestions_resolve_against_the_threads_participants`); [docs/memory.md](memory.md) |
| LLM05:2025 Improper Output Handling | Output layer: every field is checked again in code (type, allowed values, length caps), and a proposed reply is forced empty unless the thread is `needs_you`. Rendering layer: model text is shown with `textContent`, never as HTML. Sending (`frontdesk/sending.py`): recipients, subject and threading come from the thread, never from the model or the body; a reply with `[placeholders]` left is refused; you confirm the exact text, and it waits 30 seconds for Undo. | `tests/test_triage.py` (`test_validate_rejects_bad_output`, `test_reply_dropped_unless_needs_you`); `tests/test_sending.py` (`test_prepare_refusals`, `test_cancel_inside_window_and_not_after`) |
| LLM06:2025 Excessive Agency | The model has no agency: the Anthropic, OpenAI and Gemini adapters send a system prompt, the text and a JSON schema, with no tool definitions. Gmail scope layer: sync reads with `gmail.readonly`; the `gmail.modify` token is loaded only by the action and send paths. Every action is your click, and sends are capped at 10 an hour and one per thread per 10 minutes. | `frontdesk/providers/`; `tests/test_sending.py` (`test_rate_limits`, `test_only_the_send_module_can_send`); `tests/test_connect.py` (`test_a_different_scope_or_no_refresh_token_is_refused`) |
| LLM07:2025 System Prompt Leakage | Out of scope by design: the prompts are public source (`frontdesk/triage.py`, `frontdesk/assist.py`) and hold no secrets or credentials, and access is enforced in code, not in the prompt. Your profile and What's going on are in the prompt and a mail could try to coax them into a reply; a reply leaves only after you read and confirm it. | `frontdesk/triage.py`; `frontdesk/assist.py` |
| LLM08:2025 Vector and Embedding Weaknesses | Out of scope: there is no RAG, embedding or vector store. Ask's related threads are other stored threads that share a participant, chosen by a plain SQLite scan, not by similarity search. | `frontdesk/store.py` (`related`) |
| LLM09:2025 Misinformation | Partly. A ranking, summary or draft can be wrong. Nothing the model writes goes out without you: a draft is only a proposal you edit and confirm. The triage suite measures ranking accuracy per model, and the attack page flags facts in a draft (such as an amount or a phone number) that the mail does not contain. | `evals/triage/` (80 cases); `tests/test_attack.py` (`test_resisted_and_invented_facts`) |
| LLM10:2025 Unbounded Consumption | Every call has an output-token cap (2,048 by default, 8,000 for Ask), and input is bounded: at most 100 Gmail threads and 100 Slack items per sync, 2,500 characters of What's going on, a capped block of notes. A thread is ranked again only when it changes; a refusal is never re-billed, and an error is retried at most 3 times. Network layer: no other website, and no other machine without the token, can reach the routes that call a model. Each call's cost is logged for `frontdesk stats`. There is no spend cap in FrontDesk: set one at the vendor. | `tests/test_triage.py` (`test_run_saves_and_retriages_only_changed`, `test_refusal_is_terminal_and_errors_are_capped`); `tests/test_notes_cap.py` |

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
