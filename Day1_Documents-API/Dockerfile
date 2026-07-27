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

RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
