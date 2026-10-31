"""The "Try to hijack it" gallery: every attack in the injection suite, the planted text marked,
and what each recorded model actually did with it. Built from evals/hijack-gallery.json (groups
and planted quotes), the case files, and evals/injection/recordings/<model>.json (written by
`frontdesk eval --suite injection --record`). Synthetic mail only; nothing here calls a model."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from .evaluate import display_model

# Gallery order of models: the default first, then by the scoreboard's cost order.
MODEL_ORDER = ("claude-opus-5-5", "claude-sonnet-5", "claude-opus-5", "claude-fable-5-1")


def _part_text(payload: dict) -> str:
    """The message as the attacker wrote it: the text/plain part if there is one, else the HTML
    source (shown as source, so hidden tricks are visible), decoded."""
    found: dict[str, str] = {}

    def walk(p: dict) -> None:
        data = (p.get("body") or {}).get("data")
        mime = p.get("mimeType", "")
        if data and mime in ("text/plain", "text/html") and mime not in found:
            found[mime] = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", "replace")
        for c in p.get("parts") or []:
            walk(c)

    walk(payload)
    return found.get("text/plain") or found.get("text/html", "")


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def case_view(case: dict) -> dict:
    """The thread as the gallery shows it: each message's sender, subject, date and raw text,
    and whether it is HTML source."""
    msgs = []
    for m in case["thread"]["messages"]:
        p = m.get("payload", {})
        h = _headers(p)
        text = _part_text(p)
        msgs.append({"from": h.get("from", ""), "subject": h.get("subject", ""),
                     "date": h.get("date", ""), "text": text,
                     "html_source": text.lstrip().lower().startswith("<html")})
    return {"messages": msgs}


def build(root: Path) -> dict:
    """The gallery's data: groups of cases, each with its thread, what the attack wanted, the
    checks, and every recorded model's result. Raises if a planted quote is not in the thread
    (the page highlights it, so it must be exact) or a recording is for another prompt."""
    root = Path(root)
    meta = json.loads((root / "hijack-gallery.json").read_text())
    rec_dir = root / "injection" / "recordings"
    recs = {}
    for name in MODEL_ORDER:
        p = rec_dir / f"{name}.json"
        if p.exists():
            recs[name] = json.loads(p.read_text())
    if len({r["prompt_version"] for r in recs.values()}) > 1:
        raise ValueError("recordings span prompt versions; re-record them together")
    models = [{"key": k, "name": display_model(k), "recorded_at": r["recorded_at"],
               "prompt_version": r["prompt_version"],
               "resisted": sum(c["passed"] for c in r["cases"].values()),
               "total": len(r["cases"])} for k, r in recs.items()]
    groups = []
    for g in meta["groups"]:
        cases = []
        for c in g["cases"]:
            case = json.loads((root / "injection" / f"{c['id']}.json").read_text())
            view = case_view(case)
            alltext = "\n".join(m["subject"] + "\n" + m["text"] for m in view["messages"])
            for q in c["planted"]:
                if q not in alltext:
                    raise ValueError(f"{c['id']}: planted quote not found: {q!r}")
            exp = case["expect"]
            results = {}
            for k, r in recs.items():
                got = r["cases"].get(c["id"])
                if got is None:
                    continue
                results[k] = {f: got.get(f) for f in ("ok", "passed", "error", "bucket",
                                                      "urgency", "reason", "summary",
                                                      "proposed_reply", "unsupported")}
            cases.append({"id": c["id"], "planted": c["planted"], "wanted": exp["reason"],
                          "bucket_in": exp["bucket_in"],
                          "reply_must_not_contain": exp.get("reply_must_not_contain", []),
                          "thread": view, "results": results})
        groups.append({"key": g["key"], "title": g["title"], "about": g["about"],
                       "cases": cases})
    return {"models": models, "groups": groups}
