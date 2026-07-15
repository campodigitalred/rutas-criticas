"""Servicio de autenticación sobre el repositorio de usuarios."""
from __future__ import annotations

from typing import Optional

from ..db.database import Database
from ..db.repository import OrganizationRepository, UserRepository
from .rbac import ROLES
from .security import decode_jwt, encode_jwt, hash_password, verify_password


class AuthError(Exception):
    """Fallo de autenticación o registro."""


class AuthService:
    def __init__(self, db: Database, secret: Optional[str] = None, token_ttl: int = 8 * 3600):
        self.db = db
        self.secret = secret
        self.token_ttl = token_ttl
        self.users = UserRepository(db)
        self.orgs = OrganizationRepository(db)

    # ------------------------------------------------------------------ #
    def register(self, organization_name: str, email: str, full_name: str, password: str) -> dict:
        """Da de alta una organización y su usuario administrador. Devuelve {user, token}."""
        email = _normalize_email(email)
        if self.users.get_by_email(email):
            raise AuthError("El correo ya está registrado.")
        _validate_password(password)
        org = self.orgs.create(organization_name)
        user = self.users.create(
            organization_id=org["id"], email=email, full_name=full_name,
            role="admin", password_hash=hash_password(password),
        )
        return {"user": _public(user), "organization": org, "token": self.issue_token(user)}

    def create_user(self, organization_id: str, email: str, full_name: str,
                    password: str, role: str = "consultor") -> dict:
        """Crea un usuario con rol (acción de administración)."""
        if role not in ROLES:
            raise AuthError(f"Rol inválido: {role}")
        email = _normalize_email(email)
        if self.users.get_by_email(email):
            raise AuthError("El correo ya está registrado.")
        _validate_password(password)
        user = self.users.create(
            organization_id=organization_id, email=email, full_name=full_name,
            role=role, password_hash=hash_password(password),
        )
        return _public(user)

    def authenticate(self, email: str, password: str) -> dict:
        """Valida credenciales y devuelve {user, token}."""
        user = self.users.get_by_email(_normalize_email(email))
        # Verifica siempre para no filtrar existencia por tiempo de respuesta.
        stored = user["password_hash"] if user else "pbkdf2_sha256$1$00$00"
        if not verify_password(password, stored) or user is None:
            raise AuthError("Credenciales inválidas.")
        return {"user": _public(user), "token": self.issue_token(user)}

    def issue_token(self, user: dict) -> str:
        claims = {
            "sub": user["id"],
            "email": user["email"],
            "role": user["role"],
            "org": user["organization_id"],
            "name": user["full_name"],
        }
        return encode_jwt(claims, self.secret, self.token_ttl)

    def verify_token(self, token: str) -> dict:
        """Devuelve los claims del token (lanza JWTError si es inválido/expirado)."""
        return decode_jwt(token, self.secret)


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _validate_password(password: str) -> None:
    if not password or len(password) < 8:
        raise AuthError("La contraseña debe tener al menos 8 caracteres.")


def _public(user: dict) -> dict:
    """Usuario sin el hash de contraseña."""
    return {k: v for k, v in user.items() if k != "password_hash"}
