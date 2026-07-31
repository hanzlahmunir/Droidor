# Pin to 3.12, matching Day 1 and Day 2: stable, and has wheels for lxml and
# psycopg (the host's 3.14 is too new for some of them).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # UTF-8 everywhere. This container prints article titles scraped from
    # arbitrary sites; without this, one em-dash in a headline raises
    # UnicodeEncodeError from inside print(). Same bug Day 2 hit.
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8

WORKDIR /app

# lxml needs libxml2/libxslt at build time. Installed and then removed in the
# same layer so the build tools do not ship in the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements first so the pip layer caches and only reinvalidates when
# dependencies actually change, not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# Required by the UI, and NOT redundant with WORKDIR.
#
# `streamlit run app/ui.py` puts the SCRIPT's directory (/app/app) on
# sys.path, not the working directory -- so `from app.config import Config`
# raised "ModuleNotFoundError: No module named 'app'", while the identical
# import worked fine from `python -c` in the same container. That difference
# is why the CLI, the tests and my own import checks all passed while the UI
# was broken. See docs/REVIEW_NOTES.md.
#
# Set here rather than in entrypoint.sh so `docker run` and `compose exec`
# behave the same as `compose up`.
#
# Placed AFTER the pip layer on purpose: an ENV line above it invalidates the
# dependency cache, so every edit to it triggers a full reinstall of lxml,
# trafilatura and streamlit. Down here it costs nothing to change.
ENV PYTHONPATH=/app

COPY . .

# Strip Windows carriage returns before chmod. A CRLF entrypoint makes the
# shebang "bash\r", which Linux cannot find -> container exits 127. The repo's
# .gitattributes forces LF as well; this is the belt to that pair of braces,
# and it is here because Day 1 lost time to exactly this.
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# Run as a non-root user. This container fetches attacker-influenced HTML from
# arbitrary hosts and parses it with lxml; a parser bug should not land on a
# root shell.
RUN useradd --create-home --shell /bin/bash crawler \
    && mkdir -p /app/data \
    && chown -R crawler:crawler /app
USER crawler

EXPOSE 8501

ENTRYPOINT ["./entrypoint.sh"]
