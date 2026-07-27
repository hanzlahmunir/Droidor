"""Shared Neo4j connection helper with an SSL-verification fallback.

Aura uses ``neo4j+s://`` (strict TLS cert verification). On some machines —
notably Windows behind a proxy or with an intercepting cert in the local chain —
strict verification fails with ``self-signed certificate in certificate chain``.
In that case we retry with ``neo4j+ssc://``, which is still encrypted but tolerant
of a self-signed cert. Strict is tried first so secure setups stay strict.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

from logging_setup import get_logger

load_dotenv()
log = get_logger(__name__)


def get_neo4j_graph():
    """Return a connected langchain_neo4j.Neo4jGraph, falling back to +ssc on SSL error."""
    from langchain_neo4j import Neo4jGraph

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "testpassword")
    # Aura's database is often NOT named 'neo4j' (it can be the instance id).
    # Default to None so the driver uses the server's home database if unset.
    database = os.getenv("NEO4J_DATABASE") or None

    try:
        return Neo4jGraph(url=uri, username=user, password=pwd, database=database)
    except Exception as exc:
        # langchain_neo4j masks the underlying SSL cert error as a generic
        # "Could not connect" / ServiceUnavailable, so we can't rely on the
        # message. For a strict +s Aura URI, retry once with +ssc (encrypted,
        # tolerant of a self-signed cert in the local chain).
        if uri.startswith("neo4j+s://"):
            ssc_uri = uri.replace("neo4j+s://", "neo4j+ssc://")
            log.warning("Neo4j connect failed (%s); retrying with %s", type(exc).__name__, ssc_uri)
            return Neo4jGraph(url=ssc_uri, username=user, password=pwd, database=database)
        raise
