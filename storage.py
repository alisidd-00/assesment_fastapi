"""Storage backends: Local, Database, and S3-compatible (HTTP only).

This module implements a simple S3 SigV4 signer suitable for many S3-compatible
endpoints. It supports path-style and virtual-hosted-style bucket URLs and
builds a canonical query string when present.
"""
import abc
import os
import httpx
import hashlib
import hmac
import datetime
from urllib.parse import urlparse, quote, parse_qsl
from sqlalchemy.orm import sessionmaker
from database import BlobDataStore


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    def save(self, blob_id: str, data: bytes):
        raise NotImplementedError()

    @abc.abstractmethod
    def get(self, blob_id: str) -> bytes:
        raise NotImplementedError()
    
    @abc.abstractmethod
    def delete(self, blob_id: str):
        raise NotImplementedError()


class LocalStorageBackend(StorageBackend):
    """Local filesystem backend.

    This backend stores files under `storage_dir` using a hashed filename
    to avoid path traversal and filesystem injection from user-provided ids.
    """

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)

    def _filename_for_id(self, blob_id: str) -> str:
        # Use SHA-256 of the id as filename to avoid unsafe characters
        safe_name = hashlib.sha256(blob_id.encode("utf-8")).hexdigest()
        return os.path.join(self.storage_dir, safe_name)

    def save(self, blob_id: str, data: bytes):
        path = self._filename_for_id(blob_id)
        with open(path, "wb") as f:
            f.write(data)

    def get(self, blob_id: str) -> bytes:
        path = self._filename_for_id(blob_id)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def delete(self, blob_id: str):
        path = self._filename_for_id(blob_id)
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
        except Exception:
            return False
        return True


class DatabaseStorageBackend(StorageBackend):
    """Store actual blob bytes in a separate DB table.

    Accepts a sessionmaker (SQLAlchemy) so it can create scoped sessions
    for each operation.
    """

    def __init__(self, session_maker: sessionmaker):
        self._Session = session_maker

    def save(self, blob_id: str, data: bytes):
        db = self._Session()
        try:
            new_blob = BlobDataStore(id=blob_id, data=data)
            db.add(new_blob)
            db.commit()
        finally:
            db.close()

    def get(self, blob_id: str) -> bytes:
        db = self._Session()
        try:
            record = db.query(BlobDataStore).filter(BlobDataStore.id == blob_id).first()
            if record:
                return record.data
            return None
        finally:
            db.close()

    def delete(self, blob_id: str):
        db = self._Session()
        try:
            record = db.query(BlobDataStore).filter(BlobDataStore.id == blob_id).first()
            if record:
                db.delete(record)
                db.commit()
                return True
            return False
        finally:
            db.close()


class S3StorageBackend(StorageBackend):
    """S3-compatible backend using only HTTP (no SDK).

    Implements a minimal AWS Signature Version 4 signer for PUT/GET.
    Expects `bucket_url` to include the bucket path if needed, e.g.,
    `https://s3.amazonaws.com/my-bucket` or `https://minio.example.com/my-bucket`.
    """

    def __init__(self, bucket_url: str, access_key: str, secret_key: str, region: str = "us-east-1"):
        self.bucket_url = bucket_url.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.service = "s3"

    def _sign(self, key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    def _get_signature_key(self, key, date_stamp, region_name, service_name):
        k_date = self._sign(("AWS4" + key).encode("utf-8"), date_stamp)
        k_region = self._sign(k_date, region_name)
        k_service = self._sign(k_region, service_name)
        k_signing = self._sign(k_service, "aws4_request")
        return k_signing

    def _send_signed(self, method: str, blob_id: str, payload: bytes = b"") -> httpx.Response:
        # Construct full URL from bucket_url and blob_id
        parsed = urlparse(f"{self.bucket_url}/{blob_id}")
        host = parsed.netloc
        # Encode the path per AWS rules (leave '/' unescaped)
        canonical_uri = quote(parsed.path or "/", safe='/-_.~')

        t = datetime.datetime.utcnow()
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = t.strftime("%Y%m%d")

        payload_hash = hashlib.sha256(payload).hexdigest()

        # Build canonical querystring sorted by key (AWS SigV4 requirement)
        canonical_querystring = ""
        if parsed.query:
            params = parse_qsl(parsed.query, keep_blank_values=True)
            params.sort()
            canonical_querystring = "&".join([
                f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in params
            ])
        canonical_headers = (
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"

        canonical_request = "\n".join([
            method,
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            signed_headers,
            payload_hash,
        ])

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self.region}/{self.service}/aws4_request"
        string_to_sign = "\n".join([
            algorithm,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])

        signing_key = self._get_signature_key(self.secret_key, date_stamp, self.region, self.service)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization_header = (
            f"{algorithm} Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization_header,
        }

        url = f"{parsed.scheme}://{host}{parsed.path}"
        with httpx.Client() as client:
            if method == "PUT":
                resp = client.put(url, content=payload, headers=headers)
            else:
                resp = client.get(url, headers=headers)
        return resp

    def save(self, blob_id: str, data: bytes):
        resp = self._send_signed("PUT", blob_id, payload=data)
        resp.raise_for_status()

    def delete(self, blob_id: str):
        resp = self._send_signed("DELETE", blob_id, payload=b"")
        try:
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def get(self, blob_id: str) -> bytes:
        resp = self._send_signed("GET", blob_id, payload=b"")
        if resp.status_code == 200:
            return resp.content
        return None