// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → 顶部流程指示器+控制按钮 / 拓扑图 / 左侧聊天流 + 右侧三块
import { useState } from 'react'
import { ConfigProvider, Tabs, Button, Tooltip } from 'antd'
import {
  TeamOutlined,
  CodeOutlined,
  MoonOutlined,
  SunOutlined,
  SettingOutlined,
  SkinOutlined,
  ArrowLeftOutlined,
  UpOutlined,
  DownOutlined,
  MenuFoldOutlined,
  UnorderedListOutlined,
  SearchOutlined,
  ShopOutlined,
  FileTextOutlined,
  DollarOutlined,
  AppstoreOutlined,
  MessageOutlined,
} from '@ant-design/icons'
import { MeetingProvider, useMeeting } from './store/MeetingContext.tsx'
import { ThemeProvider, useTheme } from './store/ThemeContext.tsx'
import { getAntdTheme } from './theme/antdTheme.ts'
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

/** 会议主视图：聊天流全宽 + 浮动徽标展开面板 */
function MeetingView({
  onOpenInWorkspace,
}: {
  onOpenInWorkspace?: (filePath: string) => void
}) {
  const { meetingId, selectMeeting, store } = useMeeting()
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  const [borrowOpen, setBorrowOpen] = useState(false)
  const pendingBorrowRequest = store.meeting?.pending_borrow_request ?? null
  const [graphCollapsed, setGraphCollapsed] = usePersistentState<boolean>(
    'conclave-graph-collapsed',
    false,
  )
  const [activeBadge, setActiveBadge] = useState('')

  const badgeItems: BadgeItem[] = [
    { id: 'topic', label: '议题', icon: <UnorderedListOutlined /> },
    { id: 'evidence', label: '证据', icon: <SearchOutlined /> },
    { id: 'artifact', label: '产出', icon: <ShopOutlined /> },
    { id: 'report', label: '报告', icon: <FileTextOutlined /> },
    { id: 'token', label: 'Token', icon: <DollarOutlined /> },
    { id: 'model', label: '模型', icon: <AppstoreOutlined /> },
    { id: 'intervene', label: '介入', icon: <MessageOutlined /> },
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
      <div className="meeting-top-bar">
        <StageIndicator />
        <MeetingControls />
      </div>

      <div className="app-layout">
        <div className="graph-slot">
          <AgentGraph />
          <Tooltip title={graphCollapsed ? '展开拓扑图' : '收起拓扑图'}>
            <Button
              type="text"
              size="small"
              icon={graphCollapsed ? <DownOutlined /> : <UpOutlined />}
              className="graph-collapse-btn"
              onClick={() => setGraphCollapsed(v => !v)}
            />
          </Tooltip>
        </div>
        <div className="app-body app-body-full">
          <div className="chat-slot chat-slot-full">
            <ChatPanel onSelectRef={(ref) => setSelectedConflictId(ref)} />
          </div>
        </div>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => selectMeeting(null)}
          style={{ position: 'absolute', top: 12, right: 12, zIndex: 10 }}
        >
          返回看板
        </Button>

        <FloatingBadges
          badges={badgeItems}
          activeId={activeBadge || null}
          onSelect={setActiveBadge}
        />

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

/** 收起后的迷你侧边栏 */
function CollapsedSidebar({ onExpand }: { onExpand: () => void }) {
  const { meetingId } = useMeeting()
  return (
    <div className="meeting-sidebar-collapsed" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '16px 4px', gap: 8 }}>
      <Tooltip title="展开会议列表" placement="right">
        <Button
          type="text"
          icon={<MenuFoldOutlined />}
          onClick={onExpand}
          style={{ height: 40, width: 40 }}
        />
      </Tooltip>
      {meetingId && <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-color, #4f46e5)' }} title="当前会议已选中" />}
    </div>
  )
}

/** 根据 URL path 切换三层视图：/ → 封面，/board → 看板，/meeting/:id → 会议 */
function AppShell() {
  const { meetingId } = useMeeting()
  const { path } = useRouter()
  const [tab, setTab] = useState<ViewTab>('meeting')
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState<boolean>(
    'conclave-sidebar-collapsed',
    true,
  )
  const [themeOpen, setThemeOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { mode, toggleMode } = useTheme()
  const [workspaceInitialFile, setWorkspaceInitialFile] = useState<string | undefined>(undefined)

  const handleOpenInWorkspace = (filePath: string) => {
    setWorkspaceInitialFile(filePath)
    setTab('workspace')
  }

  // 第一层：封面页（仅 / 路由）
  if (path === '/') {
    return <LandingPage onEnter={() => navigate('/board')} />
  }

  // 主题工具栏
  const toolbar = (
    <div className="app-toolbar" style={{ display: 'flex', justifyContent: 'flex-end', gap: 4, padding: '8px 12px' }}>
      <Tooltip title={mode === 'light' ? '切换到暗色' : '切换到亮色'}>
        <Button
          type="text"
          size="small"
          icon={mode === 'light' ? <MoonOutlined /> : <SunOutlined />}
          onClick={toggleMode}
        />
      </Tooltip>
      <Tooltip title="主题设置">
        <Button
          type="text"
          size="small"
          icon={<SkinOutlined />}
          onClick={() => setThemeOpen(true)}
        >
          主题
        </Button>
      </Tooltip>
      <Tooltip title="LLM 设置">
        <Button
          type="text"
          size="small"
          icon={<SettingOutlined />}
          onClick={() => setSettingsOpen(true)}
        >
          设置
        </Button>
      </Tooltip>
    </div>
  )

  // 第二层：看板/运维面板（无 meetingId，有左侧抽屉菜单）
  if (!meetingId) {
    return (
      <div className="app-shell board-shell" style={{ display: 'flex' }}>
        <DrawerMenu currentPath={path} />
        <div className="board-main" style={{ flex: 1 }}>
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
    <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`} style={{ display: 'flex' }}>
      <aside className={`sidebar-zone${sidebarCollapsed ? ' is-collapsed' : ''}`}>
        {!sidebarCollapsed ? (
          <div className="sidebar-expanded-pane" style={{ position: 'relative' }}>
            <MeetingSidebar />
            <Tooltip title="收起会议列表（专注内容）">
              <Button
                type="text"
                size="small"
                icon={<MenuFoldOutlined />}
                className="sidebar-collapse-btn"
                onClick={() => setSidebarCollapsed(true)}
                style={{ position: 'absolute', top: 8, right: 8, zIndex: 2 }}
              />
            </Tooltip>
          </div>
        ) : (
          <div className="sidebar-collapsed-pane">
            <CollapsedSidebar onExpand={() => setSidebarCollapsed(false)} />
          </div>
        )}
      </aside>
      <div className="app-main" style={{ flex: 1 }}>
        {toolbar}
        <Tabs
          activeKey={tab}
          onChange={(key) => setTab(key as ViewTab)}
          items={[
            { key: 'meeting', label: <span><TeamOutlined /> 会议</span> },
            { key: 'workspace', label: <span><CodeOutlined /> 工作区</span> },
          ]}
          style={{ padding: '0 16px' }}
        />
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

/** AntD ConfigProvider 桥接层 */
function AntdThemeWrapper({ children }: { children: React.ReactNode }) {
  const { mode } = useTheme()
  return (
    <ConfigProvider theme={getAntdTheme(mode)}>
      {children}
    </ConfigProvider>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AntdThemeWrapper>
        <MeetingProvider>
          <AppShell />
        </MeetingProvider>
      </AntdThemeWrapper>
    </ThemeProvider>
  )
}
