"""The UI module must import the way STREAMLIT imports it.

WHY THIS FILE EXISTS. The UI shipped broken. `streamlit run app/ui.py` failed
with `ModuleNotFoundError: No module named 'app'` while every other check was
green:

  - the CLI worked (run as `python -m app.cli`, so /app was on sys.path)
  - all 98 tests passed (pytest.ini sets `pythonpath = .`)
  - `docker compose exec ui python -c "import app.config"` succeeded
  - the container was healthy and `curl localhost:8501` returned HTTP 200

The cause: `streamlit run app/ui.py` prepends the SCRIPT's directory
(/app/app) to sys.path, not the working directory. So `from app.config import
Config` resolved against /app/app, where there is no `app` package.

Streamlit then started successfully and rendered the traceback INTO THE PAGE,
which is why the logs looked clean and the health check passed. The only way
to see it was to open the page -- which no automated check did.

Every test in this file therefore reproduces Streamlit's import context
rather than pytest's, by importing from inside app/ as the current directory
with only PYTHONPATH to fall back on.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = PROJECT_ROOT / "app"


def _import_from(cwd: Path, module: str, pythonpath: str | None) -> subprocess.CompletedProcess:
    """Resolve `module` in a subprocess with a controlled cwd and PYTHONPATH.

    A subprocess is required: this test is about sys.path CONSTRUCTION at
    interpreter start, and the parent pytest process already has the project
    root on sys.path (via pytest.ini). Importing in-process would pass no
    matter how broken the real entry point is -- which is exactly how this
    bug survived a green suite.

    Uses importlib.util.find_spec rather than a real `import`. That is a
    deliberate narrowing, and the first version got it wrong: `import app.ui`
    EXECUTES ui.py, whose top-level code opens a database connection and
    calls the API, so the test failed against a missing Postgres even though
    the import path was perfectly fine. It was testing two things and
    reporting the wrong one.

    find_spec answers exactly the question this file exists to ask -- "can
    Python LOCATE the app package from here?" -- and nothing else. The
    offline suite stays offline.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath

    code = (
        "import importlib.util, sys;"
        f" spec = importlib.util.find_spec({module!r});"
        " sys.exit(0 if spec is not None else 1)"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("module", ["app.ui", "app.cli", "app.config"])
def test_imports_resolve_from_the_script_directory(module):
    """The regression test proper.

    cwd is app/ -- Streamlit's import context -- with PYTHONPATH set to the
    project root, which is what the Dockerfile now provides. Without that
    env var this raises ModuleNotFoundError, which is precisely the shipped
    bug.
    """
    result = _import_from(UI_DIR, module, pythonpath=str(PROJECT_ROOT))
    assert result.returncode == 0, (
        f"`import {module}` failed from {UI_DIR} even with PYTHONPATH set:\n"
        f"{result.stderr}"
    )


def test_without_pythonpath_the_import_fails_from_the_script_directory():
    """Documents the mechanism, so the fix is not deleted as redundant.

    This asserts the BUG still reproduces when PYTHONPATH is removed. If it
    ever starts passing, the import no longer depends on PYTHONPATH and the
    Dockerfile's ENV line could be dropped -- but until then, deleting that
    line breaks the UI, and this test says so.

    find_spec RAISES ModuleNotFoundError for a missing parent package rather
    than returning None, so the non-zero exit here comes from the traceback,
    and the message is checked to prove it failed for the expected reason
    rather than some unrelated crash.
    """
    result = _import_from(UI_DIR, "app.ui", pythonpath=None)
    assert result.returncode != 0
    assert "No module named 'app'" in result.stderr


def test_ui_imports_from_the_project_root_too():
    """The ordinary case must keep working: cwd at the root, no PYTHONPATH."""
    result = _import_from(PROJECT_ROOT, "app.ui", pythonpath=None)
    assert result.returncode == 0, result.stderr


def test_dockerfile_sets_pythonpath():
    """Guards the fix at its source.

    The tests above prove the import works when PYTHONPATH is right. This one
    proves the container actually sets it -- otherwise the suite could stay
    green while the shipped image is broken, which is the exact failure this
    file was written for.
    """
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "PYTHONPATH=/app" in dockerfile, (
        "Dockerfile must set PYTHONPATH=/app or `streamlit run app/ui.py` "
        "cannot import the app package."
    )
