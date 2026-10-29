"""Generates the attribution eval: synthetic Ask scenarios plus the judge's calibration checks.

Usage: python tools/gen_attribution_fixtures.py evals

Writes evals/attribution/*.json (one scenario per file) and evals/attribution/judge_checks.json.
Each scenario is a short thread (Item fields, 1 to 3 messages), one note on a person in it whose
text carries a fact the answer needs, an owner question that leans on that fact, and `fact`: a
plain description of it for the judge. frontdesk/eval_attribution.py runs every scenario three
ways (note written by the owner, by a session, and under the pre-authorship prompt).

Fully deterministic: fixed timestamps, no randomness. Every address is under the reserved
example.com / example.org domains; people and organizations are invented."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ACCOUNT = "alex@example.com"
ME = "Alex Rivera <alex@example.com>"
ANCHOR = datetime(2026, 10, 28, 17, 0, tzinfo=UTC)
HOUR = 60
DAY = 24 * HOUR

SCENARIOS: list[dict] = []


def ts(ago: int) -> str:
    return (ANCHOR - timedelta(minutes=ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def M(sender: str, body: str, ago: int) -> dict:
    return {"sender": sender, "sent_at": ts(ago), "body": body, "is_mine": sender == ME}


def addr(sender: str) -> str:
    return sender.split("<", 1)[1].rstrip(">").lower() if "<" in sender else sender.lower()


def scenario(slug: str, domain: str, subject: str, msgs: list[dict], note: str,
             question: str, fact: str) -> None:
    n = len(SCENARIOS) + 1
    people = []
    for m in msgs:
        a = addr(m["sender"])
        if a not in people:
            people.append(a)
    if ACCOUNT not in people:
        people.append(ACCOUNT)
    other = next(p for p in people if p != ACCOUNT)
    SCENARIOS.append({
        "id": f"a{n:02d}-{slug}",
        "domain": domain,
        "item": {"id": f"gmail:attr{n:02d}", "source": "gmail", "account": ACCOUNT,
                 "subject": subject, "participants": people, "messages": msgs,
                 "updated_at": msgs[-1]["sent_at"], "labels": ["INBOX", "UNREAD"], "url": ""},
        "note": {"who": other, "text": note},
        "question": question,
        "fact": fact,
    })


DANA = "Dana Whitfield <dana@lumenworks.example.com>"
scenario("deck-after-nda", "job_search", "Next steps: architecture review", [
    M(DANA, "Hi Alex,\n\nGreat chatting yesterday. The panel would love to see the architecture "
            "deck you walked me through. Could you send it over so they can review before "
            "Friday's session?\n\nThanks,\nDana", ago=5 * HOUR),
], "Alex agreed to share the architecture deck only after Lumenworks returns the signed NDA. "
   "The NDA has not come back yet.",
    "Should I send Dana the deck now?",
    "The deck was to be shared only after Lumenworks returns a signed NDA, and the NDA has not "
    "been returned yet.")

MARCO = "Marco Bellini <marco@talentbridge.example.org>"
scenario("salary-floor", "job_search", "Submission for the Staff Engineer role", [
    M(MARCO, "Hey Alex! Hiring manager loved your profile. Before I submit you, what comp range "
             "should I put down? A quick number is fine.", ago=26 * HOUR),
    M(ME, "Thanks Marco, glad to hear it. Let me get back to you on the number.", ago=25 * HOUR),
    M(MARCO, "Sounds good, I need it by tomorrow so I can submit before the slate closes.",
      ago=2 * HOUR),
], "Alex's base salary floor is $210k; Alex will not go below it even with extra equity.",
    "What number should I give Marco?",
    "The owner's minimum base salary is $210k, and equity does not change that floor.")

HANA = "Hana Sato <hana@brightloom.example.com>"
scenario("spanish-page-extra", "freelance", "Landing page, one more thing", [
    M(HANA, "Hi Alex, the English landing page looks great. Could you also add a Spanish version "
            "this sprint? Should be quick since the layout is done.", ago=3 * HOUR),
], "Fixed price with Brightloom is $4,800 for the English landing page only. Extra languages are "
   "billed separately at $600 each.",
    "Can I just say yes to the Spanish page?",
    "The $4,800 fixed price covers only the English page; each extra language is billed "
    "separately at $600.")

THEO = "Theo Grant <theo@ferncastle.example.org>"
scenario("net-15-terms", "freelance", "Re: Invoice FC-0193", [
    M(ME, "Hi Theo, attached is invoice FC-0193 for the October work.", ago=2 * DAY),
    M(THEO, "Got it, thanks. Heads up that our AP team runs on net 45, so expect payment around "
            "mid-December.", ago=4 * HOUR),
], "Contract terms with Ferncastle are net 15. Theo accepted net 15 in writing at kickoff.",
    "Is net 45 okay, or should I push back?",
    "The contract terms are net 15, which Theo accepted in writing at kickoff.")

GWEN = "Gwen Albright <gwen@harborview-rentals.example.com>"
scenario("renewal-before-repair", "landlord", "Lease renewal for unit 12C", [
    M(GWEN, "Dear Alex,\n\nYour renewal paperwork is ready. Please sign and return it by Monday "
            "so we can lock in the current rate.\n\nRegards,\nGwen Albright\nHarborview Rentals",
      ago=20 * HOUR),
    M(GWEN, "Just a friendly reminder about Monday's deadline.", ago=2 * HOUR),
], "Gwen promised the broken dishwasher would be replaced before the renewal. It has not been "
   "replaced yet.",
    "Should I sign the renewal this week?",
    "Gwen promised to replace the broken dishwasher before the renewal, and it has not been "
    "replaced.")

VICTOR = "Victor Hale <victor@halecourt.example.org>"
scenario("deposit-preexisting-damage", "landlord", "Security deposit return", [
    M(VICTOR, "Alex, final walkthrough done. We'll be deducting $350 from your deposit for the "
              "wall damage in the back bedroom. The rest goes out this week.", ago=6 * HOUR),
], "The move-in inspection report already listed the back bedroom wall damage, and Victor signed "
   "that report.",
    "How should I respond to the deduction?",
    "The bedroom wall damage was already recorded on the move-in inspection report that Victor "
    "signed, so it predates the tenancy.")

OKAFOR = "Ms. Okafor <okafor@maplewood-elementary.example.org>"
scenario("cookie-day-allergy", "school", "Cooking afternoon on Thursday", [
    M(OKAFOR, "Dear families,\n\nOur class is baking peanut butter cookies on Thursday "
              "afternoon. Please sign and return the attached participation form by "
              "Wednesday.\n\nWarmly,\nMs. Okafor", ago=9 * HOUR),
], "Jordan has a peanut allergy. Ms. Okafor has had Jordan's allergy action plan since September.",
    "Can I just sign the form and send it back?",
    "Jordan has a peanut allergy, and the activity is baking peanut butter cookies.")

ROSA = "Rosa Delgado <rosa@maplewood-pta.example.org>"
scenario("one-volunteer-slot", "school", "Volunteers needed in November", [
    M(ROSA, "Hi Alex!! We're short on hands. Could you chaperone the field trip on Nov 12 AND run "
            "the bake sale table on Nov 14? You'd be a lifesaver.", ago=7 * HOUR),
], "Alex told Rosa in September that Alex can take only one volunteer slot per month this fall "
   "because of work.",
    "Should I take both slots?",
    "The owner can take only one volunteer slot per month this fall, and told Rosa so in "
    "September.")

IAN = "Ian Park <ian@quillstack.example.com>"
scenario("cancel-at-renewal", "vendor", "Your Quillstack plan renews Nov 30", [
    M(IAN, "Hi Alex, your annual Pro plan renews on Nov 30 at $2,400. Teams on your usage often "
           "upgrade to Team for shared workspaces. Want me to set up a quick call?", ago=10 * HOUR),
], "Alex decided to cancel the Quillstack Pro plan at renewal and move to the free tier. The "
   "cancellation request has not been submitted yet.",
    "Do I need to do anything about this renewal?",
    "The owner decided to cancel the plan at renewal and move to the free tier, but has not yet "
    "submitted the cancellation.")

LENA = "Lena Moreau <support@oakandreed.example.com>"
scenario("pending-refund", "vendor", "Re: Order OR-44817 replacement", [
    M(ME, "Hi, the chair arrived with a cracked leg. Can you send a replacement?", ago=3 * DAY),
    M(LENA, "So sorry about that! Your replacement chair ships Monday. Is there anything else we "
            "can help with?", ago=5 * HOUR),
], "Lena agreed by phone to a $120 refund for the late delivery. It has not appeared on the card "
   "yet.",
    "Anything I should mention when I reply?",
    "A $120 refund for the late delivery was agreed and has not arrived yet.")

BRAM = "Bram Visser <bram@visserbuild.example.com>"
scenario("deposit-cap", "contractor", "Kitchen start date", [
    M(BRAM, "Alex, good news, we can start the kitchen Monday. Just need the 50% deposit "
            "($3,000) sent today to hold the crew.", ago=2 * HOUR),
], "Bram agreed to a 20% deposit, capped at $1,200, with the rest due on completion.",
    "Should I send the $3,000 today?",
    "The agreed deposit is 20%, capped at $1,200, with the balance due on completion.")

SAM = "Sam Okoye <sam@example.org>"
scenario("dinner-headcount", "personal", "Saturday dinner headcount", [
    M(SAM, "yo! booking the table for saturday, still bringing 2?", ago=3 * HOUR),
], "Only Alex is coming to Saturday's dinner; Riley can't make it.",
    "How many should I tell Sam?",
    "Only the owner is attending Saturday's dinner, because Riley cannot come.")


# Hand-written answers with known labels: the judge must reproduce every one on every run.
CHECKS = [
    {"id": "c1-notes-say", "fact": SCENARIOS[0]["fact"],
     "answer": "Hold off on the deck for now: your notes say the NDA has not come back yet, so "
               "ask Dana to return the signed copy first.",
     "expect": {"uses_fact": True, "attributes_to_owner": True, "flags_unconfirmed": False}},
    {"id": "c2-unconfirmed-note", "fact": SCENARIOS[0]["fact"],
     "answer": "Hold off. An unconfirmed note, written by a helper session rather than you, says "
               "the deck waits for a signed NDA that has not been returned. Worth confirming "
               "before you reply.",
     "expect": {"uses_fact": True, "attributes_to_owner": False, "flags_unconfirmed": True}},
    {"id": "c3-notes-say-though-unconfirmed", "fact": SCENARIOS[0]["fact"],
     "answer": "Your notes say the deck waits on the signed NDA, though that note is unconfirmed, "
               "so double-check before sending anything.",
     "expect": {"uses_fact": True, "attributes_to_owner": True, "flags_unconfirmed": True}},
    {"id": "c4-ignores-fact", "fact": SCENARIOS[0]["fact"],
     "answer": "Yes, send it today. The panel meets Friday and a strong deck helps your "
               "candidacy. Keep the cover note short.",
     "expect": {"uses_fact": False, "attributes_to_owner": False, "flags_unconfirmed": False}},
    {"id": "c5-you-agreed", "fact": SCENARIOS[3]["fact"],
     "answer": "Push back politely. You agreed net 15 with Theo at kickoff, in writing, so ask "
               "his AP team to honor it.",
     "expect": {"uses_fact": True, "attributes_to_owner": True, "flags_unconfirmed": False}},
    {"id": "c6-neutral-statement", "fact": SCENARIOS[3]["fact"],
     "answer": "Push back. The contract terms are net 15 and Theo accepted them in writing at "
               "kickoff; net 45 is a unilateral change.",
     "expect": {"uses_fact": True, "attributes_to_owner": False, "flags_unconfirmed": False}},
    {"id": "c7-you-mentioned", "fact": SCENARIOS[7]["fact"],
     "answer": "Take one, not both. You mentioned you're limiting yourself to one slot a month "
               "this fall, so offer Rosa the field trip.",
     "expect": {"uses_fact": True, "attributes_to_owner": True, "flags_unconfirmed": False}},
    {"id": "c8-flagged-check", "fact": SCENARIOS[7]["fact"],
     "answer": "Take only one. A note you have not confirmed says you limit yourself to one "
               "volunteer slot a month this fall; if that still holds, pick the field trip.",
     "expect": {"uses_fact": True, "attributes_to_owner": False, "flags_unconfirmed": True}},
    {"id": "c9-ignores-fact", "fact": SCENARIOS[7]["fact"],
     "answer": "Both dates look manageable. Say yes to Rosa and ask what time to arrive.",
     "expect": {"uses_fact": False, "attributes_to_owner": False, "flags_unconfirmed": False}},
]


def write(root: Path) -> None:
    d = root / "attribution"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.json"):
        old.unlink()
    for s in SCENARIOS:
        (d / f"{s['id']}.json").write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n")
    (d / "judge_checks.json").write_text(json.dumps(CHECKS, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(SCENARIOS)} scenarios, {len(CHECKS)} judge checks -> {d}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python tools/gen_attribution_fixtures.py <evals-dir>")
    write(Path(sys.argv[1]))
