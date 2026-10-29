"""Runs the page script against a stub DOM (tests/js_smoke.mjs): catches runtime errors that a
syntax check cannot, like using a const before its declaration."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_script_builds_a_thread_view():
    r = subprocess.run(["node", str(Path(__file__).parent / "js_smoke.mjs")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[-800:]
    assert "js smoke ok" in r.stdout
