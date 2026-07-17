import { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { AppProvider, useApp } from './state/AppContext';
import RequireAuth from './components/RequireAuth';
import Topbar from './components/Topbar';
import NavRail from './components/NavRail';
import MeetingToolbar from './components/MeetingToolbar';
import ContextPanel from './components/ContextPanel';
import CommandPalette from './components/CommandPalette';
import LogPanel from './components/LogPanel';
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

function Shell() {
  const { openCmdk, closeCmdk, closeCtx, authExpired, clearAuthExpired } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  // 全局键盘快捷键：⌘K / Ctrl+K 打开命令面板，Esc 关闭浮层
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openCmdk();
      }
      if (e.key === 'Escape') {
        closeCmdk();
        closeCtx();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [openCmdk, closeCmdk, closeCtx]);

  // 全局 401 → authExpired → 跳转登录页（带 redirect 回原页面）
  useEffect(() => {
    if (authExpired && !location.pathname.startsWith('/login')) {
      const redirect = encodeURIComponent(location.pathname + location.search);
      navigate(`/login?redirect=${redirect}`, { replace: true });
      setTimeout(() => clearAuthExpired(), 100);
    }
  }, [authExpired, location.pathname, location.search, navigate, clearAuthExpired]);

  const isMeeting = location.pathname.startsWith('/meeting');

  return (
    <div className="app">
      <Topbar />
      <NavRail />
      {isMeeting && <MeetingToolbar />}

      <main className="content" id="main-content">
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

      <ContextPanel />
      <CommandPalette />
      <LogPanel />
      {authExpired && <SessionExpiredModal />}
    </div>
  );
}

/** 顶层路由：登录页不需要外壳和守卫 */
function RootRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={
        <RequireAuth>
          <Shell />
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
