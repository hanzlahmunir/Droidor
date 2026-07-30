#!/bin/bash
# Creates the crawler's bookkeeping database alongside Day 1's `documents`.
#
# Postgres runs everything in /docker-entrypoint-initdb.d exactly once: on
# first boot, while the data directory is empty. It will NOT run again on
# later starts, so this cannot clobber an existing database.
#
# WHY TWO DATABASES ON ONE SERVER, rather than two schemas or two servers:
#   - Two servers would double the memory for no benefit at this size.
#   - One database shared would let a `DROP TABLE` in crawler bookkeeping sit
#     next to the documents table, and would blur who owns what.
#   - Two databases give a clean ownership line: Day 1 owns `documents` and
#     migrates it; the crawler owns `crawler` and can drop and rebuild it.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE crawler;
    GRANT ALL PRIVILEGES ON DATABASE crawler TO $POSTGRES_USER;
EOSQL

echo "Created the 'crawler' database."
