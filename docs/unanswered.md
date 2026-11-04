# Unanswered email (optional, IMAP)


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
