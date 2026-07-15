/**
 * LoginView — inicio de sesión / registro de Campo Crítico.
 *
 * Intenta autenticarse contra la API (/auth/*). Si no hay backend disponible,
 * ofrece un acceso de demostración por rol para explorar el control de acceso
 * (RBAC) en la interfaz.
 */
import React, { useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";
import { ROLE_LABELS } from "../lib/authClient.js";

const DEMO_ROLES = ["director", "consultor", "aliado"];

export default function LoginView() {
  const { login, register, loginDemo } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(orgName, email, fullName, password);
    } catch (err) {
      setError(err.message || "Error de autenticación. Prueba el acceso de demostración.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cc-app">
      <div className="cc-login">
        <div className="cc-brand" style={{ justifyContent: "center", marginBottom: 8 }}>
          <div className="cc-logo">CC</div>
          <div>
            <h1 style={{ margin: 0 }}>Campo Crítico</h1>
            <p style={{ margin: 0, color: "var(--cc-gray-500)", fontSize: 13 }}>Agencia Campo Digital</p>
          </div>
        </div>

        <div className="cc-tabs" style={{ justifyContent: "center" }}>
          <button className={`cc-tab ${mode === "login" ? "active" : ""}`} onClick={() => setMode("login")}>Iniciar sesión</button>
          <button className={`cc-tab ${mode === "register" ? "active" : ""}`} onClick={() => setMode("register")}>Registrar organización</button>
        </div>

        <form className="cc-card" onSubmit={submit}>
          {mode === "register" && (
            <>
              <label className="cc-form-label">Organización
                <input className="cc-input" style={{ width: "100%" }} value={orgName} onChange={(e) => setOrgName(e.target.value)} required />
              </label>
              <label className="cc-form-label">Nombre completo
                <input className="cc-input" style={{ width: "100%" }} value={fullName} onChange={(e) => setFullName(e.target.value)} required />
              </label>
            </>
          )}
          <label className="cc-form-label">Correo
            <input className="cc-input" style={{ width: "100%" }} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label className="cc-form-label">Contraseña
            <input className="cc-input" style={{ width: "100%" }} type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          </label>

          {error && <div className="cc-alert-danger" style={{ marginTop: 10 }}>{error}</div>}

          <button className="cc-btn primary" type="submit" disabled={busy} style={{ width: "100%", marginTop: 12 }}>
            {busy ? "Procesando…" : mode === "login" ? "Entrar" : "Crear organización"}
          </button>
        </form>

        <div className="cc-card">
          <p className="sub" style={{ margin: "0 0 10px" }}>
            ¿Sin backend a la mano? Explora el control de acceso con un acceso de demostración:
          </p>
          <div className="cc-chips">
            {DEMO_ROLES.map((role) => (
              <button
                key={role}
                className="cc-chip"
                onClick={() => loginDemo({ email: `${role}@campo.mx`, full_name: ROLE_LABELS[role], role })}
              >
                Entrar como {ROLE_LABELS[role]}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
