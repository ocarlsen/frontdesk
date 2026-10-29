#!/bin/zsh
# Regenerates docs/site/frontdesk-list.jpg and frontdesk-thread.jpg from the synthetic demo, with
# headless Chrome at 2x (the page shows them at 760x812). No network, no model, no real mail.
# Usage: tools/site_screenshots.sh
set -euo pipefail
cd "${0:A:h}/.."
out=$(mktemp -d)
bin/frontdesk export-demo "$out/site" >/dev/null
cp tools/site_screenshots/shot.js "$out/site/shot.js"
sed 's|<script src="app.js" defer></script>|&<script src="shot.js" defer></script>|' \
  "$out/site/index.html" > "$out/site/thread.html"
python3 -m http.server 8823 --bind 127.0.0.1 --directory "$out/site" >/dev/null 2>&1 &
srv=$!
trap 'kill $srv 2>/dev/null; command rm -rf "$out"' EXIT
sleep 1
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for name page in list index thread thread; do
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --window-size=760,812 --virtual-time-budget=6000 --screenshot="$out/$name.png" \
    "http://127.0.0.1:8823/$page.html" >/dev/null 2>&1
  sips -s format jpeg -s formatOptions 82 "$out/$name.png" --out "docs/site/frontdesk-$name.jpg" >/dev/null
done
echo "wrote docs/site/frontdesk-list.jpg and frontdesk-thread.jpg"
