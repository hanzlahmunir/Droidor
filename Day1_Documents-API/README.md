# Documents API (Day 1)

A small CRUD service for documents, built with **FastAPI + Postgres**.

## Run it

```bash
cp .env.example .env
docker compose up
```

That's it. Compose starts Postgres, waits for it to be healthy, applies the
Alembic migration, and serves the API at <http://localhost:8000>.

- Interactive docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

## API

| Method | Path                                      | Notes                                   |
| ------ | ----------------------------------------- | --------------------------------------- |
| POST   | `/documents`                              | Body: `{title, url, text, source}` + optional `published_at`. Duplicate `url` → **409**. |
| GET    | `/documents/{id}`                         | 404 if not found.                       |
| GET    | `/documents?source=&limit=&offset=`       | Paginated list, optional `source` filter. |
| DELETE | `/documents/{id}`                         | 204 on success, 404 if not found.       |

### The two dates

A document carries two timestamps, and they mean different things:

| Field          | Meaning                                   | Set by                  | Nullable |
| -------------- | ----------------------------------------- | ----------------------- | -------- |
| `created_at`   | when **we** stored the row                | us, at insert           | no       |
| `published_at` | when the **author** published the article | the client, if it knows | **yes**  |

`published_at` is optional on POST. Omitting it (or sending `null`) stores
`null`, which is the honest record of "no publish date could be determined" —
the state a crawler ends up in fairly often. A value that isn't a valid
ISO-8601 datetime is rejected with **422** rather than stored.

They are independent: an article published in 2019 and crawled today has
`published_at` in 2019 and `created_at` today.

## Tests

Tests run against a **real Postgres test database** (no SQLite), and the test
fixtures apply the Alembic migration before running — so a green test run also
proves the migration works.

They run automatically in **GitHub Actions on every push** (see
`.github/workflows/day1-documents-api.yml`).

To run them locally you need a Postgres reachable at the `TEST_DATABASE_URL`
in your `.env`, then:

```bash
pip install -r requirements.txt
pytest -v
```

## Notes

- **Schema** is created by the Alembic migrations (`alembic upgrade head`, run
  by the container entrypoint), never by `create_all`. Two revisions so far:
  `0001` creates the table, `0002` adds the nullable `published_at` column.
  Both downgrades are hand-written and exact — `downgrade base` returns the
  database to an empty schema.
- **`url` is unique** at the database level (`uq_documents_url`), which is what
  makes duplicate POSTs return 409 correctly even under concurrent requests.
- **`.env` is gitignored**; `.env.example` documents every key.
