"""Who is calling: Clerk session JWT when configured, else a single dev user."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Header, HTTPException

from safetyplan.config import settings

DEV_USER = "dev-user"


@lru_cache(maxsize=4)
def _jwks(issuer: str):
    import jwt

    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True)


def verify_token(token: str) -> str:
    import jwt

    s = settings()
    try:
        key = _jwks(s.clerk_issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=s.clerk_issuer,
                            options={"require": ["exp", "sub"], "verify_aud": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid session: {exc}") from exc
    if s.clerk_parties and claims.get("azp") not in s.clerk_parties:
        raise HTTPException(401, "Session issued for another origin.")
    return claims["sub"]


def current_user(authorization: str | None = Header(None)) -> str:
    s = settings()
    if s.clerk_issuer:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Sign in required.")
        return verify_token(authorization.split(" ", 1)[1].strip())
    if not s.allow_dev_auth:
        raise HTTPException(503, "Authentication is not configured (set CLERK_ISSUER).")
    return DEV_USER
