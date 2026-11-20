import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("EVENTEASE_SECRET_KEY", "local-development-key-change-before-deployment")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'eventease.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    CERTIFICATE_FOLDER = BASE_DIR / "certificates"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_POSTER_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
