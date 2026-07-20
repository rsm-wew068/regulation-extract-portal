"""Runtime configuration, loaded from portal/.env."""
import os
from pathlib import Path

from dotenv import load_dotenv

PORTAL_DIR = Path(__file__).resolve().parent.parent  # portal/
load_dotenv(PORTAL_DIR / ".env")

PAPERLESS_API_URL = os.environ["PAPERLESS_API_URL"].rstrip("/")
PAPERLESS_API_TOKEN = os.environ["PAPERLESS_API_TOKEN"]
ABSTRACT_FIELD_ID = int(os.environ["ABSTRACT_FIELD_ID"])
TRADE_FIELD_ID = int(os.environ["TRADE_FIELD_ID"])
SOURCE_FIELD_ID = int(os.environ["SOURCE_FIELD_ID"])

_origins = os.environ.get("CORS_ORIGINS", "")
CORS_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]

# Auth: shared passphrase gate. Coworkers enter PORTAL_PASSWORD; the backend
# issues an HMAC-signed bearer token (PORTAL_SECRET) required on all /api routes.
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD", "")
PORTAL_SECRET = os.environ.get("PORTAL_SECRET", "dev-secret-change-me")
