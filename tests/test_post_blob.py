import os
import base64
import tempfile
import shutil
from fastapi.testclient import TestClient
from main import app
from database import engine, Base

client = TestClient(app)


def setup_module(module):
    Base.metadata.create_all(bind=engine)


def teardown_module(module):
    pass


def test_post_and_get_blob():
    token = os.environ.get("AUTH_TOKEN", "secret-token")
    payload = {"id": "test-1", "data": base64.b64encode(b"hello world").decode('utf-8')}

    r = client.post("/v1/blobs", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201
    data = r.json()
    assert data["id"] == "test-1"
    assert data["size"] == len(b"hello world")

    r2 = client.get(f"/v1/blobs/test-1", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    got = r2.json()
    assert got["id"] == "test-1"
    assert base64.b64decode(got["data"]) == b"hello world"


def test_invalid_base64_rejected():
    token = os.environ.get("AUTH_TOKEN", "secret-token")
    payload = {"id": "test-invalid", "data": "not-base64!!!"}
    r = client.post("/v1/blobs", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


def test_duplicate_id_rejected():
    token = os.environ.get("AUTH_TOKEN", "secret-token")
    payload = {"id": "test-dup", "data": base64.b64encode(b"a").decode('utf-8')}
    r = client.post("/v1/blobs", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201
    r2 = client.post("/v1/blobs", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 400


def test_atomic_cleanup_on_metadata_failure(tmp_path, monkeypatch):
    """Simulate DB commit failure and ensure backend cleanup is attempted."""
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    from storage import LocalStorageBackend
    import main as main_module

    main_module.BACKEND = LocalStorageBackend(str(storage_dir))

    class DummyQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class DummyDB:
        def query(self, *a, **k):
            return DummyQuery()

        def add(self, *a, **k):
            return None

        def commit(self):
            raise Exception("simulated commit failure")

    def fake_get_db():
        return DummyDB()

    main_module.get_db = fake_get_db

    token = os.environ.get("AUTH_TOKEN", "secret-token")
    payload = {"id": "will-cleanup", "data": base64.b64encode(b"cleanup").decode('utf-8')}

    r = client.post("/v1/blobs", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 500

    import hashlib
    name = hashlib.sha256(payload["id"].encode("utf-8")).hexdigest()
    saved_path = storage_dir / name
    assert not saved_path.exists()
