# Pin to 3.12, matching Days 1-3: stable, and has wheels for torch and
# chromadb (the host's 3.14 is too new for some of them).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # UTF-8 everywhere. This container prints article titles and quoted text
    # scraped from arbitrary sites; without this, one em-dash in a headline
    # raises UnicodeEncodeError from inside print(). Same bug Day 2 hit.
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8

WORKDIR /app

# Install the CPU-only torch FIRST, from PyTorch's CPU index.
#
# This is the single biggest thing in the image and worth the extra layer.
# pip's default resolver pulls the CUDA build of torch -- roughly 2.5GB of
# NVIDIA libraries that cannot be used here, since neither CI nor a laptop
# container has a GPU. The CPU wheel is ~200MB.
#
# It is a separate RUN, before requirements.txt, so that this large download
# is cached independently: editing any other dependency does not re-fetch
# torch. The version matches the pin in requirements.txt, so the install below
# is satisfied by what is already here and does not reinstall it.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.5.1

# requirements next so the pip layer caches and only reinvalidates when
# dependencies actually change, not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image.
#
# Without this the model (~90MB) downloads from Hugging Face on first use,
# which means: `ask` has a slow first run that looks like a hang, an offline
# machine fails at query time rather than build time, and every container
# start re-downloads unless a cache volume is mounted. Downloading at build
# time makes the image self-contained and the runtime behaviour honest.
#
# ARG rather than ENV so it does not persist into the running container as a
# stale value if config changes; the default matches app/config.py.
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
ENV HF_HOME=/opt/hf
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('${EMBEDDING_MODEL}')" \
    && chmod -R a+rX /opt/hf

# Offline mode is set AFTER the download, not before.
#
# Setting it above would be self-defeating: the RUN line that populates the
# cache is itself a download, so an offline flag ahead of it fails the build.
# (It did, once -- the error is worth keeping in mind because "make it
# offline" reads like a property of the image rather than of a point in it.)
#
# From here on the model is present, so any attempt to reach Hugging Face
# means something is wrong. Without these, a runtime lookup fails SLOWLY --
# retries and timeouts -- and emitted "Permission denied" warnings on every
# run, because the non-root user cannot write cache metadata into /opt/hf.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    # Chroma's telemetry is disabled in code as well
    # (Settings(anonymized_telemetry=False)), but it still constructs its
    # telemetry client and logs a failure per call. This silences the second
    # path to the same decision.
    ANONYMIZED_TELEMETRY=False

# Required by the UI, and NOT redundant with WORKDIR.
#
# `streamlit run app/ui.py` puts the SCRIPT's directory (/app/app) on
# sys.path, not the working directory -- so `from app.config import Config`
# raised "ModuleNotFoundError: No module named 'app'", while the identical
# import worked fine from `python -c` in the same container. Day 3 shipped a
# broken UI once for exactly this reason.
#
# Placed AFTER the pip layers on purpose: an ENV line above them invalidates
# the dependency cache, so every edit would re-download torch.
ENV PYTHONPATH=/app

COPY . .

# Strip Windows carriage returns before chmod. A CRLF entrypoint makes the
# shebang "bash\r", which Linux cannot find -> container exits 127. The repo's
# .gitattributes forces LF as well; this is the belt to that pair of braces,
# and it is here because Day 1 lost time to exactly this.
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# Run as a non-root user. This container parses article text fetched from
# arbitrary hosts and sends it to an LLM; none of that needs root.
#
# The Chroma directory is created and owned here because it is a mounted
# volume: Docker creates a missing bind-mount target as root, and a non-root
# process then cannot write to it. Creating it in the image with the right
# owner is what makes `ingest` work on a clean checkout.
RUN useradd --create-home --shell /bin/bash rag \
    && mkdir -p /app/chroma_db /app/data/reports \
    && chown -R rag:rag /app
USER rag

EXPOSE 8501

ENTRYPOINT ["./entrypoint.sh"]
