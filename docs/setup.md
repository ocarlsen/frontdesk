# Set it up on your own mail


Python 3.12 (the version CI tests), on macOS or Linux. Keys and tokens can live in environment
variables; on macOS they can also live in the login Keychain, which is what the item names below
refer to. On Linux, use the environment variables.

**1. Gmail (required).** In Google Cloud Console: create a project, enable the Gmail API, configure
the OAuth consent screen (External, Testing), add yourself as a test user, and create a **Desktop
app** OAuth client. Save its JSON as `~/.frontdesk/client_secret.json`. Then connect from the
page (**Profile**, **Google account**, **Connect**), or run `frontdesk sync` once, which opens
Google's consent page for read-only access.

**2. Pick a model.** Claude is the default; OpenAI and Gemini work the same way.

| Vendor | `settings.json` | Key | Install |
| --- | --- | --- | --- |
| Anthropic (default) | `"provider": "anthropic", "model": "claude-opus-5-5"` | `ANTHROPIC_API_KEY`, or Keychain `frontdesk-anthropic` | included |
| OpenAI | `"provider": "openai", "model": "gpt-6.1-sol"` | `OPENAI_API_KEY`, or Keychain `frontdesk-openai` | `.venv/bin/pip install -e '.[openai]'` |
| Gemini | `"provider": "gemini", "model": "gemini-3.8-flash"` | `GEMINI_API_KEY`, or Keychain `frontdesk-gemini` | `.venv/bin/pip install -e '.[gemini]'` |

To store a key in the Keychain: `security add-generic-password -U -s frontdesk-anthropic -a $USER -w`
(it prompts for the key, so it never lands in your shell history). Ask's model picker offers every
vendor in `ask_models` that has a key.

**3. Run it.** `frontdesk doctor` first lists what is set up and what is missing, each with the
step that fixes it (offline; it never prints a key; `--online` also checks the Slack token).

```
frontdesk doctor
frontdesk sync                # first run opens Google consent (read-only)
frontdesk triage --limit 20
frontdesk serve               # prints the page URL; syncs on start and every 15 minutes
```

**4. Let it act (optional).** Archive, star, mark read, drafts and Send use a second, separate
Google permission (`gmail.modify`), kept in its own token file: **Connect** beside Gmail
actions in **Profile**, or `frontdesk authorize-actions`. Without it, FrontDesk reads and ranks
but never changes your mail.

**5. Slack (optional).** [Create the Slack app](https://api.slack.com/apps?new_app=1&manifest_yaml=display_information%3A%0A%20%20name%3A%20FrontDesk%0A%20%20description%3A%20Your%20own%20copy%20of%20FrontDesk%20reads%20your%20Slack%20for%20your%20local%20inbox.%0Aoauth_config%3A%0A%20%20scopes%3A%0A%20%20%20%20user%3A%0A%20%20%20%20%20%20-%20channels%3Aread%0A%20%20%20%20%20%20-%20groups%3Aread%0A%20%20%20%20%20%20-%20im%3Aread%0A%20%20%20%20%20%20-%20mpim%3Aread%0A%20%20%20%20%20%20-%20channels%3Ahistory%0A%20%20%20%20%20%20-%20groups%3Ahistory%0A%20%20%20%20%20%20-%20im%3Ahistory%0A%20%20%20%20%20%20-%20mpim%3Ahistory%0A%20%20%20%20%20%20-%20users%3Aread%0A%20%20%20%20%20%20-%20chat%3Awrite%0A%20%20%20%20%20%20-%20search%3Aread%0A%20%20%20%20%20%20-%20im%3Awrite%0A%20%20%20%20%20%20-%20mpim%3Awrite%0A%20%20%20%20%20%20-%20channels%3Awrite%0A%20%20%20%20%20%20-%20groups%3Awrite%0Asettings%3A%0A%20%20org_deploy_enabled%3A%20false%0A%20%20socket_mode_enabled%3A%20false%0A%20%20token_rotation_enabled%3A%20false): this opens Slack's "Create from a
manifest" dialog already filled in from [`docs/slack-app-manifest.yaml`](slack-app-manifest.yaml)
(or paste that file at [api.slack.com/apps](https://api.slack.com/apps): Create New App, From a
manifest). Pick your workspace, then **Next** and **Create and Install**. It asks only for
user-token scopes, each commented in the file with the call that needs it. Then, on the app's
**OAuth & Permissions** page, copy the **User OAuth Token** (`xoxp-...`), and store it as `SLACK_USER_TOKEN` or the Keychain item
`frontdesk-slack`. The next sync brings Slack in. In a workspace that is yours (agents or bots
posting to you), `"slack_channel_messages": "all"` brings in every channel message, not only
the ones that mention you.

**While the Google app is in Testing**, Google shows an "unverified app" screen (you are the
developer) and both tokens expire after 7 days: the page's sync message then offers **Connect
Gmail**, and `sync` and `authorize-actions` ask you to consent again.

**Connecting from the page.** **Profile** shows each permission as connected or not, with
**Connect** (or **Reconnect**) and **Disconnect**, which deletes that token from this computer;
Google keeps listing FrontDesk at [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
until you remove it there. A Desktop client may only send the browser back to `localhost`. On the
computer running FrontDesk that finishes by itself. From another device (a phone or laptop on
your tailnet), Google's tab ends on a page that cannot load; copy its whole address into the box
FrontDesk shows, and it finishes the same way. To skip that step, add a second OAuth client of
type **Web application** with the authorized redirect URI `https://<your FrontDesk address>/oauth/callback`
(for example a Tailscale Serve name) and save its JSON as `~/.frontdesk/client_secret_web.json`:
a page opened at that https address then connects directly.

**Settings** (`~/.frontdesk/settings.json`, all optional; the full list with defaults is
`DEFAULTS` in [`frontdesk/config.py`](../frontdesk/config.py)):

- Model: `provider`, `model`, `provider_options`, `ask_models`, `review_model`, and the Keychain
  item names `keychain_service`, `openai_keychain_service`, `gemini_keychain_service`.
- You: `owner_profile` (a few sentences for the model), `reply_signoff`.
- Gmail: `gmail_query` (default `in:inbox newer_than:7d`), `gmail_max_threads` (100).
- Slack: `slack_keychain_service`, `slack_days` (7), `slack_unread_days` (90), `slack_max_items`
  (100), `slack_channel_messages` (`"mentions"` or `"all"`).
- Server: `serve_host`, `serve_port`, `serve_display_host`, `serve_allowed_hosts`,
  `auto_sync_minutes` (15; 0 turns it off), `mark_read_on_open`.
- IMAP, for `frontdesk unanswered` and `inbox-buckets`: see [unanswered.md](unanswered.md).

Unknown keys are an error, not ignored.
