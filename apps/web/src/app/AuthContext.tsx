import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { auth, setToken, clearToken, workspaces, type Workspace } from '../lib/api';

interface AuthState {
  user: { id: string; email: string; display_name: string } | null;
  workspace: Workspace | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, display_name: string, password: string) => Promise<void>;
  logout: () => void;
  setActiveWorkspace: (ws: Workspace) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthState['user']>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [token, setTokenState] = useState<string | null>(localStorage.getItem('dl_token'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (token) {
      auth.me()
        .then(setUser)
        .then(() => workspaces.list())
        .then((wsList) => {
          const saved = localStorage.getItem('dl_workspace');
          const found = saved ? wsList.find(w => w.id === saved) : null;
          setWorkspace(found || wsList[0] || null);
        })
        .catch(() => { clearToken(); setTokenState(null); })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [token]);

  const login = async (email: string, password: string) => {
    const res = await auth.login(email, password);
    setToken(res.access_token);
    setTokenState(res.access_token);
    const me = await auth.me();
    setUser(me);
    const wsList = await workspaces.list();
    setWorkspace(wsList[0] || null);
    if (wsList[0]) localStorage.setItem('dl_workspace', wsList[0].id);
  };

  const register = async (email: string, display_name: string, password: string) => {
    const res = await auth.register(email, display_name, password);
    setToken(res.access_token);
    setTokenState(res.access_token);
    const me = await auth.me();
    setUser(me);
    const wsList = await workspaces.list();
    setWorkspace(wsList[0] || null);
    if (wsList[0]) localStorage.setItem('dl_workspace', wsList[0].id);
  };

  const logout = () => {
    clearToken();
    setUser(null);
    setWorkspace(null);
    setTokenState(null);
  };

  const setActiveWorkspace = (ws: Workspace) => {
    setWorkspace(ws);
    localStorage.setItem('dl_workspace', ws.id);
  };

  return (
    <AuthContext.Provider value={{ user, workspace, token, loading, login, register, logout, setActiveWorkspace }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
