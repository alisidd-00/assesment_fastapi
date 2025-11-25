# Simple Drive — FastAPI

This repository is a lightweight object storage API built with FastAPI. It supports storing and retrieving binary blobs by `id`, and can use multiple storage backends (local filesystem, database table, S3‑compatible services). This README explains how to run the project locally, configure backends (SQLite, Postgres, MinIO), and run the test suite.

## Quick overview

- API endpoints:
  - `POST /v1/blobs` — Store a Base64 encoded blob. Request JSON: `{ "id": "<id>", "data": "<base64>" }`.
  - `GET /v1/blobs/{id}` — Retrieve a blob by id. Returns `id`, `data` (Base64), `size`, and `created_at`.
- Backends: local filesystem, database table (DB), S3‑compatible (HTTP only). FTP is not implemented.
- Authentication: simple Bearer token via `Authorization: Bearer <token>` — token set with `AUTH_TOKEN` env var (default `secret-token`).

## Prerequisites

- Python 3.9+ (3.10/3.11 recommended)
- `pip` and virtualenv (or Conda)
- Optional: Docker (for running Postgres and MinIO when testing integrations)

## Install dependencies

Open a Windows `cmd.exe` or a POSIX shell in the project root (where `main.py` is) and run:

```cmd
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install --upgrade pip
pip install -r requirements.txt
```

For Conda users you can skip creating venv if you prefer the base environment, but a virtualenv is recommended.

## Configuration (environment variables)

The app reads configuration from environment variables. Defaults are provided for a quick local run.

- `STORAGE_BACKEND` — `local` | `db` | `s3` (default: `local`)
- `LOCAL_STORAGE_DIR` — path for local files (default: `./my_local_files`)
- `DATABASE_URL` — SQLAlchemy connection string (default: `sqlite:///./drive.db`). Example Postgres: `postgresql://user:pass@127.0.0.1:5432/drivedb`
- `S3_ENDPOINT` — full endpoint including bucket path (current code expects `https://host:port/my-bucket`)
- `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` — S3 credentials and region
- `AUTH_TOKEN` — Bearer token used for all requests (default: `secret-token`)
- `MAX_UPLOAD_BYTES` — max upload size in bytes (default: `10485760` = 10MB)

Set env vars in Windows `cmd` (example):

```cmd
set STORAGE_BACKEND=local
set LOCAL_STORAGE_DIR=./my_local_files
set AUTH_TOKEN=secret-token
```

## Quick smoke run (SQLite + local storage)

This is the fastest way to try the API locally — no Docker required.

1. Ensure your virtualenv is active and dependencies are installed.
2. Set environment variables (example):

```cmd
set STORAGE_BACKEND=local
set LOCAL_STORAGE_DIR=./my_local_files
set AUTH_TOKEN=secret-token
```

3. Start the application:

```cmd
uvicorn main:app --reload
```

4. Store a blob (Base64 for `Hello World` is `SGVsbG8gV29ybGQh`):

```cmd
curl -X POST http://127.0.0.1:8000/v1/blobs ^
 -H "Authorization: Bearer secret-token" ^
 -H "Content-Type: application/json" ^
 -d "{\"id\":\"example-id\",\"data\":\"SGVsbG8gV29ybGQh\"}"
```

5. Retrieve the blob:

```cmd
curl -X GET http://127.0.0.1:8000/v1/blobs/example-id ^
 -H "Authorization: Bearer secret-token"
```

## Using Postgres (optional)

You can point the application to a Postgres server using `DATABASE_URL`.

Quick start with Docker:

```cmd
docker run --name simple-postgres -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=drivedb -p 5432:5432 -d postgres:15

docker exec -it simple-postgres psql -U postgres -c "CREATE USER myappuser WITH PASSWORD 'mysecretpassword';"
docker exec -it simple-postgres psql -U postgres -c "CREATE DATABASE drivedb OWNER myappuser;"
docker exec -it simple-postgres psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE drivedb TO myappuser;"
```

Then set env vars and start the app:

```cmd
set STORAGE_BACKEND=db
set DATABASE_URL=postgresql://myappuser:mysecretpassword@127.0.0.1:5432/drivedb
set AUTH_TOKEN=secret-token
uvicorn main:app --reload
```

Important: `create_all()` will create the tables but will not create the database itself.

## Using MinIO (S3-compatible) for S3 backend (optional)

Run MinIO via Docker (recommended) and create a bucket:

```cmd
docker run --name minio -p 9000:9000 -p 9001:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin -d minio/minio server /data --console-address ":9001"

# create a bucket using mc (MinIO client) or the web UI at http://127.0.0.1:9001
mc alias set local http://127.0.0.1:9000 minioadmin minioadmin
mc mb local/my-bucket
```

Set environment variables for S3 backend and start the app:

```cmd
set STORAGE_BACKEND=s3
set S3_ENDPOINT=http://127.0.0.1:9000/my-bucket
set S3_ACCESS_KEY=minioadmin
set S3_SECRET_KEY=minioadmin
set S3_REGION=us-east-1
set AUTH_TOKEN=secret-token
uvicorn main:app --reload
```

Notes on S3 signer:

- The project implements an HTTP-only SigV4 signer. Small differences (virtual-hosted vs path-style buckets, querystring encoding, clock skew) can cause 403 errors. For local MinIO testing use the endpoint with the bucket path (`http://127.0.0.1:9000/my-bucket`). If you prefer separate `S3_ENDPOINT` and `S3_BUCKET` variables, I can update the code to support that.

## Running tests

The repository includes basic tests under `tests/` using `pytest` and `TestClient`.

Run the full test suite:

```cmd
# activate venv first
python -m pytest -q
```

To run a single test file or test function:

```cmd
pytest -q tests/test_post_blob.py::test_post_and_get_blob
```

Notes:

- By default tests use whatever `DATABASE_URL` you set. To run tests with the bundled SQLite default, unset `DATABASE_URL` or set it to `sqlite:///./drive.db`.
- Integration tests for S3/Postgres are not included by default; you can run the server against MinIO/Postgres and run the tests manually.

## Troubleshooting

- `401 Invalid token`: ensure `Authorization: Bearer <token>` header matches `AUTH_TOKEN` env var.
- `400 Invalid Base64 data`: provide valid Base64 in the `data` field.
- `413 Payload too large`: increase `MAX_UPLOAD_BYTES` env var.
- `403` from S3/MinIO: confirm `S3_ACCESS_KEY`/`S3_SECRET_KEY`, that the bucket exists, and your system clock is accurate.
- `docker exec` errors: ensure the container is running (`docker ps`).

## Next improvements (recommended)

- Harden S3 signer for virtual-hosted buckets and add MinIO integration tests.
- Add Alembic migrations for schema management.
- Add more unit and integration tests (Postgres, S3).
- Implement FTP backend for bonus points.

## Project structure (key files)

- `main.py` — FastAPI app and endpoints
- `storage.py` — storage abstraction and adapters (Local, DB, S3)
- `database.py` — SQLAlchemy models and DB setup
- `tests/` — pytest tests
- `requirements.txt` — Python dependencies

If you want, I can also add a `docker-compose.yml` to spin up Postgres + MinIO, scaffold Alembic, or harden the S3 signer and add CI integration. Tell me which you prefer and I will implement it next.

---

Generated instructions based on the current repository state. If you change configuration style (e.g., separate `S3_BUCKET`) I can update the code and README accordingly.
