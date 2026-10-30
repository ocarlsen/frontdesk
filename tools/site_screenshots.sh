#!/bin/zsh
# Regenerates docs/site/frontdesk-list.jpg (820 CSS px wide, the About page hero) and
# frontdesk-thread.jpg (760 wide) from the synthetic static demo, at 2x, with tools/capture.mjs
# (Playwright's Chromium; run `npm ci` in tests/e2e once). Heights follow the staged content, so
# check the pages' <img> width/height after a run. No network, no model, no real mail.
# Usage: tools/site_screenshots.sh   (FRONTDESK_PYTHON overrides the interpreter)
set -euo pipefail
cd "${0:A:h}/.."
py=${FRONTDESK_PYTHON:-}
if [[ -z $py ]]; then
  py=.venv/bin/python
  [[ -x $py ]] || py="$(git rev-parse --git-common-dir)/../.venv/bin/python"
fi
out=$(mktemp -d)
FRONTDESK_HOME="$out/home" PYTHONPATH=. "$py" -m frontdesk export-demo "$out/site" >/dev/null
port=8823
"$py" -m http.server $port --bind 127.0.0.1 --directory "$out/site" >/dev/null 2>&1 &
srv=$!
trap 'kill $srv 2>/dev/null; command rm -rf "$out"' EXIT
for i in {1..50}; do curl -sf -o /dev/null "http://127.0.0.1:$port/index.html" && break; sleep 0.1; done
node tools/capture.mjs "http://127.0.0.1:$port/index.html" docs/site/frontdesk-list.jpg 820 auto \
  tools/site_screenshots/list.js
node tools/capture.mjs "http://127.0.0.1:$port/index.html" docs/site/frontdesk-thread.jpg 760 auto \
  tools/site_screenshots/thread.js
