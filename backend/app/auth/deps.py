"""Dependencias FastAPI para autenticación y autorización.

* ``get_current_user`` — extrae y valida el JWT del encabezado ``Authorization:
  Bearer <token>`` y devuelve los claims del usuario.
* ``require_permission(perm)`` — dependencia que exige un permiso RBAC concreto.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException

from ..db import Database, get_database
from .rbac import has_permission, permissions_for
from .security import ExpiredTokenError, JWTError
from .service import AuthService


def get_auth_service(db: Database = Depends(get_database)) -> AuthService:
    return AuthService(db)


def get_current_user(
    authorization: Optional[str] = Header(None),
    auth: AuthService = Depends(get_auth_service),
) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Falta el encabezado Authorization Bearer.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = auth.verify_token(token)
    except ExpiredTokenError:
        raise HTTPException(status_code=401, detail="El token expiró.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido.")
    return claims


def require_permission(permission: str):
    """Devuelve una dependencia que valida el permiso del usuario autenticado."""

    def dependency(user: dict = Depends(get_current_user)) -> dict:
        role = user.get("role", "")
        if not has_permission(role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"El rol '{role}' no tiene el permiso requerido: {permission}.",
            )
        return user

    return dependency


def current_user_permissions(user: dict = Depends(get_current_user)) -> list:
    return sorted(permissions_for(user.get("role", "")))
