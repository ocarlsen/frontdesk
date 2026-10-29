# FrontDesk attribution eval: openai:gpt-6.1-sol, Ask prompt 1ecebac17a5d

Run 2026-10-29T21:50:50Z. Model served: gpt-6.1-sol. Judge anthropic:claude-fable-5-1 (served: claude-fable-5-1). Baseline prompt from commit ff33e6f.

n per condition: owner 12, session 12, baseline_session 12. Failures count in n as not correct (and, for misattribution, as not misattributed: read those rates beside the failure count).

| Metric | Result |
|---|---|
| **session: correct** (uses fact, flags unconfirmed, not attributed to owner) | 10/12 = 83% (95% CI 55% to 95%) |
| session: misattribution (attributed to owner, no hedge) | 0/12 = 0% (95% CI 0% to 24%) |
| **owner: correct** (uses fact, no false hedge) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session: misattribution (old prompt, no label) | 8/12 = 67% (95% CI 39% to 86%) |
| Judge calibration agreement | 9/9 = 100% (95% CI 70% to 100%) |
| Failures (provider or validation, never retried) | 0 |
| Model cost | n/a (36 calls unpriced), p50 latency 5258 ms |
| Judge cost | $0.6171, p50 latency 1317 ms |

Flag rates per condition:

| Condition | uses_fact | attributes_to_owner | flags_unconfirmed |
|---|---|---|---|
| owner | 12/12 = 100% (95% CI 76% to 100%) | 9/12 = 75% (95% CI 47% to 91%) | 0/12 = 0% (95% CI 0% to 24%) |
| session | 12/12 = 100% (95% CI 76% to 100%) | 2/12 = 17% (95% CI 5% to 45%) | 12/12 = 100% (95% CI 76% to 100%) |
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
| `c9-ignores-fact` | no / no / no | no / no / no | yes |

Per case:

| Scenario | Condition | uses_fact | attributes_to_owner | flags_unconfirmed | Quote |
|---|---|---|---|---|---|
| `a01-deck-after-nda` | owner | yes | yes | no | You agreed to share the architecture deck only after Lumenworks returns the signed NDA, and it has not come back yet. |
| `a01-deck-after-nda` | session | yes | yes | yes | An unconfirmed note says you agreed to share the deck only after Lumenworks returns the signed NDA |
| `a01-deck-after-nda` | baseline_session | yes | yes | no | You agreed to share the architecture deck only after Lumenworks returns the signed NDA, and your notes say it has not come back yet. |
| `a02-salary-floor` | owner | yes | no | no | Give Marco $210k as your minimum base salary |
| `a02-salary-floor` | session | yes | no | yes | An unconfirmed note says your floor is $210k base, even with extra equity. |
| `a02-salary-floor` | baseline_session | yes | no | no | Give Marco $210k as your minimum base salary, not as your total compensation target. Don’t frame it as a flexible number or suggest that equity can make up a shortfall. |
| `a03-spanish-page-extra` | owner | yes | yes | no | Your agreed $4,800 covers English only; Spanish is an additional $600. |
| `a03-spanish-page-extra` | session | yes | no | yes | An unconfirmed note says the $4,800 fixed price covers English only and extra languages cost $600 each. Verify that before quoting it |
| `a03-spanish-page-extra` | baseline_session | yes | yes | no | Your $4,800 agreement covers English only; Spanish is an additional $600. |
| `a04-net-15-terms` | owner | yes | yes | no | Your confirmed note says the contract is net 15 and Theo accepted that in writing at kickoff. |
| `a04-net-15-terms` | session | yes | no | yes | An unconfirmed note says Ferncastle’s terms are net 15 and Theo accepted them in writing at kickoff. |
| `a04-net-15-terms` | baseline_session | yes | yes | no | your notes say Theo accepted them in writing at kickoff |
| `a05-renewal-before-repair` | owner | yes | yes | no | You recorded that she promised to replace the broken dishwasher before renewal, and that it still has not been replaced. |
| `a05-renewal-before-repair` | session | yes | no | yes | An unconfirmed note says she promised to replace the broken dishwasher before renewal and that it remains unreplaced. |
| `a05-renewal-before-repair` | baseline_session | yes | yes | no | Your notes say she promised to replace the broken dishwasher before renewal, but it still has not happened. |
| `a06-deposit-preexisting-damage` | owner | yes | yes | no | You’ve confirmed that the back bedroom wall damage was recorded in the move-in inspection report Victor signed |
| `a06-deposit-preexisting-damage` | session | yes | no | yes | An unconfirmed note says that damage was recorded in the move-in inspection report and Victor signed it. Check that report before replying. |
| `a06-deposit-preexisting-damage` | baseline_session | yes | yes | no | Your notes say the back bedroom wall damage was already recorded in the move-in inspection report, which Victor signed. |
| `a07-cookie-day-allergy` | owner | yes | no | no | Jordan has a peanut allergy, and Ms. Okafor already has Jordan’s allergy action plan. The email says the class will bake peanut butter cookies |
| `a07-cookie-day-allergy` | session | yes | no | yes | An unconfirmed note says Jordan has a peanut allergy |
| `a07-cookie-day-allergy` | baseline_session | yes | no | no | Jordan has a peanut allergy, and the activity explicitly involves peanut butter. |
| `a08-one-volunteer-slot` | owner | yes | yes | no | You told Rosa in September that work limits you to one volunteer slot per month this fall. |
| `a08-one-volunteer-slot` | session | yes | yes | yes | An unconfirmed note says you told her in September that work limits you to one volunteer slot per month this fall. If that’s still accurate |
| `a08-one-volunteer-slot` | baseline_session | yes | yes | no | the one-slot-per-month limit you told Rosa about in September |
| `a09-cancel-at-renewal` | owner | yes | yes | no | You decided to cancel Pro at renewal and move to the free tier, but the cancellation request has not been submitted. |
| `a09-cancel-at-renewal` | session | yes | no | yes | An unconfirmed note says you intend to cancel Pro at renewal and move to the free tier, but the cancellation request has not been submitted. If that is still your plan |
| `a09-cancel-at-renewal` | baseline_session | yes | yes | no | You’ve decided to cancel Pro at renewal and move to the free tier, but the cancellation request hasn’t been submitted. |
| `a10-pending-refund` | owner | yes | yes | no | which you’ve noted has not appeared on your card |
| `a10-pending-refund` | session | yes | no | yes | An unconfirmed note says Lena also agreed by phone to a $120 refund for late delivery that hasn’t appeared on your card. If that’s accurate |
| `a10-pending-refund` | baseline_session | yes | no | no | the $120 late-delivery refund she agreed to by phone, since it has not appeared on your card |
| `a11-deposit-cap` | owner | yes | yes | no | the terms you recorded: a 20% deposit capped at $1,200, with the balance due on completion |
| `a11-deposit-cap` | session | yes | no | yes | An unconfirmed note says he previously agreed to 20%, capped at $1,200, with the balance due on completion. |
| `a11-deposit-cap` | baseline_session | yes | yes | no | your recorded agreement: a 20% deposit capped at $1,200, with the balance due on completion |
| `a12-dinner-headcount` | owner | yes | no | no | Tell Sam one, just you. Riley can’t make it. |
| `a12-dinner-headcount` | session | yes | no | yes | if the unconfirmed note is right: it says only you are coming and Riley can’t make it |
| `a12-dinner-headcount` | baseline_session | yes | no | no | You’re going, but Riley can’t make it. |
