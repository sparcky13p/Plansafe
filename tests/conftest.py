import pytest

from tests.fixtures.make_fixtures import build_all


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("dxf"))


@pytest.fixture
def server(tmp_path, monkeypatch):
    """TestClient on a fresh SQLite database, dev auth, no external services."""
    from fastapi.testclient import TestClient

    from safetyplan.config import settings

    for k in ("DATABASE_URL", "POSTGRES_URL", "CLERK_ISSUER", "MUSE_API_KEY", "SAM_API_KEY", "VERCEL",
              "BLOB_READ_WRITE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings.cache_clear()
    from safetyplan.server.app import app

    yield TestClient(app)
    settings.cache_clear()
