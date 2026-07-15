/**
 * Cliente de autenticación — espejo del RBAC del backend (app/auth/rbac.py).
 *
 * Gestiona el token JWT y el usuario en localStorage, decodifica los claims del
 * token y expone comprobaciones de permisos para condicionar la UI. La UI es
 * solo una conveniencia: la autorización real la aplica el backend.
 *
 * En producción, login()/register() llaman a la API (/auth/*) y guardan el JWT
 * real devuelto. En el prototipo sin backend, demoLogin() crea una sesión local
 * (token sin firmar, solo para mostrar) — claramente marcada como demo.
 */
const TOKEN_KEY = "cc_auth_token";
const USER_KEY = "cc_auth_user";

// Espejo de ROLE_PERMISSIONS (backend/app/auth/rbac.py).
export const PERMISSIONS = {
  PROJECT_READ: "project:read",
  PROJECT_WRITE: "project:write",
  PROJECT_DELETE: "project:delete",
  TASK_WRITE: "task:write",
  TASK_EXECUTE: "task:execute",
  DEPENDENCY_WRITE: "dependency:write",
  RESOURCE_WRITE: "resource:write",
  REPORT_READ: "report:read",
  USER_MANAGE: "user:manage",
};

const P = PERMISSIONS;
const CONSULTOR = [P.PROJECT_READ, P.PROJECT_WRITE, P.TASK_WRITE, P.TASK_EXECUTE, P.DEPENDENCY_WRITE, P.RESOURCE_WRITE, P.REPORT_READ];
const DIRECTOR = [...CONSULTOR, P.PROJECT_DELETE, P.USER_MANAGE];
export const ROLE_PERMISSIONS = {
  admin: DIRECTOR,
  director: DIRECTOR,
  consultor: CONSULTOR,
  aliado: [P.PROJECT_READ, P.TASK_EXECUTE, P.REPORT_READ],
};

export const ROLE_LABELS = {
  admin: "Administrador",
  director: "Director de proyecto",
  consultor: "Consultor",
  aliado: "Aliado rural",
};

function storage() {
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch (_) {
    /* no disponible */
  }
  const mem = new Map();
  return {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, v),
    removeItem: (k) => mem.delete(k),
  };
}
const store = storage();

/* --------------------------- Decodificación JWT --------------------------- */
function b64urlDecode(seg) {
  let s = seg.replace(/-/g, "+").replace(/_/g, "/");
  s += "=".repeat((4 - (s.length % 4)) % 4);
  const bin = typeof atob !== "undefined" ? atob(s) : Buffer.from(s, "base64").toString("binary");
  try {
    return decodeURIComponent(
      bin.split("").map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join("")
    );
  } catch (_) {
    return bin;
  }
}
function b64urlEncode(obj) {
  const json = JSON.stringify(obj);
  const b64 = typeof btoa !== "undefined"
    ? btoa(unescape(encodeURIComponent(json)))
    : Buffer.from(json, "utf-8").toString("base64");
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decodeToken(token) {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(b64urlDecode(payload));
  } catch (_) {
    return null;
  }
}

export function isTokenExpired(token) {
  const claims = decodeToken(token);
  if (!claims || !claims.exp) return false;
  return Date.now() / 1000 >= claims.exp;
}

/* ------------------------------ Sesión ------------------------------------ */
export function setSession(token, user) {
  store.setItem(TOKEN_KEY, token);
  store.setItem(USER_KEY, JSON.stringify(user));
}
export function getToken() {
  return store.getItem(TOKEN_KEY);
}
export function currentUser() {
  const raw = store.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}
export function logout() {
  store.removeItem(TOKEN_KEY);
  store.removeItem(USER_KEY);
}
export function isAuthenticated() {
  const t = getToken();
  return !!t && !isTokenExpired(t);
}
export function authHeader() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/* ------------------------------ Permisos ---------------------------------- */
export function hasPermission(permission, user = currentUser()) {
  if (!user) return false;
  return (ROLE_PERMISSIONS[user.role] || []).includes(permission);
}

/* ------------------------- Autenticación (API) ---------------------------- */
const API_BASE = "/api/v1";

export async function login(email, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error("Credenciales inválidas.");
  const data = await res.json();
  setSession(data.token, data.user);
  return data.user;
}

export async function register(organization_name, email, full_name, password) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ organization_name, email, full_name, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "No se pudo registrar.");
  }
  const data = await res.json();
  setSession(data.token, data.user);
  return data.user;
}

/**
 * Inicio de sesión de demostración (sin backend): crea una sesión local con un
 * token NO firmado, únicamente para explorar la UI y el RBAC. NO usar en producción.
 */
export function demoLogin({ email, full_name, role = "consultor", organization_name = "Agencia Campo Digital" }) {
  const now = Math.floor(Date.now() / 1000);
  const header = b64urlEncode({ alg: "none", typ: "JWT", demo: true });
  const payload = b64urlEncode({
    sub: "demo-" + role,
    email,
    name: full_name || email,
    role,
    org: "demo-org",
    iat: now,
    exp: now + 8 * 3600,
  });
  const token = `${header}.${payload}.demo`;
  const user = {
    id: "demo-" + role,
    email,
    full_name: full_name || email,
    role,
    organization_id: "demo-org",
    organization_name,
    demo: true,
  };
  setSession(token, user);
  return user;
}
