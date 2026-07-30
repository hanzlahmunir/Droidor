# Python 3.12, matching Day 1 and CI. The host runs 3.14, which is too new for
# some wheels; pinning here keeps local, container and CI identical.
FROM python:3.12-slim

# PYTHONUNBUFFERED is REQUIRED, not cosmetic: without it Python block-buffers
# stdout when it is not a TTY, and streamed tokens would appear in bursts at
# the end instead of arriving one at a time -- destroying the whole point of
# the streaming output.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Model replies contain emoji and non-Latin text. Without a UTF-8 locale
    # the container's default ASCII codec raises UnicodeEncodeError from inside
    # print() and kills the chat -- the same bug that hit the Windows console.
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8

WORKDIR /app

# Dependencies first, in their own layer, so editing source does not force a
# reinstall on every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY benchmark.py compare.py pytest.ini ./
COPY tests/ ./tests/

# Cost logs and transcripts are written here. Mounted as a volume in
# docker-compose.yml so they survive the container being removed.
RUN mkdir -p logs

# Run as a non-root user. This container fetches attacker-influenced URLs and
# evaluates model-written expressions; if either guard were ever bypassed, the
# blast radius should not include root.
RUN useradd --create-home --uid 1000 chatuser \
    && chown -R chatuser:chatuser /app
USER chatuser

# ENTRYPOINT (not CMD) so arguments passed to `docker compose run --rm chat`
# are appended to the command rather than replacing it. That is what makes
#     docker compose run --rm chat --mode simple
# work. With CMD, "--mode simple" would replace the whole command and the
# container would try to execute a binary called "--mode".
#
# The tests/benchmark services override this with `entrypoint:` in
# docker-compose.yml.
ENTRYPOINT ["python", "-m", "app.cli"]
