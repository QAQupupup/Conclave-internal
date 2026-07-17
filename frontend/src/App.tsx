import { useEffect } from 'react';
import { AppProvider, useApp } from './state/AppContext';
import Topbar from './components/Topbar';
import NavRail from './components/NavRail';
import MeetingToolbar from './components/MeetingToolbar';
import ContextPanel from './components/ContextPanel';
import CommandPalette from './components/CommandPalette';
import LogPanel from './components/LogPanel';
import LoginModal from './components/LoginModal';
import Landing from './views/Landing';
import Board from './views/Board';
import Meeting from './views/Meeting';
import Report from './views/Report';
import Models from './views/Models';
import Monitor from './views/Monitor';
import Topology from './views/Topology';
import Settings from './views/Settings';

function Shell() {
  const { view, openCmdk, closeCmdk, closeCtx } = useApp();

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

  return (
    <div className="app">
      <Topbar />
      <NavRail />
      {view === 'meeting' && <MeetingToolbar />}

      <main className="content" id="main-content">
        {view === 'landing' && <Landing />}
        {view === 'board' && <Board />}
        {view === 'meeting' && <Meeting />}
        {view === 'report' && <Report />}
        {view === 'models' && <Models />}
        {view === 'monitor' && <Monitor />}
        {view === 'topology' && <Topology />}
        {view === 'settings' && <Settings />}
      </main>

      <ContextPanel />
      <CommandPalette />
      <LogPanel />
      <LoginModal />
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
