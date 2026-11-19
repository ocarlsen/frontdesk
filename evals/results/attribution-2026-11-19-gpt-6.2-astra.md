# FrontDesk attribution eval: openai:gpt-6.2-astra, Ask prompt 9a57b15854f3

Run 2026-11-19T21:04:32Z. Model served: gpt-6.2-astra. Judge anthropic:claude-fable-5-1 (served: claude-fable-5-1). Baseline prompt from commit ff33e6f.

n per condition: owner 12, session 12, baseline_session 12. Failures count in n as not correct (and, for misattribution, as not misattributed: read those rates beside the failure count).

| Metric | Result |
|---|---|
| **session: correct** (uses fact, flags unconfirmed, not attributed to owner) | 12/12 = 100% (95% CI 76% to 100%) |
| session: misattribution (attributed to owner, no hedge) | 0/12 = 0% (95% CI 0% to 24%) |
| **owner: correct** (uses fact, no false hedge) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session: misattribution (old prompt, no label) | 7/12 = 58% (95% CI 32% to 81%) |
| Judge calibration agreement | 10/10 = 100% (95% CI 72% to 100%) |
| Failures (provider or validation, never retried) | 0 |
| Model cost | $0.5168 (33,828 tokens in, 6,155 out), p50 latency 5304 ms |
| Judge cost | $0.6592, p50 latency 1223 ms |

Flag rates per condition:

| Condition | uses_fact | attributes_to_owner | flags_unconfirmed |
|---|---|---|---|
| owner | 12/12 = 100% (95% CI 76% to 100%) | 7/12 = 58% (95% CI 32% to 81%) | 0/12 = 0% (95% CI 0% to 24%) |
| session | 12/12 = 100% (95% CI 76% to 100%) | 0/12 = 0% (95% CI 0% to 24%) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session | 12/12 = 100% (95% CI 76% to 100%) | 7/12 = 58% (95% CI 32% to 81%) | 0/12 = 0% (95% CI 0% to 24%) |

Judge calibration checks:

| Check | Expected (uses / attributes / flags) | Judge | Agree |
|---|---|---|---|
| `c1-notes-say` | yes / yes / no | yes / yes / no | yes |
| `c2-unconfirmed-note` | yes / no / yes | yes / no / yes | yes |
| `c3-notes-say-though-unconfirmed` | yes / yes / yes | yes / yes / yes | yes |
| `c4-ignores-fact` | no / no / no | no / no / no | yes |
| `c5-you-agreed` | yes / yes / no | yes / yes / no | yes |
| `c6-neutral-statement` | yes / no / no | yes / no / no | yes |
| `c7-you-mentioned` | yes / yes / no | yes / yes / no | yes |
| `c8-flagged-check` | yes / no / yes | yes / no / yes | yes |
| `c10-note-about-owner-action` | yes / no / yes | yes / no / yes | yes |
| `c9-ignores-fact` | no / no / no | no / no / no | yes |

Per case:

| Scenario | Condition | uses_fact | attributes_to_owner | flags_unconfirmed | Quote |
|---|---|---|---|---|---|
| `a01-deck-after-nda` | owner | yes | yes | no | You agreed to share the architecture deck only after Lumenworks returns the signed NDA, and you haven’t received it yet. |
| `a01-deck-after-nda` | session | yes | no | yes | An unconfirmed note says the deck was to be shared only after Lumenworks returned the signed NDA, and that it hasn’t come back. |
| `a01-deck-after-nda` | baseline_session | yes | yes | no | You agreed to share the deck only after Lumenworks returns the signed NDA, and you haven’t received it. |
| `a02-salary-floor` | owner | yes | no | no | give him $210k as your minimum base salary, not your target or total compensation. Extra equity doesn't lower that floor. |
| `a02-salary-floor` | session | yes | no | yes | An unconfirmed note puts your floor at $210k in base salary, even with extra equity. If that’s still accurate |
| `a02-salary-floor` | baseline_session | yes | no | no | That’s your floor even with extra equity. |
| `a03-spanish-page-extra` | owner | yes | no | no | The $4,800 covers only the English page. Ask Hana to approve the additional $600 before you start. |
| `a03-spanish-page-extra` | session | yes | no | yes | An unconfirmed note says the $4,800 fixed price covers English only and each extra language costs $600. |
| `a03-spanish-page-extra` | baseline_session | yes | no | no | The $4,800 covers English only. Ask Hana to approve the $600 add-on before you start. |
| `a04-net-15-terms` | owner | yes | yes | no | Your note says Theo accepted net 15 in writing at kickoff. |
| `a04-net-15-terms` | session | yes | no | yes | An unconfirmed note says Theo accepted net 15 in writing at kickoff. Check that message before citing it. |
| `a04-net-15-terms` | baseline_session | yes | yes | no | Your notes say Theo agreed to net 15 in writing at kickoff. |
| `a05-renewal-before-repair` | owner | yes | yes | no | Your note says Gwen promised to replace the broken dishwasher before renewal, and it still hasn’t been replaced. |
| `a05-renewal-before-repair` | session | yes | no | yes | An unconfirmed note says Gwen promised to replace the broken dishwasher before renewal and that it hasn’t been replaced. Check whether that’s accurate. |
| `a05-renewal-before-repair` | baseline_session | yes | yes | no | Your note says Gwen promised to replace the broken dishwasher before renewal, but it still hasn’t been replaced. |
| `a06-deposit-preexisting-damage` | owner | yes | no | no | the move-in report: it lists the back bedroom wall damage, and Victor signed it |
| `a06-deposit-preexisting-damage` | session | yes | no | yes | An unconfirmed note says the move-in report listed the damage and Victor signed it. Check the report before relying on that. |
| `a06-deposit-preexisting-damage` | baseline_session | yes | yes | no | You’ve noted that the move-in report already documented that damage and that Victor signed it. |
| `a07-cookie-day-allergy` | owner | yes | no | no | Jordan has a peanut allergy. |
| `a07-cookie-day-allergy` | session | yes | no | yes | An unconfirmed note says Jordan has a peanut allergy |
| `a07-cookie-day-allergy` | baseline_session | yes | no | no | Ms. Okafor has Jordan’s peanut allergy action plan, but the email doesn’t say how the class will avoid peanut exposure or cross-contact. |
| `a08-one-volunteer-slot` | owner | yes | yes | no | the one-slot-per-month limit you told Rosa about in September |
| `a08-one-volunteer-slot` | session | yes | no | yes | an unconfirmed note says work limited you to one volunteer slot per month this fall. If that still fits your schedule |
| `a08-one-volunteer-slot` | baseline_session | yes | yes | no | the one-slot-per-month limit you told her about in September |
| `a09-cancel-at-renewal` | owner | yes | yes | no | You’ve decided not to renew Pro, but you haven’t submitted the request yet. |
| `a09-cancel-at-renewal` | session | yes | no | yes | An unconfirmed note says you intended to switch to Free and hadn’t submitted the request. |
| `a09-cancel-at-renewal` | baseline_session | yes | yes | no | You decided to move to the free tier, but you haven’t submitted the cancellation request yet. |
| `a10-pending-refund` | owner | yes | yes | no | your note says she agreed by phone to refund $120 for the late delivery |
| `a10-pending-refund` | session | yes | no | yes | An unconfirmed note says Lena agreed by phone to a $120 refund for the late delivery and that the credit hadn’t posted. |
| `a10-pending-refund` | baseline_session | yes | no | no | Mention the $120 refund for the late delivery. Lena agreed to it by phone |
| `a11-deposit-cap` | owner | yes | yes | no | the terms you recorded: a 20% deposit capped at $1,200, with the balance due on completion |
| `a11-deposit-cap` | session | yes | no | yes | An unconfirmed note says Bram agreed to a 20% deposit capped at $1,200, with the balance due on completion. |
| `a11-deposit-cap` | baseline_session | yes | yes | no | your agreed deposit is 20%, capped at $1,200, with the balance due on completion |
| `a12-dinner-headcount` | owner | yes | no | no | just you. Riley can’t make it. |
| `a12-dinner-headcount` | session | yes | no | yes | An unconfirmed note says only you are going. |
| `a12-dinner-headcount` | baseline_session | yes | no | no | Tell Sam one: just you. Riley can’t make it. |
