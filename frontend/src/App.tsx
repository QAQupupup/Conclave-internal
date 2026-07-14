// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → 顶部流程指示器+控制按钮 / 拓扑图 / 左侧聊天流 + 右侧三块
import { useState, lazy, Suspense } from 'react'
import { ConfigProvider, Tabs, Button, Tooltip, Typography } from 'antd'
import {
  TeamOutlined,
  CodeOutlined,
  MoonOutlined,
  SunOutlined,
  SettingOutlined,
  SkinOutlined,
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
import { ChatPanel } from './components/ChatPanel.tsx'
import { TopicPanel } from './components/TopicPanel.tsx'
import { EvidencePanel } from './components/EvidencePanel.tsx'
import { ArtifactPanel } from './components/ArtifactPanel.tsx'
import { TokenPanel } from './components/TokenPanel.tsx'
import { ModelSelector } from './components/ModelSelector.tsx'
import { IntervenePanel } from './components/IntervenePanel.tsx'
import { BorrowDialog } from './components/BorrowDialog.tsx'
import { BorrowApprovalDialog } from './components/BorrowApprovalDialog.tsx'
import { MeetingSidebar } from './components/MeetingSidebar.tsx'
import { ThemeSettings } from './components/ThemeSettings.tsx'
import { SettingsPanel } from './components/SettingsPanel.tsx'
import { LandingPage } from './components/LandingPage.tsx'
import { FloatingBadges, PanelModal } from './components/FloatingBadges.tsx'
import { DrawerMenu } from './components/DrawerMenu.tsx'
import { PanelErrorBoundary } from './components/ErrorBoundary.tsx'
import { LogPanel } from './components/LogPanel.tsx'
import { GuardButton } from './components/GuardButton.tsx'
import type { BadgeItem } from './components/FloatingBadges.tsx'

// 代码分割：重型组件按需加载（Monaco/echarts/d3/xterm 不进首屏 bundle）
const AgentGraph = lazy(() => import('./components/AgentGraph.tsx').then(m => ({ default: m.AgentGraph })))
const ReportViewer = lazy(() => import('./components/ReportViewer.tsx').then(m => ({ default: m.ReportViewer })))
const WorkspacePanel = lazy(() => import('./components/WorkspacePanel.tsx').then(m => ({ default: m.WorkspacePanel })))
const DashboardView = lazy(() => import('./components/DashboardView.tsx').then(m => ({ default: m.DashboardView })))
const ModelsView = lazy(() => import('./components/ModelsView.tsx').then(m => ({ default: m.ModelsView })))
const TaskBoard = lazy(() => import('./components/TaskBoard.tsx').then(m => ({ default: m.TaskBoard })))

/** 全局视图切换：会议 / 工作区 */
type ViewTab = 'meeting' | 'workspace'

/** 会议主视图：聊天流全宽 + 浮动徽标展开面板 */
function MeetingView({
  onOpenInWorkspace,
}: {
  onOpenInWorkspace?: (filePath: string) => void
}) {
  const { meetingId, store } = useMeeting()
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
        return wrap('report', <Suspense fallback={<div className="suspense-fallback">加载报告…</div>}><ReportViewer /></Suspense>)
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
          <Suspense fallback={<div className="suspense-fallback">加载拓扑图…</div>}><AgentGraph /></Suspense>
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
    <div className="flex-col-overflow">
      <div className="workspace-view">
        <Suspense fallback={<div className="suspense-fallback">加载工作区…</div>}><WorkspacePanel meetingId={meetingId} initialFile={initialFile} /></Suspense>
      </div>
    </div>
  )
}

/** 收起后的迷你侧边栏 */
function CollapsedSidebar({ onExpand }: { onExpand: () => void }) {
  const { meetingId } = useMeeting()
  return (
    <div className="meeting-sidebar-collapsed app-collapsed-sidebar-extra">
      <Tooltip title="展开会议列表" placement="right">
        <Button
          type="text"
          icon={<MenuFoldOutlined />}
          onClick={onExpand}
          className="app-collapsed-sidebar-btn"
        />
      </Tooltip>
      {meetingId && <div className="app-collapsed-sidebar-dot" title="当前会议已选中" />}
    </div>
  )
}

/** 根据 URL path 切换三层视图：/ → 封面，/board → 看板，/models → 模型管理，/meeting/:id → 会议 */
function AppShell() {
  const { meetingId, store, selectMeeting } = useMeeting()
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

  // 第一层：封面页（仅 / 路由）—— CaptchaGuard 由外层 CaptchaGuardLayer 控制不在首页显示
  if (path === '/') {
    return <LandingPage onEnter={() => navigate('/board')} />
  }

  // 第二层：看板/运维面板/模型管理（无 meetingId，有左侧抽屉菜单）
  if (!meetingId) {
    const pageTitles: Record<string, string> = {
      '/dashboard': '会议看板',
      '/models': '模型管理',
      '/ops': '运维面板',
    }
    const pageTitle = pageTitles[path] || '页面'
    return (
      <div className="app-shell board-shell">
        <DrawerMenu currentPath={path} />
        <div className="board-main">
          {/* 统一页面头部：标题 + 面包屑 + 工具栏 */}
          <div className="app-page-header">
            <div className="app-page-header-left">
              <Typography.Title level={4} className="app-page-title">{pageTitle}</Typography.Title>
              <div className="app-page-breadcrumb">
                会议看板 / {pageTitle}
              </div>
            </div>
            <div className="toolbar-button-group">
              <Tooltip title={mode === 'light' ? '切换到暗色' : '切换到亮色'}>
                <Button type="text" size="small"
                  icon={mode === 'light' ? <MoonOutlined /> : <SunOutlined />}
                  onClick={toggleMode} />
              </Tooltip>
              <Tooltip title="主题设置">
                <Button type="text" size="small" icon={<SkinOutlined />}
                  onClick={() => setThemeOpen(true)}>主题</Button>
              </Tooltip>
              <Tooltip title="设置">
                <Button type="text" size="small" icon={<SettingOutlined />}
                  onClick={() => setSettingsOpen(true)}>设置</Button>
              </Tooltip>
            </div>
          </div>
          {/* 页面内容区，统一padding，可滚动 */}
          <div className="app-page-content">
            {path === '/dashboard' ? (
              <Suspense fallback={<div className="suspense-fallback">加载看板…</div>}><DashboardView /></Suspense>
            ) : path === '/models' ? (
              <Suspense fallback={<div className="suspense-fallback">加载模型管理…</div>}><ModelsView /></Suspense>
            ) : (
              <Suspense fallback={<div className="suspense-fallback">加载会议…</div>}><TaskBoard onBackToLanding={() => navigate('/')} /></Suspense>
            )}
          </div>
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
        {!sidebarCollapsed ? (
          <div className="sidebar-expanded-pane app-sidebar-pane-relative">
            <MeetingSidebar onCollapseSidebar={() => setSidebarCollapsed(true)} />
          </div>
        ) : (
          <div className="sidebar-collapsed-pane">
            <CollapsedSidebar onExpand={() => setSidebarCollapsed(false)} />
          </div>
        )}
      </aside>
      <div className="app-main">
        {/* 会议级统一导航栏：面包屑 + 返回 + 工具栏合为一行 */}
        <div className="app-meeting-navbar">
          <div className="breadcrumb-area">
            <a className="app-breadcrumb-link"
               onClick={() => { selectMeeting(null); navigate('/board') }}>
              会议看板
            </a>
            <span className="app-breadcrumb-sep">/</span>
            <span className="app-breadcrumb-topic">
              {store.meeting?.topic
                ? (store.meeting.topic.length > 30 ? store.meeting.topic.slice(0, 30) + '…' : store.meeting.topic)
                : meetingId}
            </span>
          </div>
          <div className="app-meeting-actions">
            <Tooltip title={mode === 'light' ? '切换到暗色' : '切换到亮色'}>
              <Button type="text" size="small"
                icon={mode === 'light' ? <MoonOutlined /> : <SunOutlined />}
                onClick={toggleMode} />
            </Tooltip>
            <Tooltip title="主题设置">
              <Button type="text" size="small" icon={<SkinOutlined />}
                onClick={() => setThemeOpen(true)} />
            </Tooltip>
            <Tooltip title="LLM 设置">
              <Button type="text" size="small" icon={<SettingOutlined />}
                onClick={() => setSettingsOpen(true)} />
            </Tooltip>
          </div>
        </div>
        <Tabs
          activeKey={tab}
          onChange={(key) => setTab(key as ViewTab)}
          items={[
            { key: 'meeting', label: <span><TeamOutlined /> 会议</span> },
            { key: 'workspace', label: <span><CodeOutlined /> 工作区</span> },
          ]}
          className="app-meeting-tabs"
        />
        <div className="flex-col-overflow">
          {tab === 'meeting' ? (
            <MeetingView onOpenInWorkspace={handleOpenInWorkspace} />
          ) : (
            <WorkspaceView meetingId={meetingId ?? undefined} initialFile={workspaceInitialFile} />
          )}
        </div>
      </div>
      {themeOpen && <ThemeSettings onClose={() => setThemeOpen(false)} />}
      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
      <LogPanel />
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

function CaptchaGuardLayer() {
  const { path } = useRouter()
  return <GuardButton path={path} />
}

export default function App() {
  return (
    <ThemeProvider>
      <AntdThemeWrapper>
        <MeetingProvider>
          <AppShell />
        </MeetingProvider>
        <CaptchaGuardLayer />
      </AntdThemeWrapper>
    </ThemeProvider>
  )
}
