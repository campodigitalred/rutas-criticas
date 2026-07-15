"""Primitivas de seguridad (solo biblioteca estándar).

* Hashing de contraseñas con **PBKDF2-HMAC-SHA256** (con sal aleatoria e
  iteraciones), formato ``pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>``.
* **JWT HS256** (firma HMAC-SHA256) con ``iat``/``exp``, verificación en tiempo
  constante y detección de manipulación.

No requiere dependencias externas (PyJWT/passlib/bcrypt), por lo que es
verificable sin conexión. En producción puede sustituirse por dichas librerías
manteniendo el mismo contrato.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict

# --------------------------------------------------------------------------- #
# Contraseñas — PBKDF2-HMAC-SHA256
# --------------------------------------------------------------------------- #
_ALGO = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 200_000


def hash_password(password: str, iterations: int = _DEFAULT_ITERATIONS) -> str:
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# --------------------------------------------------------------------------- #
# JWT HS256
# --------------------------------------------------------------------------- #
class JWTError(Exception):
    """Token inválido, manipulado o mal formado."""


class ExpiredTokenError(JWTError):
    """El token expiró."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def get_secret(secret: str | None = None) -> str:
    """Secreto de firma. En producción, definir ``CAMPO_JWT_SECRET``."""
    return secret or os.getenv("CAMPO_JWT_SECRET", "dev-secret-cambiar-en-produccion")


def encode_jwt(
    claims: Dict[str, Any],
    secret: str | None = None,
    expires_in: int = 8 * 3600,
) -> str:
    secret = get_secret(secret)
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**claims, "iat": now, "exp": now + expires_in}
    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return ".".join(segments)


def decode_jwt(token: str, secret: str | None = None) -> Dict[str, Any]:
    secret = get_secret(secret)
    try:
        header_seg, payload_seg, sig_seg = token.split(".")
    except ValueError:
        raise JWTError("Formato de token inválido.")

    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        provided = _b64url_decode(sig_seg)
    except Exception:
        raise JWTError("Firma ilegible.")
    if not hmac.compare_digest(expected, provided):
        raise JWTError("Firma inválida (token manipulado).")

    try:
        payload = json.loads(_b64url_decode(payload_seg))
    except Exception:
        raise JWTError("Payload ilegible.")

    exp = payload.get("exp")
    if exp is not None and int(time.time()) >= int(exp):
        raise ExpiredTokenError("El token expiró.")
    return payload
