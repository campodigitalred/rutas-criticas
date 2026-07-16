/**
 * AuthContext — sesión de usuario y permisos para toda la app.
 */
import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import {
  currentUser,
  demoLogin,
  hasPermission as hasPerm,
  isAuthenticated,
  login as apiLogin,
  logout as clearSession,
  register as apiRegister,
} from "../lib/authClient.js";

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => (isAuthenticated() ? currentUser() : null));

  const login = useCallback(async (email, password) => {
    const u = await apiLogin(email, password);
    setUser(u);
    return u;
  }, []);

  const register = useCallback(async (org, email, name, password) => {
    const u = await apiRegister(org, email, name, password);
    setUser(u);
    return u;
  }, []);

  const loginDemo = useCallback((opts) => {
    const u = demoLogin(opts);
    setUser(u);
    return u;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      isAuthenticated: !!user,
      login,
      register,
      loginDemo,
      logout,
      can: (permission) => hasPerm(permission, user),
    }),
    [user, login, register, loginDemo, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
