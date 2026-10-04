#!/usr/bin/env bash
# Usage: ADMIN_TOKEN=... ./examples/import.sh examples/support-triage.json [http://localhost:8002]
# Edit the "CHANGE-ME" model aliases first (they must exist under Connections).
set -euo pipefail
file="$1"; base="${2:-http://localhost:8002}"
id=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['id'])" "$file")
curl -fsS -X PUT "$base/admin/routers/$id" \
  -H "Authorization: Bearer ${ADMIN_TOKEN:-}" -H "Content-Type: application/json" --data @"$file"
echo
