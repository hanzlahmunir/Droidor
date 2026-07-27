"""Shared embedding model.

Ingestion and the Chroma store MUST use the same embedding model, or retrieval
silently degrades. Both import ``get_embeddings`` from here so there is one
source of truth. Defaults to a small, fast, free local sentence-transformers
model; override with ``EMBEDDING_MODEL`` in ``.env``.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings

    model_name = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    return HuggingFaceEmbeddings(model_name=model_name)
