"""Vercel Python function entry point.

Local: uvicorn api.index:app --reload
"""

from safetyplan.server.app import app  # noqa: F401
