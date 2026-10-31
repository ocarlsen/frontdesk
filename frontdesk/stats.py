"""`frontdesk stats`: what FrontDesk did and what it cost, from the usage log (counts and costs
only, no mail). Drafts and sends say whether they went out as FrontDesk wrote them."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from .store import Store

ORIGIN_LABEL = {"proposed": "as FrontDesk proposed", "ask_draft": "as Ask drafted",
                "edited": "edited", "written": "written from scratch"}


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _cents(total: float, n: int) -> str:
    return f"{100 * total / n:.2f}¢ each" if n else ""


def render(summary: dict) -> str:
    kinds = summary["kinds"]
    if not kinds:
        return "No usage logged yet. It starts with the next ranking, Ask, draft or send."
    first = summary["first"][:10]
    since = summary["since"][:10] if summary["since"] else first
    lines = [f"FrontDesk usage since {since}" + (f" (first logged {first})"
                                                  if summary["since"] and first > since else "")]

    def row(label: str, kind: str, unit: str) -> None:
        k = kinds.get(kind)
        if not k:
            return
        cost = (f"  {_money(k['cost_usd'])}  {_cents(k['cost_usd'], k['n'])}"
                if k["cost_usd"] else "")
        lines.append(f"  {label:<13}{k['n']:>5} {unit}{cost}")
        for model, m in sorted(k["models"].items(), key=lambda kv: -kv[1]["n"]):
            if len(k["models"]) > 1 or m["cost_usd"]:
                lines.append(f"  {'':<13}{m['n']:>5} on {model}  {_money(m['cost_usd'])}")
        if k["origins"]:
            n = k["n"]
            parts = [f"{v} {ORIGIN_LABEL.get(o, o)} ({100 * v / n:.0f}%)"
                     for o, v in sorted(k["origins"].items(), key=lambda kv: -kv[1])]
            lines.append(f"  {'':<13}      " + ", ".join(parts))

    row("Ranked", "rank", "threads")
    row("Ask", "ask", "answers")
    row("Drafts saved", "draft", "drafts")
    row("Sent", "send", "replies")
    row("Searches", "search", "all-of-Gmail searches")
    row("Kept", "keep", "threads from search")
    total = sum(k["cost_usd"] for k in kinds.values())
    lines.append(f"  {'Model cost':<13}{_money(total):>5} paid to your provider")
    return "\n".join(lines)


def main(store: Store, days: int | None = None, as_json: bool = False) -> int:
    since = ""
    if days is not None:
        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = store.usage_summary(since)
    print(json.dumps(summary, indent=1) if as_json else render(summary))
    return 0
