from __future__ import annotations

import hashlib
import hmac
import secrets


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310_000
MIN_PASSWORD_LENGTH = 5


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = PASSWORD_ITERATIONS) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен содержать не менее {MIN_PASSWORD_LENGTH} символов")
    password_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), password_salt, iterations)
    return f"{PASSWORD_SCHEME}${iterations}${password_salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(raw_iterations)
        salt = bytes.fromhex(raw_salt)
        expected = bytes.fromhex(raw_digest)
    except (TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def hash_pin(pin: str) -> str:
    if not (len(pin) == 4 and pin.isdigit()):
        raise ValueError("PIN должен состоять из 4 цифр")
    return hash_password(f"pos-pin:{pin}")


def verify_pin(pin: str, encoded: str | None) -> bool:
    return bool(encoded) and len(pin) == 4 and pin.isdigit() and verify_password(f"pos-pin:{pin}", encoded)


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
