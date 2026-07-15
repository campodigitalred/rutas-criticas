"""Pruebas de autenticación: seguridad, RBAC y servicio."""
import time

import pytest

from app.auth import (
    AuthError,
    AuthService,
    ExpiredTokenError,
    JWTError,
    decode_jwt,
    encode_jwt,
    hash_password,
    has_permission,
    verify_password,
)
from app.auth.rbac import (
    P_PROJECT_DELETE,
    P_PROJECT_READ,
    P_PROJECT_WRITE,
    P_TASK_EXECUTE,
    P_USER_MANAGE,
)
from app.db import Database


# ------------------------------- Contraseñas ------------------------------- #
def test_password_hash_and_verify():
    h = hash_password("Sembrar-2025!")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("Sembrar-2025!", h) is True
    assert verify_password("incorrecta", h) is False


def test_password_hash_is_salted():
    # Dos hashes de la misma contraseña difieren (sal aleatoria).
    assert hash_password("misma") != hash_password("misma")


def test_verify_rejects_malformed_hash():
    assert verify_password("x", "no-es-un-hash") is False


# ---------------------------------- JWT ------------------------------------ #
def test_jwt_roundtrip():
    token = encode_jwt({"sub": "u1", "role": "director"}, secret="s3cr3t")
    claims = decode_jwt(token, secret="s3cr3t")
    assert claims["sub"] == "u1" and claims["role"] == "director"
    assert "iat" in claims and "exp" in claims


def test_jwt_wrong_secret_fails():
    token = encode_jwt({"sub": "u1"}, secret="a")
    with pytest.raises(JWTError):
        decode_jwt(token, secret="b")


def test_jwt_tamper_detected():
    token = encode_jwt({"sub": "u1", "role": "aliado"}, secret="s")
    header, payload, sig = token.split(".")
    # Reusar firma con un payload alterado -> firma inválida.
    forged = f"{header}.{payload}x.{sig}"
    with pytest.raises(JWTError):
        decode_jwt(forged, secret="s")


def test_jwt_expired():
    token = encode_jwt({"sub": "u1"}, secret="s", expires_in=-1)
    with pytest.raises(ExpiredTokenError):
        decode_jwt(token, secret="s")


# ---------------------------------- RBAC ----------------------------------- #
def test_rbac_permissions():
    assert has_permission("admin", P_PROJECT_DELETE)
    assert has_permission("director", P_PROJECT_DELETE)
    assert has_permission("director", P_USER_MANAGE)
    # El consultor edita pero no borra proyectos ni gestiona usuarios.
    assert has_permission("consultor", P_PROJECT_WRITE)
    assert not has_permission("consultor", P_PROJECT_DELETE)
    assert not has_permission("consultor", P_USER_MANAGE)
    # El aliado (campo) solo lee y ejecuta tareas.
    assert has_permission("aliado", P_PROJECT_READ)
    assert has_permission("aliado", P_TASK_EXECUTE)
    assert not has_permission("aliado", P_PROJECT_WRITE)


# ------------------------------- AuthService ------------------------------- #
@pytest.fixture()
def auth():
    db = Database(":memory:")
    db.init_schema()
    yield AuthService(db, secret="test-secret")
    db.close()


def test_register_creates_org_admin_and_token(auth):
    out = auth.register("Agencia Campo Digital", "Dir@Campo.mx", "Directora", "Sembrar-2025!")
    assert out["user"]["role"] == "admin"
    assert out["user"]["email"] == "dir@campo.mx"      # normalizado
    assert "password_hash" not in out["user"]           # nunca se expone
    claims = auth.verify_token(out["token"])
    assert claims["sub"] == out["user"]["id"] and claims["role"] == "admin"


def test_register_duplicate_email_fails(auth):
    auth.register("Org", "a@b.mx", "A", "Sembrar-2025!")
    with pytest.raises(AuthError):
        auth.register("Org2", "A@B.mx", "A2", "Sembrar-2025!")


def test_short_password_rejected(auth):
    with pytest.raises(AuthError):
        auth.register("Org", "a@b.mx", "A", "corta")


def test_authenticate_success_and_failure(auth):
    reg = auth.register("Org", "user@campo.mx", "User", "Sembrar-2025!")
    ok = auth.authenticate("user@campo.mx", "Sembrar-2025!")
    assert ok["user"]["id"] == reg["user"]["id"]
    with pytest.raises(AuthError):
        auth.authenticate("user@campo.mx", "mala-contraseña")
    with pytest.raises(AuthError):
        auth.authenticate("noexiste@campo.mx", "Sembrar-2025!")


def test_create_user_with_role(auth):
    admin = auth.register("Org", "admin@campo.mx", "Admin", "Sembrar-2025!")
    org_id = admin["user"]["organization_id"]
    aliado = auth.create_user(org_id, "campo@campo.mx", "Aliado Rural", "EnElCampo-1", role="aliado")
    assert aliado["role"] == "aliado"
    logged = auth.authenticate("campo@campo.mx", "EnElCampo-1")
    assert auth.verify_token(logged["token"])["role"] == "aliado"


def test_create_user_invalid_role(auth):
    admin = auth.register("Org", "admin@campo.mx", "Admin", "Sembrar-2025!")
    with pytest.raises(AuthError):
        auth.create_user(admin["user"]["organization_id"], "x@y.mx", "X", "Password1", role="superuser")
