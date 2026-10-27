"""Runtime configuration, read from environment variables.

Every external service has a local fallback so the app runs with no keys:

  DATABASE_URL            Neon/Postgres URL; default: SQLite file in DATA_DIR
  DATA_DIR                local data directory (default .data, /tmp/plansafe on Vercel)
  BLOB_READ_WRITE_TOKEN   enables Vercel Blob client uploads for large plans
  CLERK_ISSUER            e.g. https://<app>.clerk.accounts.dev ; enables auth
  CLERK_AUTHORIZED_PARTIES  comma-separated allowed origins (azp claim), optional
  ALLOW_DEV_AUTH          "1" to allow the single dev user when deployed without Clerk
  MUSE_API_KEY / MUSE_API_BASE / MUSE_MODEL   vision + instruction model
  SAM_API_KEY / SAM_API_BASE / SAM_MODEL       site photo segmentation (stretch)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Load a local .env when python-dotenv is available (never committed).
try:  # pragma: no cover - optional convenience
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    on_vercel: bool
    blob_token: str | None
    clerk_issuer: str | None
    clerk_parties: tuple[str, ...]
    allow_dev_auth: bool

    @property
    def auth_mode(self) -> str:
        return "clerk" if self.clerk_issuer else "dev"


@lru_cache(maxsize=1)
def settings() -> Settings:
    on_vercel = bool(os.environ.get("VERCEL"))
    data_dir = Path(os.environ.get("DATA_DIR") or ("/tmp/plansafe" if on_vercel else ".data"))
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if not url:
        data_dir.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{(data_dir / 'plansafe.db').as_posix()}"
    issuer = (os.environ.get("CLERK_ISSUER") or "").rstrip("/") or None
    parties = tuple(p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if p.strip())
    return Settings(
        database_url=url,
        data_dir=data_dir,
        on_vercel=on_vercel,
        blob_token=os.environ.get("BLOB_READ_WRITE_TOKEN") or None,
        clerk_issuer=issuer,
        clerk_parties=parties,
        allow_dev_auth=(os.environ.get("ALLOW_DEV_AUTH") == "1") or not on_vercel,
    )
