from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SESSION_COOKIE_NAME = "kifli_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 nap


def load_or_create_secret(data_dir: Path, env_secret: str = "") -> bytes:
    if env_secret.strip():
        return hashlib.sha256(env_secret.strip().encode("utf-8")).digest()
    secret_file = data_dir / ".app_secret"
    data_dir.mkdir(parents=True, exist_ok=True)
    if secret_file.exists():
        raw = secret_file.read_text(encoding="utf-8").strip()
        if raw:
            return hashlib.sha256(raw.encode("utf-8")).digest()
    generated = secrets.token_urlsafe(48)
    secret_file.write_text(generated, encoding="utf-8")
    try:
        secret_file.chmod(0o600)
    except Exception:
        pass
    return hashlib.sha256(generated.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode('ascii')}${base64.b64encode(dk).decode('ascii')}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, salt_b64, dk_b64 = stored_hash.split("$", 2)
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_session_token(secret_key: bytes, user_id: int) -> str:
    payload = {
        "uid": int(user_id),
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(secret_key, raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_session_token(secret_key: bytes, token: str) -> int | None:
    if not token or "." not in token:
        return None
    try:
        raw, sig = token.rsplit(".", 1)
        expected_sig = hmac.new(secret_key, raw.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return int(payload["uid"])
    except Exception:
        return None


def _fernet(secret_key: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(secret_key))


def encrypt_secret(secret_key: bytes, plaintext: str) -> str:
    clean = (plaintext or "").strip()
    if not clean:
        return ""
    return _fernet(secret_key).encrypt(clean.encode("utf-8")).decode("ascii")


def decrypt_secret(secret_key: bytes, ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet(secret_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        return ""


def mask_api_key(key: str) -> str:
    clean = (key or "").strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "••••"
    return f"{clean[:4]}••••{clean[-4:]}"


def generate_personal_mcp_token() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(28))
