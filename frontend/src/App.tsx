import { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { AppProvider, useApp } from './state/AppContext';
import { ToastProvider, useToast } from './components/Toast';
import ErrorBoundary from './components/ErrorBoundary';
import ConfirmModal from './components/ConfirmModal';
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

/** 将 Toast 函数桥接到 AppContext（AppContext 初始化时 ToastProvider 尚未挂载） */
function ToastBridge() {
  const { show } = useToast();
  const { _setToastFn } = useApp();
  useEffect(() => { _setToastFn(show); }, [show, _setToastFn]);
  return null;
}

function Shell() {
  const { openCmdk, closeCmdk, closeCtx, authExpired, clearAuthExpired, confirmState, resolveConfirm } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  // 全局键盘快捷键
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

  // 全局 401 → 跳转登录页
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
        <ErrorBoundary>
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
        </ErrorBoundary>
      </main>

      <ContextPanel />
      <CommandPalette />
      <LogPanel />
      {authExpired && <SessionExpiredModal />}
      {confirmState && (
        <ConfirmModal
          open={!!confirmState}
          title={confirmState.title}
          message={confirmState.message}
          confirmText={confirmState.confirmText}
          cancelText={confirmState.cancelText}
          danger={confirmState.danger}
          onConfirm={() => resolveConfirm(true)}
          onCancel={() => resolveConfirm(false)}
        />
      )}
    </div>
  );
}

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
      <ToastProvider>
        <ToastBridge />
        <ErrorBoundary>
          <RootRoutes />
        </ErrorBoundary>
      </ToastProvider>
    </AppProvider>
  );
}
