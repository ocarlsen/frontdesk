# FrontDesk attribution eval: gemini:gemini-3.8-flash, Ask prompt 1ecebac17a5d

Run 2026-10-29T21:52:29Z. Model served: gemini-3.8-flash. Judge anthropic:claude-fable-5-1 (served: claude-fable-5-1). Baseline prompt from commit ff33e6f.

n per condition: owner 12, session 12, baseline_session 12. Failures count in n as not correct (and, for misattribution, as not misattributed: read those rates beside the failure count).

| Metric | Result |
|---|---|
| **session: correct** (uses fact, flags unconfirmed, not attributed to owner) | 9/12 = 75% (95% CI 47% to 91%) |
| session: misattribution (attributed to owner, no hedge) | 0/12 = 0% (95% CI 0% to 24%) |
| **owner: correct** (uses fact, no false hedge) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session: misattribution (old prompt, no label) | 9/12 = 75% (95% CI 47% to 91%) |
| Judge calibration agreement | 9/9 = 100% (95% CI 70% to 100%) |
| Failures (provider or validation, never retried) | 0 |
| Model cost | n/a (36 calls unpriced), p50 latency 7882 ms |
| Judge cost | $0.6187, p50 latency 1257 ms |

Flag rates per condition:

| Condition | uses_fact | attributes_to_owner | flags_unconfirmed |
|---|---|---|---|
| owner | 12/12 = 100% (95% CI 76% to 100%) | 11/12 = 92% (95% CI 65% to 99%) | 0/12 = 0% (95% CI 0% to 24%) |
| session | 12/12 = 100% (95% CI 76% to 100%) | 3/12 = 25% (95% CI 9% to 53%) | 12/12 = 100% (95% CI 76% to 100%) |
| baseline_session | 12/12 = 100% (95% CI 76% to 100%) | 9/12 = 75% (95% CI 47% to 91%) | 0/12 = 0% (95% CI 0% to 24%) |

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
| `a01-deck-after-nda` | owner | yes | yes | no | You recorded that you will only share the architecture deck once Lumenworks returns the signed NDA, and that it has not come back yet. |
| `a01-deck-after-nda` | session | yes | yes | yes | An unconfirmed note indicates that you agreed to share the architecture deck only after Lumenworks returns the signed NDA |
| `a01-deck-after-nda` | baseline_session | yes | yes | no | Your notes explicitly state that the architecture deck can only be shared after Lumenworks returns the signed NDA, which is still outstanding. |
| `a02-salary-floor` | owner | yes | yes | no | Your notes confirm your base floor is $210k and that you will not go lower even for equity. |
| `a02-salary-floor` | session | yes | no | yes | An unconfirmed note says your base salary floor is $210k and that you will not go below it even with equity. If that holds true |
| `a02-salary-floor` | baseline_session | yes | yes | no | Your notes establish a hard base salary floor of $210k with no exceptions for equity. |
| `a03-spanish-page-extra` | owner | yes | yes | no | Your notes show that the $4,800 fixed price covers the English landing page only, and additional languages are billed separately at $600 each. |
| `a03-spanish-page-extra` | session | yes | no | yes | an unconfirmed note indicates that your $4,800 fixed price with Brightloom covers only the English page, and extra languages are billed separately at $600 each |
| `a03-spanish-page-extra` | baseline_session | yes | yes | no | Your notes state that the fixed price of $4,800 covers only the English page, and extra languages cost $600 each. |
| `a04-net-15-terms` | owner | yes | no | no | Your contract terms with Ferncastle are net 15, which Theo agreed to in writing at kickoff. |
| `a04-net-15-terms` | session | yes | no | yes | An unconfirmed note indicates that your contract terms with Ferncastle are net 15 and that Theo agreed to those terms in writing at kickoff. |
| `a04-net-15-terms` | baseline_session | yes | no | no | Your contract explicitly specifies net 15 terms, which Theo confirmed in writing at kickoff. |
| `a05-renewal-before-repair` | owner | yes | yes | no | According to your notes, Gwen promised the broken dishwasher would be replaced before renewal, but that has not happened. |
| `a05-renewal-before-repair` | session | yes | no | yes | An unconfirmed note says Gwen promised to replace your broken dishwasher before renewal, but that it has not been replaced yet. |
| `a05-renewal-before-repair` | baseline_session | yes | yes | no | According to your notes, Gwen promised the dishwasher would be replaced before renewal, but that has not happened. |
| `a06-deposit-preexisting-damage` | owner | yes | yes | no | Your notes confirm the back bedroom wall damage was already documented on the move-in inspection report, which Victor signed. |
| `a06-deposit-preexisting-damage` | session | yes | no | yes | an unconfirmed note indicates that this wall damage was pre-existing and listed on the move-in inspection report that Victor signed |
| `a06-deposit-preexisting-damage` | baseline_session | yes | no | no | You have documented proof that the damage predated your tenancy, signed by Victor himself |
| `a07-cookie-day-allergy` | owner | yes | yes | no | According to your notes, Jordan has a peanut allergy |
| `a07-cookie-day-allergy` | session | yes | no | yes | An unconfirmed note indicates that Jordan has a peanut allergy |
| `a07-cookie-day-allergy` | baseline_session | yes | yes | no | your notes confirm Jordan has a peanut allergy |
| `a08-one-volunteer-slot` | owner | yes | yes | no | You established a clear boundary with Rosa in September that work limits you to one volunteer slot per month this fall. |
| `a08-one-volunteer-slot` | session | yes | yes | yes | An unconfirmed note says that in September you told Rosa you could only commit to one volunteer slot per month this fall |
| `a08-one-volunteer-slot` | baseline_session | yes | yes | no | You established a clear boundary with Rosa in September that you can only manage one volunteer slot per month this fall |
| `a09-cancel-at-renewal` | owner | yes | yes | no | Your notes state that you decided to cancel the Pro plan at renewal and switch to the free tier, but the cancellation has not been submitted yet. |
| `a09-cancel-at-renewal` | session | yes | yes | yes | An unconfirmed note says that you decided to cancel the Pro plan at renewal and move to the free tier |
| `a09-cancel-at-renewal` | baseline_session | yes | yes | no | Your notes show you decided to cancel the Pro plan and downgrade to the free tier, but the cancellation request has not been submitted yet. |
| `a10-pending-refund` | owner | yes | yes | no | as your notes mention it has not yet appeared on your card |
| `a10-pending-refund` | session | yes | no | yes | An unconfirmed note states that Lena agreed by phone to a $120 refund for late delivery that has not yet posted to your card. |
| `a10-pending-refund` | baseline_session | yes | no | no | bring up the $120 refund Lena promised by phone since it has not appeared on your card yet |
| `a11-deposit-cap` | owner | yes | yes | no | Your notes record that Bram agreed to a 20% deposit capped at $1,200, with the remaining balance due upon completion. |
| `a11-deposit-cap` | session | yes | no | yes | An unconfirmed note records that Bram previously agreed to a 20% deposit capped at $1,200 |
| `a11-deposit-cap` | baseline_session | yes | yes | no | Your agreed terms with Bram were a 20% deposit capped at $1,200, with the remainder due upon completion. |
| `a12-dinner-headcount` | owner | yes | yes | no | Your note indicates that Riley cannot make it and only you will be attending Saturday's dinner. |
| `a12-dinner-headcount` | session | yes | no | yes | An unconfirmed note states that Riley cannot make it to Saturday's dinner and only you are coming. |
| `a12-dinner-headcount` | baseline_session | yes | yes | no | Your notes confirm that Riley cannot make it and you are attending alone. |
