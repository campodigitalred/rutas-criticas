"""Autenticación y control de acceso (RBAC) de Campo Crítico."""
from .rbac import ROLE_PERMISSIONS, ROLES, has_permission, permissions_for
from .security import (
    ExpiredTokenError,
    JWTError,
    decode_jwt,
    encode_jwt,
    hash_password,
    verify_password,
)
from .service import AuthError, AuthService

__all__ = [
    "ROLES",
    "ROLE_PERMISSIONS",
    "has_permission",
    "permissions_for",
    "hash_password",
    "verify_password",
    "encode_jwt",
    "decode_jwt",
    "JWTError",
    "ExpiredTokenError",
    "AuthService",
    "AuthError",
]
