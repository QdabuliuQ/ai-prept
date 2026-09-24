"""Backward-compatible entrypoint — prefer api.app:app """

from api.app import app

__all__ = ["app"]
