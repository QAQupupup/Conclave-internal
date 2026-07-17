import { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { AppProvider, useApp } from './state/AppContext';
import RequireAuth from './components/RequireAuth';
import Topbar from './components/Topbar';
import NavRail from './components/NavRail';
import LogPanel from './components/LogPanel';
import CommandPalette from './components/CommandPalette';
import ContextPanel from './components/ContextPanel';
import SessionExpiredModal from './components/SessionExpiredModal';
import Landing from './views/Landing';
import Board from './views/Board';
import Meeting from './views/Meeting';
import Report from './views/Report';
import Models from './views/Models';
import Monitor from './views/Monitor';
import Topology from './views/Topology';
import Settings from './views/Settings';
import Login from './views/Login';

/** 受保护的应用外壳（Topbar + NavRail + 视图区域） */
function ProtectedShell() {
  const { authExpired } = useApp();

  return (
    <div className="app">
      <Topbar />
      <div className="app-body">
        <NavRail />
        <main className="app-main">
          <Routes>
            <Route index element={<Landing />} />
            <Route path="board" element={<Board />} />
            <Route path="meeting/:id" element={<Meeting />} />
            <Route path="meeting" element={<Meeting />} />
            <Route path="report/:id" element={<Report />} />
            <Route path="report" element={<Report />} />
            <Route path="models" element={<Models />} />
            <Route path="monitor" element={<Monitor />} />
            <Route path="topology" element={<Topology />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="" replace />} />
          </Routes>
        </main>
      </div>
      <LogPanel />
      <CommandPalette />
      <ContextPanel />
      {authExpired && <SessionExpiredModal />}
    </div>
  );
}

/** 顶层路由：登录页不需要外壳和守卫 */
function RootRoutes() {
  const { authExpired, clearAuthExpired } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  // 全局 401 → authExpired → 跳转登录页（带 redirect 回原页面）
  useEffect(() => {
    if (authExpired && !location.pathname.startsWith('/login')) {
      const redirect = encodeURIComponent(location.pathname + location.search);
      navigate(`/login?redirect=${redirect}`, { replace: true });
      setTimeout(() => clearAuthExpired(), 100);
    }
  }, [authExpired, location.pathname, location.search, navigate, clearAuthExpired]);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={
        <RequireAuth>
          <ProtectedShell />
        </RequireAuth>
      } />
    </Routes>
  );
}

export default function App() {
  return (
    <AppProvider>
      <RootRoutes />
    </AppProvider>
  );
}
