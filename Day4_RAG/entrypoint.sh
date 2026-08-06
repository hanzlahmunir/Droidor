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
        # Fail loudly rather than starting a UI that cannot load a corpus.
        echo "ERROR: the documents API did not become ready in 120s." >&2
        exit 1
    fi
    sleep 2
done

# Verify the UI's imports resolve the way STREAMLIT will resolve them, not the
# way this shell does.
#
# This check exists because Day 3's UI shipped broken once. `streamlit run
# app/ui.py` puts the script's directory (/app/app) on sys.path rather than
# the working directory, so `from app.config import Config` raised
# ModuleNotFoundError -- but only inside Streamlit. Every other check passed:
# the CLI worked, the tests passed, and `python -c "import app.config"` in the
# same container succeeded. Streamlit then started successfully and rendered
# the traceback into the PAGE, so the container looked healthy and the logs
# looked clean.
#
# `-c` with a chdir into the script's directory reproduces Streamlit's import
# context exactly. Failing here stops the container with a readable error
# instead of serving a broken page.
echo "Verifying the UI's imports..."
if ! (cd /app/app && python -c "import app.ui" >/dev/null 2>&1); then
    echo "ERROR: app/ui.py cannot import its own package." >&2
    echo "       PYTHONPATH is '${PYTHONPATH:-unset}' and must include /app." >&2
    (cd /app/app && python -c "import app.ui") >&2 || true
    exit 1
fi

# Report whether the corpus has been ingested yet.
#
# An empty collection is the expected state on a first `up` -- ingestion is a
# separate, deliberate command -- but a UI that answers "I don't know" to
# everything because nothing was ingested looks identical to one whose
# retrieval is broken. Saying so here, in the logs, separates those two.
python -c "
from app.config import Config
from app.storage import open_collection
try:
    count = open_collection(Config()).count()
except Exception as exc:
    print(f'Could not open the vector store: {exc}')
else:
    if count:
        print(f'Vector store ready: {count} chunks indexed.')
    else:
        print('Vector store is EMPTY -- run: docker compose run --rm rag ingest')
" || true

echo "Starting the UI on http://localhost:8501"
# exec so Streamlit becomes PID 1 and receives Docker's stop signals directly,
# rather than being orphaned behind a bash wrapper.
exec streamlit run app/ui.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
