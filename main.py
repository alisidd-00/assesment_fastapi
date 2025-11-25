import os
import base64
import binascii
from fastapi import FastAPI, HTTPException, Depends, Header, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from database import Base, engine, SessionLocal, BlobMetadata
from storage import LocalStorageBackend, S3StorageBackend, DatabaseStorageBackend
import logging

logger = logging.getLogger("simpledrive")
logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(bind=engine)

app = FastAPI()

STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()
LOCAL_STORAGE_DIR = os.environ.get("LOCAL_STORAGE_DIR", "my_local_files")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # default 10MB


def verify_token(authorization: str = Header(...)):
    """Simple Bearer token check.

    Expects header: 'Authorization: Bearer <token>'
    The token is read from `AUTH_TOKEN` env var (default `secret-token`).
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header format")

    token = authorization.split(" ", 1)[1]
    expected = os.environ.get("AUTH_TOKEN", "secret-token")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")
    return True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class BlobCreate(BaseModel):
    id: str
    data: str


class BlobResponse(BaseModel):
    id: str
    data: str
    size: int
    created_at: datetime


class BlobCreateResponse(BaseModel):
    id: str
    size: int
    created_at: datetime
    storage_type: str


if STORAGE_BACKEND == "local":
    BACKEND = LocalStorageBackend(storage_dir=LOCAL_STORAGE_DIR)
    BACKEND_NAME = "local"
elif STORAGE_BACKEND == "db":
    BACKEND = DatabaseStorageBackend(SessionLocal)
    BACKEND_NAME = "db"
elif STORAGE_BACKEND == "s3":
    BACKEND = S3StorageBackend(bucket_url=S3_ENDPOINT, access_key=S3_ACCESS_KEY, secret_key=S3_SECRET_KEY, region=S3_REGION)
    BACKEND_NAME = "s3"
else:
    BACKEND = LocalStorageBackend(storage_dir=LOCAL_STORAGE_DIR)
    BACKEND_NAME = "local"


@app.post("/v1/blobs", response_model=BlobCreateResponse, dependencies=[Depends(verify_token)], status_code=status.HTTP_201_CREATED)
def create_blob(blob: BlobCreate, db: Session = Depends(get_db)):
    if db.query(BlobMetadata).filter(BlobMetadata.id == blob.id).first():
        raise HTTPException(status_code=400, detail="ID already exists")

    try:
        decoded_data = base64.b64decode(blob.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid Base64 data")

    if len(decoded_data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Payload too large (max {MAX_UPLOAD_BYTES} bytes)")

    try:
        BACKEND.save(blob.id, decoded_data)
    except Exception as e:
        logger.exception("backend save failed for id=%s", blob.id)
        raise HTTPException(status_code=500, detail=f"Failed to save data: {e}")

    file_size = len(decoded_data)
    new_metadata = BlobMetadata(
        id=blob.id,
        size=file_size,
        created_at=datetime.utcnow(),
        storage_type=BACKEND_NAME,
    )
    db.add(new_metadata)
    try:
        db.commit()
    except Exception as e:
        logger.exception("db commit failed for id=%s, attempting cleanup", blob.id)
        try:
            BACKEND.delete(blob.id)
        except Exception:
            logger.exception("cleanup failed for id=%s", blob.id)
        raise HTTPException(status_code=500, detail="Failed to persist metadata; uploaded data cleaned up when possible")

    return BlobCreateResponse(id=blob.id, size=file_size, created_at=new_metadata.created_at, storage_type=BACKEND_NAME)


@app.get("/v1/blobs/{blob_id}", response_model=BlobResponse, dependencies=[Depends(verify_token)])
def get_blob(blob_id: str, db: Session = Depends(get_db)):
    metadata = db.query(BlobMetadata).filter(BlobMetadata.id == blob_id).first()
    if not metadata:
        raise HTTPException(status_code=404, detail="Blob not found")

    binary_data = BACKEND.get(blob_id)
    if binary_data is None:
        raise HTTPException(status_code=404, detail="Data missing from storage backend")

    encoded_data = base64.b64encode(binary_data).decode("utf-8")

    return BlobResponse(
        id=metadata.id,
        data=encoded_data,
        size=metadata.size,
        created_at=metadata.created_at,
    )