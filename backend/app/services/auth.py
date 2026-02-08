import json
import os

from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2 import id_token

_DEFAULT_CLIENT_SECRET = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../client_secret_556243231835-hp9de3dc0umqvor2101d4qj2192kfd83.apps.googleusercontent.com.json",
    )
)
GOOGLE_CLIENT_SECRET_FILE = os.getenv("GOOGLE_CLIENT_SECRET_FILE", _DEFAULT_CLIENT_SECRET)
print(f"[auth] GOOGLE_CLIENT_ID set: {bool(os.getenv('GOOGLE_CLIENT_ID'))}", flush=True)


def _load_client_id_from_file():
    try:
        with open(GOOGLE_CLIENT_SECRET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data["web"]["client_id"]
    except Exception:
        return None


def verify_google_token(token: str) -> dict:
    client_id = os.getenv("GOOGLE_CLIENT_ID") or _load_client_id_from_file()
    if not client_id:
        file_exists = os.path.exists(GOOGLE_CLIENT_SECRET_FILE)
        print(
            f"[auth] missing client_id env; secret file exists: {file_exists}",
            flush=True,
        )
        raise HTTPException(status_code=500, detail="Google client id not configured")

    try:
        payload = id_token.verify_oauth2_token(token, Request(), client_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    if payload.get("aud") != client_id:
        raise HTTPException(status_code=401, detail="Token audience mismatch")

    return payload
