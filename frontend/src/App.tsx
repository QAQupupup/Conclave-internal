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
import { ModelSelector } from './components/ModelSelector.tsx'
import { IntervenePanel } from './components/IntervenePanel.tsx'
import { BorrowDialog } from './components/BorrowDialog.tsx'
import { BorrowApprovalDialog } from './components/BorrowApprovalDialog.tsx'
import { MeetingSidebar } from './components/MeetingSidebar.tsx'
import { WorkspacePanel } from './components/WorkspacePanel.tsx'
import { ThemeSettings } from './components/ThemeSettings.tsx'
import { SettingsPanel } from './components/SettingsPanel.tsx'
import { LandingPage } from './components/LandingPage.tsx'
import { TaskBoard } from './components/TaskBoard.tsx'
import { FloatingBadges, PanelModal } from './components/FloatingBadges.tsx'
import { DrawerMenu } from './components/DrawerMenu.tsx'
import { DashboardView } from './components/DashboardView.tsx'
import { PanelErrorBoundary } from './components/ErrorBoundary.tsx'
import type { BadgeItem } from './components/FloatingBadges.tsx'

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

/** 会议主视图：聊天流全宽 + 浮动徽标展开面板 */
function MeetingView({
  onOpenInWorkspace,
}: {
  onOpenInWorkspace?: (filePath: string) => void
}) {
  // [CON-12] useMeeting 返回 selectMeeting、connected 等上下文
  // 移除未用的 refreshMeeting 解构（实际无调用点）
  const { meetingId, selectMeeting, store } = useMeeting()
  // 右侧证据面板选中冲突（聊天流点击证据 ref 时联动高亮）
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  // 借调表单模态开关（用户手动发起）
  const [borrowOpen, setBorrowOpen] = useState(false)
  // 自动借调审批弹窗：监听 store 中的 pending_borrow_request
  const pendingBorrowRequest = store.meeting?.pending_borrow_request ?? null
  // 拓扑图折叠/展开状态
  const [graphCollapsed, setGraphCollapsed] = usePersistentState<boolean>(
    'conclave-graph-collapsed',
    false,
  )
  // 浮动徽标激活的面板 ID（空字符串表示全部关闭）
  const [activeBadge, setActiveBadge] = useState('')

  const badgeItems: BadgeItem[] = [
    { id: 'topic', label: '议题', icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <line x1="2" y1="4" x2="14" y2="4" />
        <line x1="2" y1="8" x2="11" y2="8" />
        <line x1="2" y1="12" x2="14" y2="12" />
      </svg>
    ) },
    { id: 'evidence', label: '证据', icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="7" cy="7" r="4.5" />
        <line x1="10.5" y1="10.5" x2="14" y2="14" />
      </svg>
    ) },
    { id: 'artifact', label: '产出', icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="5" width="12" height="9" rx="1.5" />
        <path d="M5 5V3.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1V5" />
      </svg>
    ) },
    { id: 'report', label: '报告', icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 1.5h7l3 3v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1z" />
        <path d="M10 1.5v3h3" />
        <line x1="5" y1="8" x2="11" y2="8" />
        <line x1="5" y1="11" x2="9" y2="11" />
      </svg>
    ) },
    { id: 'token', label: 'Token', icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <rect x="0.5" y="0.5" width="15" height="15" rx="3" fill="var(--bg-elev)" stroke="currentColor" strokeWidth="1.5" />
        <text x="8" y="12" textAnchor="middle" fontSize="9" fontWeight="600" fill="currentColor" fontFamily="system-ui, sans-serif">T</text>
      </svg>
    ) },
    { id: 'model', label: '模型', icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 1.5l5.5 3v7L8 14.5 2.5 11.5v-7z" />
        <path d="M8 1.5v13" />
        <path d="M2.5 4.5L8 8l5.5-3.5" />
      </svg>
    ) },
    { id: 'intervene', label: '介入', icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 2C4.7 2 2 4.7 2 8c0 1.1.3 2.1.8 3L2 14l3.2-.7C6.1 13.8 7 14 8 14c3.3 0 6-2.7 6-6s-2.7-6-6-6z" />
      </svg>
    ) },
  ]

  const badgeLabels: Record<string, string> = {
    topic: '议题与团队',
    evidence: '证据与裁决',
    artifact: '产出物',
    report: '会议报告',
    token: 'Token 消耗',
    model: '模型设置',
    intervene: '介入对话',
  }

  const renderPanelContent = (id: string) => {
    // [CON-05 修复] 面板级 ErrorBoundary 包裹，避免单个面板挂掉整个浮窗层
    // 关键路径：仅包面板内容；modal 标题栏、关闭按钮不受影响
    const wrap = (panelId: string, node: React.ReactNode) => (
      <PanelErrorBoundary panel={panelId}>{node}</PanelErrorBoundary>
    )
    switch (id) {
      case 'topic':
        return wrap('topic', <TopicPanel />)
      case 'evidence':
        return wrap('evidence',
          <EvidencePanel
            selectedConflictId={selectedConflictId}
            onSelectConflict={setSelectedConflictId}
          />,
        )
      case 'artifact':
        return wrap('artifact',
          <ArtifactPanel
            onOpenBorrow={() => setBorrowOpen(true)}
            onOpenInWorkspace={onOpenInWorkspace}
          />,
        )
      case 'report':
        return wrap('report', <ReportViewer />)
      case 'token':
        return wrap('token', <TokenPanel />)
      case 'model':
        return wrap('model', <ModelSelector meetingId={meetingId} showHeader />)
      case 'intervene':
        return wrap('intervene', <IntervenePanel onClose={() => setActiveBadge('')} />)
      default:
        return null
    }
  }

  return (
    <div className={`meeting-view${graphCollapsed ? ' graph-collapsed' : ''}`}>
      {/* 顶部：六步流程指示器 + 会议控制按钮 */}
      <div className="meeting-top-bar">
        <StageIndicator />
        <MeetingControls />
      </div>

      {/* 主体：拓扑图 + 聊天流全宽 */}
      <div className="app-layout">
        <div className="graph-slot">
          <AgentGraph />
          <button
            type="button"
            className="graph-collapse-btn"
            onClick={() => setGraphCollapsed(v => !v)}
            title={graphCollapsed ? '展开拓扑图' : '收起拓扑图'}
            aria-label={graphCollapsed ? '展开拓扑图' : '收起拓扑图'}
          >
            {graphCollapsed ? '▼' : '▲'}
          </button>
        </div>
        <div className="app-body app-body-full">
          <div className="chat-slot chat-slot-full">
            <ChatPanel onSelectRef={(ref) => setSelectedConflictId(ref)} />
          </div>
        </div>
        <button type="button" className="btn btn-ghost new-meeting-btn" onClick={() => selectMeeting(null)}>
          返回看板
        </button>

        {/* 浮动徽标 */}
        <FloatingBadges
          badges={badgeItems}
          activeId={activeBadge || null}
          onSelect={setActiveBadge}
        />

        {/* 面板弹窗 */}
        <PanelModal
          open={activeBadge !== ''}
          title={badgeLabels[activeBadge] || ''}
          onClose={() => setActiveBadge('')}
        >
          {activeBadge ? renderPanelContent(activeBadge) : null}
        </PanelModal>

        <BorrowDialog open={borrowOpen} onClose={() => setBorrowOpen(false)} />
        <BorrowApprovalDialog
          request={pendingBorrowRequest}
          onClose={() => {}}
        />
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
  // 左侧会议列表侧边栏的折叠/展开状态（持久化到 localStorage，默认折叠聚焦内容）
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState<boolean>(
    'conclave-sidebar-collapsed',
    true,
  )
  // 主题设置面板开关
  const [themeOpen, setThemeOpen] = useState(false)
  // LLM 设置面板开关
  const [settingsOpen, setSettingsOpen] = useState(false)
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
      <button
        type="button"
        className="btn btn-ghost settings-btn"
        onClick={() => setSettingsOpen(true)}
        title="LLM 设置"
      >
        ⚙ 设置
      </button>
    </div>
  )

  // 第二层：看板/运维面板（无 meetingId，有左侧抽屉菜单）
  if (!meetingId) {
    return (
      <div className="app-shell board-shell">
        <DrawerMenu currentPath={path} />
        <div className="board-main">
          {toolbar}
          {path === '/dashboard' ? (
            <DashboardView />
          ) : (
            <TaskBoard onBackToLanding={() => navigate('/')} />
          )}
          {themeOpen && <ThemeSettings onClose={() => setThemeOpen(false)} />}
          {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
        </div>
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
          <MeetingView onOpenInWorkspace={handleOpenInWorkspace} />
        ) : (
          <WorkspaceView meetingId={meetingId ?? undefined} initialFile={workspaceInitialFile} />
        )}
      </div>
      {themeOpen && <ThemeSettings onClose={() => setThemeOpen(false)} />}
      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
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
