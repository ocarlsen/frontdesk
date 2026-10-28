"""The static demo export: complete, self-contained, and carrying only synthetic data."""
from __future__ import annotations

import json
import re

from frontdesk.export import export_demo, static_file


def test_export_is_complete_and_synthetic(tmp_path):
    out = tmp_path / "site"
    assert export_demo(out, cname="frontdesk.example.com") == 20
    rows = json.loads((out / "api" / "items.json").read_text())
    assert len(rows) == 20
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


def test_static_file_names_match_the_page_script():
    js = (__import__("pathlib").Path(__file__).parents[1] / "frontdesk/web/app.js").read_text()
    assert 'itemId.replace(/[^A-Za-z0-9]/g, "-")' in js
    assert static_file("gmail:18c2f") == "gmail-18c2f"
