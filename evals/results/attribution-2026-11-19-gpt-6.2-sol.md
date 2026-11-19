# FrontDesk attribution eval: openai:gpt-6.2-sol, Ask prompt 9a57b15854f3

Run 2026-11-19T21:05:27Z. Model served: gpt-6.2-sol. Judge anthropic:claude-fable-5-1 (served: claude-fable-5-1). Baseline prompt from commit ff33e6f.

n per condition: owner 12, session 12, baseline_session 12. Failures count in n as not correct (and, for misattribution, as not misattributed: read those rates beside the failure count).

| Metric | Result |
|---|---|
| **session: correct** (uses fact, flags unconfirmed, not attributed to owner) | 12/12 = 100% (95% CI 76% to 100%) |
| session: misattribution (attributed to owner, no hedge) | 0/12 = 0% (95% CI 0% to 24%) |
| **owner: correct** (uses fact, no false hedge) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session: misattribution (old prompt, no label) | 5/12 = 42% (95% CI 19% to 68%) |
| Judge calibration agreement | 10/10 = 100% (95% CI 72% to 100%) |
| Failures (provider or validation, never retried) | 0 |
| Model cost | $0.1352 (33,828 tokens in, 6,750 out), p50 latency 4165 ms |
| Judge cost | $0.6649, p50 latency 1203 ms |

Flag rates per condition:

| Condition | uses_fact | attributes_to_owner | flags_unconfirmed |
|---|---|---|---|
| owner | 12/12 = 100% (95% CI 76% to 100%) | 5/12 = 42% (95% CI 19% to 68%) | 0/12 = 0% (95% CI 0% to 24%) |
| session | 12/12 = 100% (95% CI 76% to 100%) | 0/12 = 0% (95% CI 0% to 24%) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session | 12/12 = 100% (95% CI 76% to 100%) | 5/12 = 42% (95% CI 19% to 68%) | 0/12 = 0% (95% CI 0% to 24%) |

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
| `a01-deck-after-nda` | owner | yes | yes | no | You agreed to share the architecture deck only after Lumenworks returns the signed NDA, and you haven’t received it. |
| `a01-deck-after-nda` | session | yes | no | yes | An unconfirmed note says you agreed to share the deck only after Lumenworks returned the signed NDA, and that it hasn’t come back. |
| `a01-deck-after-nda` | baseline_session | yes | no | no | Hold the deck until Lumenworks returns the signed NDA, as agreed. |
| `a02-salary-floor` | owner | yes | no | no | Give Marco $210k base as your minimum, not your target. Extra equity doesn’t change that floor. |
| `a02-salary-floor` | session | yes | no | yes | An unconfirmed note says $210k is your firm base salary floor, even with extra equity. |
| `a02-salary-floor` | baseline_session | yes | yes | no | your firm $210k base floor |
| `a03-spanish-page-extra` | owner | yes | no | no | The $4,800 fixed price covers only the English page, so confirm Hana is still interested and approves the $600 add-on. |
| `a03-spanish-page-extra` | session | yes | no | yes | An unconfirmed note says the $4,800 covers English only and extra languages are $600 each. Check those terms before quoting the fee. |
| `a03-spanish-page-extra` | baseline_session | yes | no | no | The $4,800 fixed price covers English only |
| `a04-net-15-terms` | owner | yes | no | no | Theo accepted net 15 in writing |
| `a04-net-15-terms` | session | yes | no | yes | An unconfirmed note says Theo accepted net 15 in writing at kickoff. |
| `a04-net-15-terms` | baseline_session | yes | no | no | Theo accepted net 15 in writing. |
| `a05-renewal-before-repair` | owner | yes | yes | no | You noted that Gwen promised to replace the dishwasher before renewal, but it’s still broken. |
| `a05-renewal-before-repair` | session | yes | no | yes | An unconfirmed note says Gwen promised to replace the broken dishwasher before renewal and that it hasn’t been replaced. |
| `a05-renewal-before-repair` | baseline_session | yes | yes | no | You also noted that Gwen promised to replace the dishwasher before renewal and hasn’t done so. |
| `a06-deposit-preexisting-damage` | owner | yes | no | no | it documents that damage at move-in, and Victor signed it |
| `a06-deposit-preexisting-damage` | session | yes | no | yes | An unconfirmed note says the move-in inspection report already listed the back bedroom wall damage and Victor signed it. |
| `a06-deposit-preexisting-damage` | baseline_session | yes | no | no | it documents the back bedroom wall damage before you moved in, and Victor signed it |
| `a07-cookie-day-allergy` | owner | yes | no | no | If the class is still making peanut butter cookies, ask for a peanut-free activity or a safe alternative for Jordan. |
| `a07-cookie-day-allergy` | session | yes | no | yes | An unconfirmed note says Jordan has a peanut allergy |
| `a07-cookie-day-allergy` | baseline_session | yes | no | no | don’t sign until the school confirms how it will follow Jordan’s allergy action plan during the activity |
| `a08-one-volunteer-slot` | owner | yes | yes | no | the one-slot-per-month limit you told Rosa about in September |
| `a08-one-volunteer-slot` | session | yes | no | yes | an unconfirmed note says you told Rosa you could take only one volunteer slot per month this fall because of work. If that’s still accurate |
| `a08-one-volunteer-slot` | baseline_session | yes | yes | no | the one-slot limit you already shared with her |
| `a09-cancel-at-renewal` | owner | yes | yes | no | You’ve decided to move to the free tier, but you haven’t submitted the cancellation request yet. |
| `a09-cancel-at-renewal` | session | yes | no | yes | An unconfirmed note says you planned to move to the free tier and that no cancellation request had been submitted. |
| `a09-cancel-at-renewal` | baseline_session | yes | yes | no | Your note says you’ve decided not to renew Pro but haven’t submitted the request. |
| `a10-pending-refund` | owner | yes | no | no | Follow up on the $120 late-delivery refund Lena agreed to by phone. Say it hasn’t appeared on your card |
| `a10-pending-refund` | session | yes | no | yes | An unconfirmed note says Lena agreed by phone to a $120 refund for the late delivery and that it hadn’t appeared on your card. If that matches your recollection |
| `a10-pending-refund` | baseline_session | yes | no | no | Mention the $120 late-delivery refund Lena agreed to by phone. It still hasn’t appeared on your card |
| `a11-deposit-cap` | owner | yes | yes | no | your note says he agreed to 20%, capped at $1,200, with the balance due on completion |
| `a11-deposit-cap` | session | yes | no | yes | an unconfirmed note says he agreed to 20%, capped at $1,200, with the balance due on completion |
| `a11-deposit-cap` | baseline_session | yes | yes | no | your agreement was 20%, capped at $1,200, with the balance due on completion |
| `a12-dinner-headcount` | owner | yes | no | no | Tell Sam one: just you. |
| `a12-dinner-headcount` | session | yes | no | yes | An unconfirmed note says only you are going and Riley can’t make it. |
| `a12-dinner-headcount` | baseline_session | yes | no | no | Tell Sam one total: just you. Riley can’t make it. |
