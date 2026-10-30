"""The live FrontDesk server on the synthetic demo inbox, for the browser tests' Ask checks.

    python tests/e2e/live_server.py

Prints one JSON line, {"live": URL}, then serves on 127.0.0.1 until stdin closes (the test
runner's global setup starts it as a child and closes stdin in teardown).

Same settings as `frontdesk demo` ({"demo": True}: sync, profile and Ask's model calls are off),
on a throwaway store in a temp FRONTDESK_HOME. FD_E2E_APP_JS=<file> serves that file as app.js
(a red proof against another version of the page, as for the static demo). Ask's model list is stubbed empty, so nothing
asks the Keychain whether a key exists, and nothing here calls a model. The real ~/.frontdesk is
never read: FRONTDESK_HOME is set before frontdesk.config is imported, and the script refuses to
run if that did not take."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="fd-e2e-live-"))
    home = work / "home"
    os.environ["FRONTDESK_HOME"] = str(home)
    sys.path.insert(0, str(ROOT))
    from frontdesk import config
    if Path(config.HOME) != home:
        raise SystemExit("frontdesk.config did not pick up the temp FRONTDESK_HOME; refusing")
    from frontdesk.demo import load_demo
    from frontdesk.store import Store
    from frontdesk.web import server
    config.ensure_home()
    server.available_models = lambda _settings: []   # no Keychain lookups for Ask's model list
    if os.environ.get("FD_E2E_APP_JS"):
        web = work / "web"
        shutil.copytree(server.STATIC_DIR, web, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
        shutil.copyfile(os.environ["FD_E2E_APP_JS"], web / "app.js")
        server.STATIC_DIR = web
    db = work / "e2e.db"
    st = Store(db)
    load_demo(st, now=datetime.now(UTC))
    st.db.close()
    app = server.make_server(Store(db), "127.0.0.1", 0, settings={"demo": True})
    threading.Thread(target=app.serve_forever, daemon=True).start()
    print(json.dumps({"live": f"http://127.0.0.1:{app.server_address[1]}/index.html"}),
          flush=True)
    try:
        sys.stdin.read()          # until the parent closes our stdin
    finally:
        app.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
