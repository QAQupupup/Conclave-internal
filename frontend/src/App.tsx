// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → 顶部流程指示器+控制按钮 / 拓扑图 / 左侧聊天流 + 右侧三块
import { useState } from 'react'
import { MeetingProvider, useMeeting } from './store/MeetingContext.tsx'
import { ThemeProvider, useTheme } from './store/ThemeContext.tsx'
import { usePersistentState } from './hooks/usePersistentState.ts'
import { useRouter } from './hooks/useRouter.ts'
import { navigate } from './lib/router.ts'
import { StageIndicator } from './components/StageIndicator.tsx'
import { MeetingControls } from './components/MeetingControls.tsx'
import { AgentGraph } from './components/AgentGraph.tsx'
import { ChatPanel } from './components/ChatPanel.tsx'
import { TopicPanel } from './components/TopicPanel.tsx'
import { EvidencePanel } from './components/EvidencePanel.tsx'
import { ArtifactPanel } from './components/ArtifactPanel.tsx'
import { ReportViewer } from './components/ReportViewer.tsx'
import { TokenPanel } from './components/TokenPanel.tsx'
import { BorrowDialog } from './components/BorrowDialog.tsx'
import { MeetingSidebar } from './components/MeetingSidebar.tsx'
import { WorkspacePanel } from './components/WorkspacePanel.tsx'
import { ThemeSettings } from './components/ThemeSettings.tsx'
import { LandingPage } from './components/LandingPage.tsx'
import { TaskBoard } from './components/TaskBoard.tsx'

/** 全局视图切换：会议 / 工作区 */
type ViewTab = 'meeting' | 'workspace'

/** 顶部 Tab 切换条 */
function TabBar({ tab, onChange }: { tab: ViewTab; onChange: (t: ViewTab) => void }) {
  return (
    <div className="tab-bar">
      <button
        className={`tab-btn ${tab === 'meeting' ? 'active' : ''}`}
        onClick={() => onChange('meeting')}
      >
        会议
      </button>
      <button
        className={`tab-btn ${tab === 'workspace' ? 'active' : ''}`}
        onClick={() => onChange('workspace')}
      >
        工作区
      </button>
    </div>
  )
}

/** 右侧面板 Tab：议题 / 证据 / 产出 / 报告 / Token */
type RightPanelTab = 'topic' | 'evidence' | 'artifact' | 'report' | 'token'

/** 会议主视图：顶部流程指示器+控制按钮 / 拓扑图 / 聊天流 + 右侧面板，借调模态 + 冲突联动选中态 + 右侧 Tab 切换 */
function MeetingView({
  onOpenInWorkspace,
  rightTab,
  setRightTab,
}: {
  onOpenInWorkspace?: (filePath: string) => void
  rightTab: RightPanelTab
  setRightTab: (t: RightPanelTab) => void
}) {
  const { reset } = useMeeting()
  // 右侧证据面板选中冲突（聊天流点击证据 ref 时联动高亮）
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  // 借调表单模态开关
  const [borrowOpen, setBorrowOpen] = useState(false)
  // 拓扑图折叠/展开状态（持久化到 localStorage）
  const [graphCollapsed, setGraphCollapsed] = usePersistentState<boolean>(
    'conclave-graph-collapsed',
    false,
  )
  // 聊天面板折叠/展开状态
  const [chatCollapsed, setChatCollapsed] = usePersistentState<boolean>(
    'conclave-chat-collapsed',
    false,
  )
  // 右侧面板折叠/展开状态
  const [rightCollapsed, setRightCollapsed] = usePersistentState<boolean>(
    'conclave-right-collapsed',
    false,
  )

  return (
    <div className={`meeting-view${graphCollapsed ? ' graph-collapsed' : ''}${chatCollapsed ? ' chat-collapsed' : ''}${rightCollapsed ? ' right-collapsed' : ''}`}>
      {/* 顶部：六步流程指示器 + 会议控制按钮（替代原 Header） */}
      <div className="meeting-top-bar">
        <StageIndicator />
        <MeetingControls />
      </div>

      {/* 主体：拓扑图 + 左侧聊天流 + 右侧三块面板 */}
      <div className="app-layout">
        <div className="graph-slot">
          <AgentGraph />
          <button
            type="button"
            className="graph-collapse-btn"
            onClick={() => setGraphCollapsed(v => !v)}
            title={graphCollapsed ? '展开拓扑图' : '收起拓扑图（专注聊天/内容）'}
            aria-label={graphCollapsed ? '展开拓扑图' : '收起拓扑图'}
          >
            {graphCollapsed ? '▼' : '▲'}
          </button>
        </div>
        <div className="app-body">
          <div className="chat-slot">
            <ChatPanel onSelectRef={(ref) => setSelectedConflictId(ref)} />
            <button
              type="button"
              className="panel-collapse-btn chat-collapse-btn"
              onClick={() => setChatCollapsed(v => !v)}
              title={chatCollapsed ? '展开聊天流' : '收起聊天流'}
              aria-label={chatCollapsed ? '展开聊天流' : '收起聊天流'}
            >
              {chatCollapsed ? '›' : '‹'}
            </button>
          </div>
          <div className="right-column-slot">
            <div className="right-column">
              <div className="right-tabs">
                <button
                  className={`right-tab ${rightTab === 'topic' ? 'active' : ''}`}
                  onClick={() => setRightTab('topic')}
                >
                  议题
                </button>
                <button
                  className={`right-tab ${rightTab === 'evidence' ? 'active' : ''}`}
                  onClick={() => setRightTab('evidence')}
                >
                  证据
                </button>
                <button
                  className={`right-tab ${rightTab === 'artifact' ? 'active' : ''}`}
                  onClick={() => setRightTab('artifact')}
                >
                  产出
                </button>
                <button
                  className={`right-tab ${rightTab === 'report' ? 'active' : ''}`}
                  onClick={() => setRightTab('report')}
                >
                  报告
                </button>
                <button
                  className={`right-tab ${rightTab === 'token' ? 'active' : ''}`}
                  onClick={() => setRightTab('token')}
                >
                  Token
                </button>
              </div>
              {rightTab === 'topic' && <TopicPanel />}
              {rightTab === 'evidence' && (
                <EvidencePanel
                  selectedConflictId={selectedConflictId}
                  onSelectConflict={setSelectedConflictId}
                />
              )}
              {rightTab === 'artifact' && (
                <ArtifactPanel
                  onOpenBorrow={() => setBorrowOpen(true)}
                  onOpenInWorkspace={onOpenInWorkspace}
                />
              )}
              {rightTab === 'report' && <ReportViewer />}
              {rightTab === 'token' && <TokenPanel />}
            </div>
            <button
              type="button"
              className="panel-collapse-btn right-collapse-btn"
              onClick={() => setRightCollapsed(v => !v)}
              title={rightCollapsed ? '展开右侧面板' : '收起右侧面板'}
              aria-label={rightCollapsed ? '展开右侧面板' : '收起右侧面板'}
            >
              {rightCollapsed ? '‹' : '›'}
            </button>
          </div>
        </div>
        <button type="button" className="btn btn-ghost new-meeting-btn" onClick={reset}>
          返回看板
        </button>
        <BorrowDialog open={borrowOpen} onClose={() => setBorrowOpen(false)} />
      </div>
    </div>
  )
}

/** 工作区视图：文件树 + 编辑器 + 终端 */
function WorkspaceView({ meetingId, initialFile }: { meetingId?: string; initialFile?: string }) {
  return (
    <div className="app-layout">
      <div className="workspace-view">
        <WorkspacePanel meetingId={meetingId} initialFile={initialFile} />
      </div>
    </div>
  )
}

/** 收起后的迷你侧边栏：只展示一个竖向标签 + 展开按钮，节省横向空间让用户专注内容 */
function CollapsedSidebar({ onExpand }: { onExpand: () => void }) {
  const { meetingId } = useMeeting()
  return (
    <div className="meeting-sidebar-collapsed">
      <button
        type="button"
        className="collapsed-expand-btn"
        onClick={onExpand}
        title="展开会议列表"
        aria-label="展开会议列表"
      >
        <span className="collapsed-icon">›</span>
        <span className="collapsed-label">会<br />议</span>
      </button>
      {meetingId && <div className="collapsed-dot" title="当前会议已选中" />}
    </div>
  )
}

/** 根据 URL path 切换三层视图：/ → 封面，/board → 看板，/meeting/:id → 会议 */
function AppShell() {
  const { meetingId } = useMeeting()
  const { path } = useRouter()
  const [tab, setTab] = useState<ViewTab>('meeting')
  // 右侧面板 Tab 状态提升到 AppShell，避免切换会议/工作区视图时丢失
  const [rightTab, setRightTab] = useState<RightPanelTab>('topic')
  // 左侧会议列表侧边栏的折叠/展开状态（持久化到 localStorage）
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState<boolean>(
    'conclave-sidebar-collapsed',
    false,
  )
  // 主题设置面板开关
  const [themeOpen, setThemeOpen] = useState(false)
  const { mode, toggleMode } = useTheme()
  // 工作区跨视图跳转：从产出物"在工作区打开"时记录初始文件，切到 workspace Tab
  const [workspaceInitialFile, setWorkspaceInitialFile] = useState<string | undefined>(undefined)

  /** 从会议产出物跳转到工作区 */
  const handleOpenInWorkspace = (filePath: string) => {
    setWorkspaceInitialFile(filePath)
    setTab('workspace')
  }

  // 第一层：封面页（仅 / 路由）
  if (path === '/') {
    return <LandingPage onEnter={() => navigate('/board')} />
  }

  // 主题工具栏（看板和会议视图共用）
  const toolbar = (
    <div className="app-toolbar">
      <button
        type="button"
        className="btn btn-ghost theme-toggle-btn"
        onClick={toggleMode}
        title={mode === 'light' ? '切换到暗色' : '切换到亮色'}
        aria-label="切换主题"
      >
        {mode === 'light' ? '☾' : '☀'}
      </button>
      <button
        type="button"
        className="btn btn-ghost theme-settings-btn"
        onClick={() => setThemeOpen(true)}
        title="主题设置"
      >
        主题
      </button>
    </div>
  )

  // 第二层：任务看板（/board 或其他非会议路由，无侧栏全宽）
  if (!meetingId) {
    return (
      <div className="app-shell board-shell">
        {toolbar}
        <TaskBoard onBackToLanding={() => navigate('/')} />
        {themeOpen && <ThemeSettings onClose={() => setThemeOpen(false)} />}
      </div>
    )
  }

  // 第三层：会议视图（/meeting/:id，侧栏 + 主体）
  return (
    <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className={`sidebar-zone${sidebarCollapsed ? ' is-collapsed' : ''}`}>
        <div className="sidebar-expanded-pane">
          <MeetingSidebar />
          <button
            type="button"
            className="sidebar-collapse-btn"
            onClick={() => setSidebarCollapsed(true)}
            title="收起会议列表（专注内容）"
            aria-label="收起会议列表"
          >
            ‹
          </button>
        </div>
        <div className="sidebar-collapsed-pane">
          <CollapsedSidebar onExpand={() => setSidebarCollapsed(false)} />
        </div>
      </aside>
      <div className="app-main">
        {toolbar}
        <TabBar tab={tab} onChange={setTab} />
        {tab === 'meeting' ? (
          <MeetingView
            onOpenInWorkspace={handleOpenInWorkspace}
            rightTab={rightTab}
            setRightTab={setRightTab}
          />
        ) : (
          <WorkspaceView meetingId={meetingId ?? undefined} initialFile={workspaceInitialFile} />
        )}
      </div>
      {themeOpen && <ThemeSettings onClose={() => setThemeOpen(false)} />}
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <MeetingProvider>
        <AppShell />
      </MeetingProvider>
    </ThemeProvider>
  )
}
