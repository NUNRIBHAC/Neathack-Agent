import { createContext, useContext, useEffect, useState } from "react";
import api from "@/lib/api";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=anon, obj=user
  const [workspaces, setWorkspaces] = useState([]);
  const [activeWs, setActiveWs] = useState(localStorage.getItem("dr_ws") || null);

  const loadWorkspaces = async () => {
    const { data } = await api.get("/workspaces");
    setWorkspaces(data);
    if (data.length && !data.find((w) => w.id === localStorage.getItem("dr_ws"))) {
      setActiveWs(data[0].id);
      localStorage.setItem("dr_ws", data[0].id);
    }
    return data;
  };

  const bootstrap = async () => {
    if (window.location.hash?.includes("session_id=")) { return; } // AuthCallback handles it
    const token = localStorage.getItem("dr_token");
    if (!token) { setUser(false); return; }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
      await loadWorkspaces();
    } catch {
      localStorage.removeItem("dr_token");
      setUser(false);
    }
  };

  useEffect(() => { bootstrap(); }, []);

  const afterAuth = async (token, u, defaultWs) => {
    localStorage.setItem("dr_token", token);
    setUser(u);
    const ws = await loadWorkspaces();
    const target = defaultWs || (ws[0] && ws[0].id);
    if (target) { setActiveWs(target); localStorage.setItem("dr_ws", target); }
  };

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    await afterAuth(data.token, data.user);
  };
  const googleSession = async (sessionId) => {
    const { data } = await api.post("/auth/google/session", { session_id: sessionId });
    await afterAuth(data.token, data.user, data.default_workspace);
  };
  const register = async (email, password, name) => {
    const { data } = await api.post("/auth/register", { email, password, name });
    await afterAuth(data.token, data.user, data.default_workspace);
  };
  const logout = () => {
    localStorage.removeItem("dr_token");
    localStorage.removeItem("dr_ws");
    setUser(false);
    setWorkspaces([]);
  };
  const switchWs = (id) => { setActiveWs(id); localStorage.setItem("dr_ws", id); };

  return (
    <AuthCtx.Provider value={{ user, workspaces, activeWs, login, register, googleSession, logout, switchWs, loadWorkspaces, setActiveWs }}>
      {children}
    </AuthCtx.Provider>
  );
}