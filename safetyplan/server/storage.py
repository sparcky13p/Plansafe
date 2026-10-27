"""Plan / price-list file storage.

refs:  "db:<id>"   small upload stored in the files table
       "https://<store>.public.blob.vercel-storage.com/..."   large file uploaded
       by the browser straight to Vercel Blob (see api/blob-upload.js)
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from safetyplan.db.models import StoredFile

MAX_REMOTE_BYTES = 60 * 1024 * 1024
BLOB_HOST_SUFFIX = ".blob.vercel-storage.com"


def save(db: Session, owner: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    f = StoredFile(owner=owner, name=name, content_type=content_type, data=data)
    db.add(f)
    db.flush()
    return f"db:{f.id}"


def load(db: Session, owner: str, ref: str) -> bytes:
    if ref.startswith("db:"):
        f = db.get(StoredFile, ref[3:])
        if f is None or f.owner != owner:
            raise HTTPException(404, "File not found.")
        return f.data
    check_blob_url(ref)
    try:
        with httpx.stream("GET", ref, timeout=60, follow_redirects=False) as r:
            r.raise_for_status()
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > MAX_REMOTE_BYTES:
                    raise HTTPException(413, "Plan file too large.")
                chunks.append(chunk)
            return b"".join(chunks)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not fetch uploaded file: {exc}") from exc


def check_blob_url(url: str) -> None:
    """Only fetch from Vercel Blob, never arbitrary URLs (SSRF)."""
    u = urlparse(url)
    if u.scheme != "https" or not (u.hostname or "").endswith(BLOB_HOST_SUFFIX):
        raise HTTPException(422, "File URL must be a Vercel Blob URL.")
