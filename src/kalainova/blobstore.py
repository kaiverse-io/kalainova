"""Where kit bytes live: a local cache, optionally backed by private S3-compatible storage.

A kit records only a file's hash and suffix, so moving storage never changes a kit or a lock.

  $KALAINOVA_STORE       the local cache directory (default <home>/store)
  $KALAINOVA_STORE_URI   s3://bucket/prefix for the durable copy. Unset means local only.
  $KALAINOVA_KMS_KEY     KMS key id. Set it on AWS to encrypt every object with SSE-KMS.
  $KALAINOVA_S3_ENDPOINT for S3-compatible storage such as R2

Credentials come from the platform's normal chain (role, environment), never from a file here.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .jobfs import ContractError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _client() -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise ContractError(
            "KALAINOVA_STORE_URI is set, but boto3 is missing; run `uv sync --extra cloud`"
        ) from exc
    return boto3.client("s3", endpoint_url=os.environ.get("KALAINOVA_S3_ENDPOINT") or None)


def _location(uri: str, name: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ContractError(f"KALAINOVA_STORE_URI must look like s3://bucket/prefix, not {uri!r}")
    return parsed.netloc, "/".join(p for p in (parsed.path.strip("/"), name[:2], name) if p)


def remote_uri() -> str:
    return os.environ.get("KALAINOVA_STORE_URI", "")


def push(path: Path, *, client: Any = None) -> None:
    """Copy one cached file to durable storage. Same name means same bytes, so repeating is safe."""
    uri = remote_uri()
    if not uri:
        return
    bucket, key = _location(uri, path.name)
    extra: dict[str, str] = {}
    kms = os.environ.get("KALAINOVA_KMS_KEY")
    if kms:
        extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms}
    (client or _client()).upload_file(str(path), bucket, key, ExtraArgs=extra)


def fetch(path: Path, *, client: Any = None) -> bool:
    """Fill the cache from durable storage. False if nothing is configured. The hash is the file's
    name, so a wrong or corrupted download is refused and never reaches the cache."""
    uri = remote_uri()
    if not uri:
        return False
    bucket, key = _location(uri, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{uuid.uuid4().hex[:8]}.{path.name}")
    try:
        (client or _client()).download_file(bucket, key, str(temp))
        if _sha256(temp) != path.stem:
            raise ContractError(f"{key}: stored bytes do not match their hash")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return True
