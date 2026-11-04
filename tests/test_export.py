"""The static demo export: complete, self-contained, and carrying only synthetic data."""
from __future__ import annotations

import json
import re

from frontdesk.export import export_demo, static_file


def test_export_is_complete_and_synthetic(tmp_path):
    out = tmp_path / "site"
    assert export_demo(out, cname="frontdesk.example.com") == 24
    rows = json.loads((out / "api" / "items.json").read_text())
    assert len(rows) == 24
    slack = [r for r in rows if r["item"]["source"] == "slack"]
    assert len(slack) == 4
    assert {r["item"]["labels"][1] for r in slack} == {"dm", "group_dm", "channel"}
    for r in rows:
        for i, m in enumerate(r["item"]["messages"]):
            assert (out / "msg" / f"{static_file(r['item']['id'])}-{i}.html").exists() \
                == m["has_html"]
    page = (out / "index.html").read_text()
    assert 'data-static="1"' in page and 'http-equiv="Content-Security-Policy"' in page
    assert "frame-ancestors" not in page          # header-only directive, ignored in meta
    msg = next((out / "msg").glob("*.html")).read_text()
    assert "script-src 'none'" in msg
    assert (out / "CNAME").read_text().strip() == "frontdesk.example.com"
    assert (out / ".nojekyll").exists() and (out / "app.js").exists()
    # nothing but reserved example domains in any address or link host
    blob = "".join(p.read_text() for p in out.rglob("*") if p.is_file()
                   and p.suffix in (".json", ".html"))
    addrs = re.findall(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", blob)
    assert addrs and all(re.search(r"example\.(com|org|net)$", d) for d in addrs)
    assert "token" not in (out / "index.html").read_text().lower()
    # every link host in the list is Gmail's (Open in Gmail) or a reserved example host; the
    # Slack threads' links stay in the made-up workspace, never a real one
    hosts = set(re.findall(r"https?://([\w.-]+)", (out / "api" / "items.json").read_text()))
    assert "examplecorp.example.com" in hosts
    assert all(h == "mail.google.com" or re.search(r"(^|\.)example\.(com|org|net)$", h)
               for h in hosts), hosts
    assert "slack.com" not in blob
    # the People strip's data per thread: the people half of /api/ask, read-only, no history
    for r in rows:
        ppl = json.loads((out / "api" / "people" / f"{static_file(r['item']['id'])}.json")
                         .read_text())
        assert set(ppl) == {"people", "notes", "aliases", "names", "display", "demo"}
        assert ppl["demo"] is True and ppl["notes"] == {}
    assert any(r["item"]["source"] == "slack" and json.loads(
        (out / "api" / "people" / f"{static_file(r['item']['id'])}.json").read_text())["display"]
        for r in rows)                                 # Slack keys come with display names


def test_static_file_names_match_the_page_script():
    js = (__import__("pathlib").Path(__file__).parents[1] / "frontdesk/web/app.js").read_text()
    assert 'itemId.replace(/[^A-Za-z0-9]/g, "-")' in js
    assert static_file("gmail:18c2f") == "gmail-18c2f"


def test_export_shows_web_images_only_on_request_and_only_its_own(tmp_path):
    out = tmp_path / "site"
    export_demo(out)
    plain = sorted(p for p in (out / "msg").glob("*.html") if not p.stem.endswith("-images"))
    assert plain and all(p.with_name(p.stem + "-images.html").exists() for p in plain)
    news = next(p for p in plain if "frontdesk.ocarlsen.com/img/" in p.read_text())
    assert "img-src data:;" in news.read_text()
    assert "img-src data: https:;" in news.with_name(news.stem + "-images.html").read_text()
    # Every web image any demo mail points at is the demo's own, and is exported.
    blob = "".join(p.read_text() for p in plain)
    srcs = set(re.findall(r'src="(https?://[^"]+)"', blob))
    assert srcs and all(s.startswith("https://frontdesk.ocarlsen.com/img/") for s in srcs), srcs
    for s in srcs:
        assert (out / "img" / s.split("/img/")[1].split("?")[0]).is_file(), s
