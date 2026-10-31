"""`frontdesk export-demo OUT`: the demo inbox as plain static files for any static host (GitHub
Pages at frontdesk.ocarlsen.com). No server and no secrets: the page, its script and styles, the
ranked list as JSON, each thread's people (for the People strip), and each message's HTML as its
own file, all produced by the REAL pipeline (normalize, replayed triage, ranked_payload,
people_payload, message_html) over the synthetic fixtures.

A static host cannot send response headers, so the Content-Security-Policy travels as a <meta>
tag in each page (frame-ancestors is header-only and is dropped; the iframe sandbox still
applies). Actions run in the visitor's tab only."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .demo import load_demo
from .store import Store
from .web import server

WEB = Path(__file__).parent / "web"
ABOUT = "https://ocarlsen.ai/frontdesk.html"


def _meta_csp(policy: str) -> str:
    kept = "; ".join(d.strip() for d in policy.split(";")
                     if d.strip() and not d.strip().startswith("frame-ancestors"))
    return f'<meta http-equiv="Content-Security-Policy" content="{kept}">'


def static_file(item_id: str) -> str:
    """Must match staticFile() in app.js."""
    return re.sub(r"[^A-Za-z0-9]", "-", item_id)


EVALS = Path(__file__).resolve().parents[1] / "evals"


def _export_gallery(out: Path, evals: Path = EVALS) -> bool:
    """The "Try to hijack it" page: the injection suite with each recorded model's results.
    Needs the repository's evals/ (with recordings); an installed package without it skips it."""
    from .gallery import build
    if not (evals / "hijack-gallery.json").exists():
        return False
    (out / "api" / "hijack.json").write_text(json.dumps(build(evals), ensure_ascii=False))
    page = (WEB / "hijack.html").read_text()
    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n'
                        + _meta_csp(server.CSP), 1)
    (out / "hijack.html").write_text(page)
    for name in ("hijack.js", "hijack.css"):
        shutil.copy(WEB / name, out / name)
    return True


def export_demo(out: Path, cname: str | None = None, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    exported = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if out.exists():
        shutil.rmtree(out)
    (out / "api" / "people").mkdir(parents=True)
    (out / "msg").mkdir()
    with tempfile.TemporaryDirectory(prefix="frontdesk-export-") as tmp:
        store = Store(Path(tmp) / "demo.db")
        n = load_demo(store, now=now, log=lambda *_: None)
        rows = server.ranked_payload(store)
        (out / "api" / "items.json").write_text(json.dumps(rows))
        # Same shape as GET /api/profile in demo mode: empty and read-only.
        (out / "api" / "profile.json").write_text(
            json.dumps({"profile": "", "signoff": "", "demo": True, "situation": []}))
        # Same shape as GET /api/memory in demo mode: the Memory page shows empty, read-only.
        (out / "api" / "memory.json").write_text(json.dumps(server.DEMO_MEMORY))
        meta = _meta_csp(server.MSG_CSP)
        for r in rows:
            # The People strip's data (the people half of GET /api/ask): read-only in the demo.
            item = store.get_item(r["item"]["id"])
            (out / "api" / "people" / f"{static_file(item.id)}.json").write_text(
                json.dumps({**server.people_payload(store, item), "demo": True}))
            for i, m in enumerate(r["item"]["messages"]):
                if m["has_html"]:
                    doc = server.message_html(store, r["item"]["id"], i)
                    doc = doc.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + meta, 1)
                    (out / "msg" / f"{static_file(r['item']['id'])}-{i}.html").write_text(doc)
        store.db.close()
    page = (WEB / "index.html").read_text()
    page = page.replace('<html lang="en">',
                        f'<html lang="en" data-static="1" data-exported="{exported}">', 1)
    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n'
                        + _meta_csp(server.CSP), 1)
    page = page.replace('<header class="top">', (
        '<p class="demo-banner">Live demo with a synthetic inbox: every person and address is '
        f'made up. <a href="{ABOUT}">About FrontDesk</a> \u00b7 '
        '<a href="hijack.html">Try to hijack it</a></p>\n<header class="top">'), 1)
    (out / "index.html").write_text(page)
    for name in ("app.js", "app.css"):
        shutil.copy(WEB / name, out / name)
    _export_gallery(out)
    (out / ".nojekyll").write_text("")
    if cname:
        (out / "CNAME").write_text(cname + "\n")
    return n
