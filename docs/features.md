# What FrontDesk does

Every feature, in detail. The [README](../README.md) has the idea and the results.


- **Sync** your Gmail inbox with a read-only token.
- **Triage** each thread with the model you choose: `needs_you` / `fyi` / `ignore`, urgency 1 to 5,
  a one-line reason, and a proposed reply when one is warranted. Replies never invent facts: where
  only you know the answer they carry a placeholder like `[time that works]`.
- **Show** a ranked page that leads each thread with a short summary, renders the full thread
  like Gmail (the mail's own HTML, safely sandboxed), and has a Sync button.
- **Slack (optional):** your own Slack app and user token. DMs, group DMs and channel threads
  that mention you, that you replied in or that you started become threads on the same page, from
  the last 7 days (`slack_days`), plus anything still unread however old (back to
  `slack_unread_days`, 90): DMs with someone else's message after your read position, and
  channel messages that mention you after it. With `slack_channel_messages: "all"` (default
  `"mentions"`), every message in your channels comes in, for a workspace that is yours (agents
  or bots posting to you), with unread ones back to `slack_unread_days`. The newest 100
  conversations are kept
  (`slack_max_items`, like `gmail_max_threads`). DMs and threads you follow show unread from
  Slack's own read position. Reading a channel message in FrontDesk (or marking it done) moves
  Slack's read position for that channel too, but only up to the newest message such that every
  older unread one there is read or done in FrontDesk, so nothing you have not seen is marked
  read in Slack (needs the `channels:write`/`groups:write` scopes in the manifest; reinstall an
  older app to add them). A thread's own read state stays in FrontDesk (no public Slack API moves
  it), and a mark you made holds through syncs until you read it in Slack or a new reply comes. **Done** hides one until someone posts again, and
  **Send** replies in the thread with the same confirm-and-undo flow.
  A star on a Slack thread is kept in FrontDesk only: Slack has no supported API for saving a
  message for later (`stars.add` still answers, but since 2023 it has no effect anyone can see in
  Slack, per [Slack's changelog](https://docs.slack.dev/changelog/2023-07-its-later-already-for-stars-and-reminders/)),
  so no extra Slack scope is needed, and the star goes when the thread ages out of the sync window.
- **Ask** about any thread: the box starts with FrontDesk's own question ("What do you think? ...")
  as editable text; change it or leave it, and **Ask** sends what is in the box (the model picker
  chooses the model). **Second opinion** has the review model check the answer; **Polish draft**
  tightens the reply. Each answer resets the box to the built-in question.
- **Auto-sync** a few seconds after the server starts, then every 15 minutes (`auto_sync_minutes`);
  `Shift+N` (Gmail's update key) or the Sync button syncs now. When Gmail's `historyId` (it moves
  on any change in the mailbox), the query and the kept threads are as they were after the last
  complete sync, Gmail sync is one call and fetches nothing. Opening the page syncs when the last
  sync is more than 2 minutes old. An open page reloads only after a sync that changed something. With an `in:inbox` query, a thread Gmail lists whose messages carry no INBOX
  label (Gmail's listing can be stale for old mail) is left out, as Gmail's own inbox leaves it
  out. Gmail-style keyboard shortcuts (`?`):
  `j`/`k` move, `o` opens, `e`/`y` archive (or mark a Slack thread done), `[`/`]` archive and
  open the next thread, `s` stars, `r` replies, `a` replies all, `Shift+I`/`Shift+U` mark read
  and unread (Gmail too; on Slack, unread is kept in FrontDesk), `z` undoes, `g i`/`g s`/`g u` go to the
  inbox, Starred or Unread (both views are toggles beside the section counts, Unread listing
  every unread thread from Gmail and Slack). Each action that changes mail also has a control: row icons on hover, the
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
  sync reads only the last week of the inbox. Each Gmail result also has icons under its age, for
  its own state: Mark read or Mark unread, and Archive or Move to inbox. Slack matches are ones
  FrontDesk has not stored: they open in Slack, and **Keep** (their icon, or the bar after `x`)
  brings the conversation in, ranked once, kept current by sync until you mark it done.
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
