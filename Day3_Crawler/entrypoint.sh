#!/usr/bin/env bash
# Container entrypoint for the UI service.
#
# `docker compose up` must leave the user with a working system, so this waits
# for the documents API before starting Streamlit. Without the wait, the UI
# comes up first, shows "API unreachable" in red, and looks broken for the ten
# seconds Day 1 takes to run its migrations -- which is indistinguishable from
# actually being broken.
set -euo pipefail

API_URL="${API_BASE_URL:-http://api:8000}"

echo "Waiting for the documents API at ${API_URL}..."
for attempt in $(seq 1 60); do
    if python -c "
import sys, urllib.request
try:
    with urllib.request.urlopen('${API_URL}/health', timeout=2) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo "Documents API is up."
        break
    fi
    if [ "$attempt" -eq 60 ]; then
        # Fail loudly rather than starting a UI that cannot store anything.
        echo "ERROR: the documents API did not become ready in 120s." >&2
        exit 1
    fi
    sleep 2
done

# Create the crawler's own tables. Idempotent, so it is safe on every boot.
echo "Preparing the crawler database..."
python -c "from app.storage.database import create_schema; create_schema()"

echo "Starting the UI on http://localhost:8501"
# exec so Streamlit becomes PID 1 and receives Docker's stop signals directly,
# rather than being orphaned behind a bash wrapper.
exec streamlit run app/ui.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
