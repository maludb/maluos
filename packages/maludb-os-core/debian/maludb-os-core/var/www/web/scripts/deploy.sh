#!/usr/bin/env bash
# Build as the deploy user, hand .next to the service user, restart, wait until it answers.
set -euo pipefail
cd "$(dirname "$0")/.."
sudo -n chown -R "$(id -un)":"$(id -gn)" .next
npm run build 2>&1 | grep -E "rror|✓ Compiled|Failed|Type error" | grep -v "env.local\|EACCES" || true
sudo -n chown -R www-data:www-data .next
sudo -n systemctl restart maludb-os-web
for _ in $(seq 1 20); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/login)" = 200 ] && { echo "web up"; exit 0; }
  python3 -c "import time; time.sleep(1)"
done
echo "web did NOT come up"; exit 1
