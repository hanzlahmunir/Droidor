# Day 5 builds ON TOP OF the Day 4 image rather than rebuilding its own stack.
#
# WHY. The eval imports Day 4's retriever, embedder, config and answerer. Those
# are the things under measurement, so they must be the REAL ones -- if this
# image carried its own copy, the copy would drift the moment Day 4 changed and
# the score would describe code nobody runs. Same reasoning that has Day 3 and
# Day 4 build the Day 1 API from source instead of vendoring it.
#
# It also inherits the expensive parts already solved in Day 4's Dockerfile:
# the CPU-only torch wheel (~200MB instead of ~2.5GB of unusable CUDA) and the
# all-MiniLM-L6-v2 weights baked in at build time, so this image needs no
# network at run time and has no slow first query.
#
# The tag is produced by Day 5's docker-compose.yml, which builds
# ../Day4_RAG first and names it. Building this Dockerfile by hand needs that
# image to exist:
#
#     docker build -t day4_rag-base ../Day4_RAG
#     docker build -t day5_eval .
ARG DAY4_IMAGE=day4_rag-base
FROM ${DAY4_IMAGE}

# Day 4's WORKDIR is /app and its package sits at /app/app. Both are inherited,
# so `from app.retriever import retrieve` resolves to Day 4's module.
WORKDIR /app

# PYTHONPATH so pytest and eval.py both find Day 4's `app` package AND the
# Day 5 modules beside it. Day 4's entrypoint documents the Streamlit variant
# of this trap; the same class of bug applies to pytest, which inserts rootdir
# rather than the working directory.
ENV PYTHONPATH=/app

# Day 5's own files, layered over Day 4's /app. Copied last so editing a
# question or the scorer does not invalidate any dependency layer.
#
# NOTE these land beside Day 4's code, not on top of it: Day 5 adds eval.py,
# eval_set.json and tests/test_eval_script.py, and overwrites nothing. The
# tests/ directory merges -- Day 4's suite stays present and runnable, which
# is deliberate: `run --rm tests` here proves Day 5 did not break Day 4.
COPY pytest.ini /app/pytest.ini
COPY eval.py /app/eval.py
COPY eval_set.json /app/eval_set.json
COPY tests/ /app/tests/

# No ENTRYPOINT of its own. docker-compose.yml sets one per service, so the
# same image serves `eval` and `tests` without an override.
CMD ["python", "eval.py"]
