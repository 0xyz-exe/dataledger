import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './AuthContext';
import { LoginPage } from '../features/auth/LoginPage';
import { RegisterPage } from '../features/auth/RegisterPage';
import { DashboardPage } from '../features/dashboard/DashboardPage';
import { DatasetsPage } from '../features/datasets/DatasetsPage';
import { ReconciliationPage } from '../features/reconciliation/ReconciliationPage';
import { DiscrepanciesPage } from '../features/discrepancies/DiscrepanciesPage';
import {
  LayoutDashboard, Database, GitMerge, AlertCircle,
  LogOut, ChevronDown, Moon, Sun,
} from 'lucide-react';

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } });

function Nav() {
  const { user, workspace, logout } = useAuth();
  const navigate = useNavigate();
  const [dark, setDark] = React.useState(() => document.documentElement.classList.contains('dark'));

  const toggleDark = () => {
    document.documentElement.classList.toggle('dark');
    setDark(d => !d);
  };

  const navCls = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
      isActive
        ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
        : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800'
    }`;

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-56 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col">
        <div className="px-4 py-5 border-b border-gray-200 dark:border-gray-800">
          <span className="text-lg font-bold text-blue-600 dark:text-blue-400">DataLedger</span>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{workspace?.name || '—'}</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <NavLink to="/dashboard" className={navCls}><LayoutDashboard size={16} />Overview</NavLink>
          <NavLink to="/datasets" className={navCls}><Database size={16} />Datasets</NavLink>
          <NavLink to="/reconciliation" className={navCls}><GitMerge size={16} />Reconciliation</NavLink>
          <NavLink to="/discrepancies" className={navCls}><AlertCircle size={16} />Discrepancies</NavLink>
        </nav>
        <div className="p-3 border-t border-gray-200 dark:border-gray-800 space-y-1">
          <button onClick={toggleDark} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md">
            {dark ? <Sun size={16} /> : <Moon size={16} />}
            {dark ? 'Light mode' : 'Dark mode'}
          </button>
          <button onClick={() => { logout(); navigate('/login'); }} className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md">
            <LogOut size={16} />Logout
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto bg-gray-50 dark:bg-gray-950">
        <Routes>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/datasets/*" element={<DatasetsPage />} />
          <Route path="/reconciliation/*" element={<ReconciliationPage />} />
          <Route path="/discrepancies" element={<DiscrepanciesPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function ProtectedLayout() {
  const { user, loading } = useAuth();
  if (loading) return <div className="h-screen flex items-center justify-center text-gray-500">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Nav />;
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/*" element={<ProtectedLayout />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
