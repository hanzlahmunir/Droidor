# Pin to 3.12: stable, has wheels for psycopg/pydantic (the host's 3.14 is too
# new for some wheels). The container guarantees the runtime, so it doesn't
# matter what Python the developer has locally.
FROM python:3.12-slim

# Faster, cleaner logs: no .pyc files, unbuffered stdout so Docker shows logs
# in real time.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first so Docker caches the pip layer and only reinstalls
# when requirements.txt actually changes (not on every code edit).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now the app code.
COPY . .

# Strip any Windows carriage returns and make it executable. A CRLF entrypoint
# turns the shebang into `bash\r`, which Linux can't find -> the container exits
# 127 ("command not found"). This line makes the build robust even if someone
# clones on Windows with core.autocrlf=true. (.gitattributes also forces LF.)
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
