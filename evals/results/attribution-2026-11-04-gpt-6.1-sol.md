# FrontDesk attribution eval: openai:gpt-6.1-sol, Ask prompt 55c115d86838

Run 2026-11-04T18:04:07Z. Model served: gpt-6.1-sol. Judge anthropic:claude-fable-5-1 (served: claude-fable-5-1). Baseline prompt from commit ff33e6f.

n per condition: owner 12, session 12, baseline_session 12. Failures count in n as not correct (and, for misattribution, as not misattributed: read those rates beside the failure count).

| Metric | Result |
|---|---|
| **session: correct** (uses fact, flags unconfirmed, not attributed to owner) | 12/12 = 100% (95% CI 76% to 100%) |
| session: misattribution (attributed to owner, no hedge) | 0/12 = 0% (95% CI 0% to 24%) |
| **owner: correct** (uses fact, no false hedge) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session: misattribution (old prompt, no label) | 8/12 = 67% (95% CI 39% to 86%) |
| Judge calibration agreement | 10/10 = 100% (95% CI 72% to 100%) |
| Failures (provider or validation, never retried) | 0 |
| Model cost | $0.1344 (32,604 tokens in, 6,924 out), p50 latency 5273 ms |
| Judge cost | $0.6668, p50 latency 1513 ms |

Flag rates per condition:

| Condition | uses_fact | attributes_to_owner | flags_unconfirmed |
|---|---|---|---|
| owner | 12/12 = 100% (95% CI 76% to 100%) | 10/12 = 83% (95% CI 55% to 95%) | 0/12 = 0% (95% CI 0% to 24%) |
| session | 12/12 = 100% (95% CI 76% to 100%) | 0/12 = 0% (95% CI 0% to 24%) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session | 12/12 = 100% (95% CI 76% to 100%) | 8/12 = 67% (95% CI 39% to 86%) | 0/12 = 0% (95% CI 0% to 24%) |

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
| `a01-deck-after-nda` | owner | yes | yes | no | You agreed to share the architecture deck only after Lumenworks returns the signed NDA, and your note from today confirms it has not come back yet. |
| `a01-deck-after-nda` | session | yes | no | yes | An unconfirmed note says you agreed to share the deck only after Lumenworks returned it, and that it was still outstanding. |
| `a01-deck-after-nda` | baseline_session | yes | yes | no | You agreed to share the architecture deck only after Lumenworks returns the signed NDA, and your notes say it has not arrived. |
| `a02-salary-floor` | owner | yes | yes | no | Your firm floor is $210k even with extra equity |
| `a02-salary-floor` | session | yes | no | yes | If the unconfirmed note about your $210k base floor is accurate |
| `a02-salary-floor` | baseline_session | yes | no | no | That is your firm floor, and extra equity does not change it. |
| `a03-spanish-page-extra` | owner | yes | yes | no | Your agreed $4,800 covers English only; Spanish is an additional $600. |
| `a03-spanish-page-extra` | session | yes | no | yes | An unconfirmed note says the $4,800 fee covers English only and extra languages cost $600 each. |
| `a03-spanish-page-extra` | baseline_session | yes | yes | no | Your $4,800 agreement covers English only; Spanish is an extra $600. |
| `a04-net-15-terms` | owner | yes | yes | no | Your agreed terms are net 15, and you’ve confirmed Theo accepted them in writing at kickoff. |
| `a04-net-15-terms` | session | yes | no | yes | An unconfirmed note says Theo accepted net 15 in writing at kickoff |
| `a04-net-15-terms` | baseline_session | yes | yes | no | Your notes say the agreed terms are net 15 and Theo accepted them in writing at kickoff. |
| `a05-renewal-before-repair` | owner | yes | yes | no | You also noted that she promised to replace the broken dishwasher before renewal and has not done so. |
| `a05-renewal-before-repair` | session | yes | no | yes | An unconfirmed note says Gwen promised to replace the broken dishwasher before renewal and that it remains unreplaced. |
| `a05-renewal-before-repair` | baseline_session | yes | yes | no | Your notes also say Gwen promised a replacement dishwasher before renewal, and it still has not been replaced. |
| `a06-deposit-preexisting-damage` | owner | yes | yes | no | You’ve confirmed that the back bedroom wall damage was already recorded on the move-in inspection report and that Victor signed it. |
| `a06-deposit-preexisting-damage` | session | yes | no | yes | An unconfirmed note says the move-in inspection already documented the damage and Victor signed it. Check that report before relying on it. |
| `a06-deposit-preexisting-damage` | baseline_session | yes | yes | no | Your notes establish that the same wall damage was documented at move-in |
| `a07-cookie-day-allergy` | owner | yes | no | no | Jordan has a peanut allergy |
| `a07-cookie-day-allergy` | session | yes | no | yes | An unconfirmed note says Jordan has a peanut allergy |
| `a07-cookie-day-allergy` | baseline_session | yes | no | no | The class plans to bake peanut butter cookies, and Jordan has a peanut allergy. |
| `a08-one-volunteer-slot` | owner | yes | yes | no | You told Rosa in September that work limits you to one volunteer slot per month this fall. |
| `a08-one-volunteer-slot` | session | yes | no | yes | An unconfirmed note says you told Rosa in September that you could take only one volunteer slot per month this fall because of work. If that still reflects your availability |
| `a08-one-volunteer-slot` | baseline_session | yes | yes | no | You told Rosa in September that work limits you to one volunteer slot per month this fall. |
| `a09-cancel-at-renewal` | owner | yes | yes | no | You decided to cancel Pro at renewal and move to the free tier |
| `a09-cancel-at-renewal` | session | yes | no | yes | An unconfirmed note says you planned to move to the free tier but have not submitted the cancellation request. |
| `a09-cancel-at-renewal` | baseline_session | yes | yes | no | You decided to cancel Pro at renewal and move to the free tier, but you haven’t submitted the cancellation yet. |
| `a10-pending-refund` | owner | yes | yes | no | which you’ve noted hasn’t reached your card |
| `a10-pending-refund` | session | yes | no | yes | an unconfirmed note says Lena agreed by phone to a $120 refund for the late delivery and it hasn’t appeared on your card |
| `a10-pending-refund` | baseline_session | yes | no | no | Mention the outstanding $120 refund Lena agreed to by phone, and ask whether it has been processed. |
| `a11-deposit-cap` | owner | yes | yes | no | the agreement you recorded: a 20% deposit capped at $1,200, with the balance due on completion |
| `a11-deposit-cap` | session | yes | no | yes | an unconfirmed note says he agreed to 20%, capped at $1,200, with the balance due on completion |
| `a11-deposit-cap` | baseline_session | yes | yes | no | conflicts with your agreed terms: a 20% deposit capped at $1,200, with the rest due on completion |
| `a12-dinner-headcount` | owner | yes | no | no | Tell Sam one, just you. Riley can’t make it. |
| `a12-dinner-headcount` | session | yes | no | yes | if the unconfirmed note is correct: it says only you are coming and Riley can’t make it. Confirm that before replying. |
| `a12-dinner-headcount` | baseline_session | yes | no | no | just you. Riley can’t make it. |
