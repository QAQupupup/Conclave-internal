// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → 顶部流程指示器+控制按钮 / 拓扑图 / 左侧聊天流 + 右侧三块
import { useState, lazy, Suspense, useCallback, useEffect } from 'react'
import { ConfigProvider, Tabs, Button, Tooltip, Typography, Drawer, Divider, Breadcrumb, Dropdown } from 'antd'
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
  HomeOutlined,
  MenuOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  CloudServerOutlined,
} from '@ant-design/icons'
import { MeetingProvider, useMeeting } from './store/MeetingContext.tsx'
import { AuthProvider, useAuth } from './store/AuthContext.tsx'
import { ThemeProvider, useTheme } from './store/ThemeContext.tsx'
import { getAntdTheme } from './theme/antdTheme.ts'
import { usePersistentState } from './hooks/usePersistentState.ts'
import { useRouter } from './hooks/useRouter.ts'
import { navigate } from './lib/router.ts'
import { LoginPage } from './pages/LoginPage.tsx'
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
import { FloatingBadges, type PanelToggleState } from './components/FloatingBadges.tsx'
import { DrawerMenu } from './components/DrawerMenu.tsx'
import { PanelErrorBoundary } from './components/ErrorBoundary.tsx'
import { LogPanelContent } from './components/LogPanel.tsx'
import { GuardButton } from './components/GuardButton.tsx'
import { UserMenu } from './components/UserMenu.tsx'

// 代码分割：重型组件按需加载（Monaco/echarts/d3/xterm 不进首屏 bundle）
const AgentGraph = lazy(() => import('./components/AgentGraph.tsx').then(m => ({ default: m.AgentGraph })))
const ReportViewer = lazy(() => import('./components/ReportViewer.tsx').then(m => ({ default: m.ReportViewer })))
const WorkspacePanel = lazy(() => import('./components/WorkspacePanel.tsx').then(m => ({ default: m.WorkspacePanel })))
const DashboardView = lazy(() => import('./components/DashboardView.tsx').then(m => ({ default: m.DashboardView })))
const ModelsView = lazy(() => import('./components/ModelsView.tsx').then(m => ({ default: m.ModelsView })))
const TaskBoard = lazy(() => import('./components/TaskBoard.tsx').then(m => ({ default: m.TaskBoard })))

/** 全局视图切换：会议 / 工作区 */
type ViewTab = 'meeting' | 'workspace'

/** 会议主视图：聊天流全宽 + 顶部工具栏按钮 + 右侧 Drawer 面板 */
function MeetingView({
  onOpenInWorkspace,
}: {
  onOpenInWorkspace?: (filePath: string) => void
}) {
  const { meetingId, store, rejectBorrow, selectMeeting } = useMeeting()
  const meeting = store.meeting
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  const [borrowOpen, setBorrowOpen] = useState(false)
  const pendingBorrowRequest = meeting?.pending_borrow_request ?? null
  const [graphCollapsed, setGraphCollapsed] = usePersistentState<boolean>(
    'conclave-graph-collapsed',
    false,
  )

  // 面板开关状态（互斥：同一时间只开一个 Drawer）
  const [panels, setPanels] = useState<PanelToggleState>({
    topic: false, evidence: false, output: false, report: false,
    token: false, model: false, intervention: false, logs: false,
  })

  const togglePanel = useCallback((key: keyof PanelToggleState) => {
    setPanels(prev => {
      const next: PanelToggleState = {
        topic: false, evidence: false, output: false, report: false,
        token: false, model: false, intervention: false, logs: false,
      }
      next[key] = !prev[key]
      return next
    })
  }, [])

  // ESC 关闭 Drawer
  const closeDrawer = useCallback(() => {
    setPanels({
      topic: false, evidence: false, output: false, report: false,
      token: false, model: false, intervention: false, logs: false,
    })
  }, [])

  const pendingBorrow = !!pendingBorrowRequest
  const interventionCount = (meeting?.intervention_messages ?? []).filter(
    (m: { reply_to_id?: string | null; sender?: string }) => !m.reply_to_id && m.sender === 'user',
  ).length

  const activeDrawerKey = (Object.keys(panels) as Array<keyof PanelToggleState>).find(k => panels[k])
  const drawerTitles: Record<keyof PanelToggleState, string> = {
    topic: '议题聚焦',
    evidence: '证据面板',
    output: '产出物',
    report: '最终报告',
    token: 'Token 监控',
    model: '模型调度',
    intervention: '介入申请',
    logs: '实时日志',
  }

  const drawerWidth = activeDrawerKey === 'logs' ? 600
    : activeDrawerKey === 'output' || activeDrawerKey === 'token' ? 500
    : 440

  const wrap = (panelId: string, node: React.ReactNode) => (
    <PanelErrorBoundary panel={panelId}>{node}</PanelErrorBoundary>
  )

  const renderDrawerContent = () => {
    if (panels.topic) return wrap('topic', <TopicPanel />)
    if (panels.evidence) return wrap('evidence',
      <EvidencePanel selectedConflictId={selectedConflictId} onSelectConflict={setSelectedConflictId} />,
    )
    if (panels.output) return wrap('output',
      <ArtifactPanel onOpenBorrow={() => setBorrowOpen(true)} onOpenInWorkspace={onOpenInWorkspace} />,
    )
    if (panels.report) return wrap('report',
      <Suspense fallback={<div className="suspense-fallback">加载报告…</div>}><ReportViewer /></Suspense>,
    )
    if (panels.token) return wrap('token', <TokenPanel />)
    if (panels.model) return wrap('model', <ModelSelector meetingId={meetingId} showHeader />)
    if (panels.intervention) return wrap('intervene', <IntervenePanel onClose={closeDrawer} />)
    if (panels.logs) return wrap('logs', <LogPanelContent embedded />)
    return null
  }

  return (
    <div className={`meeting-view${graphCollapsed ? ' graph-collapsed' : ''}`}>
      <div className="meeting-top-bar">
        <StageIndicator />
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <FloatingBadges
            panels={panels}
            onToggle={togglePanel}
            pendingBorrow={pendingBorrow}
            interventionCount={interventionCount}
          />
          <div className="button-separator" style={{ width: 1, height: 20, background: 'var(--border-color, #e5e7eb)', margin: '0 4px' }} />
          <MeetingControls
            onOpenReport={() => togglePanel('report')}
            onBackToBoard={() => { selectMeeting(null); navigate('/board') }}
          />
        </div>
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

        {/* 右侧 Drawer 面板（互斥打开，mask=false 不遮挡聊天区） */}
        <Drawer
          title={activeDrawerKey ? drawerTitles[activeDrawerKey] : ''}
          placement="right"
          width={drawerWidth}
          open={!!activeDrawerKey}
          onClose={closeDrawer}
          mask={false}
          styles={{ body: { padding: 16, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' } }}
          zIndex={varZDrawer()}
        >
          {renderDrawerContent()}
        </Drawer>

        <BorrowDialog open={borrowOpen} onClose={() => setBorrowOpen(false)} />
        <BorrowApprovalDialog
          request={pendingBorrowRequest}
          onClose={() => {
            if (pendingBorrowRequest) {
              rejectBorrow(pendingBorrowRequest.id, '用户选择稍后处理')
            }
          }}
        />
      </div>
    </div>
  )
}

/** 读取 CSS 变量中 --z-drawer 的值，用于 AntD Drawer zIndex */
function varZDrawer(): number {
  if (typeof window === 'undefined') return 200
  const val = getComputedStyle(document.documentElement).getPropertyValue('--z-drawer').trim()
  const n = parseInt(val, 10)
  return isNaN(n) ? 200 : n
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
  const { logout, isAuthenticated, loading: authLoading } = useAuth()
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

  // P1-7: 切换会议时重置Tab为会议视图
  useEffect(() => {
    setTab('meeting')
    setWorkspaceInitialFile(undefined)
  }, [meetingId])

  // 统一退出登录逻辑
  const handleLogout = useCallback(() => {
    logout()
    navigate('/')
  }, [logout])

  // 全局导航菜单项（会议视图中使用）
  const globalNavItems = [
    {
      key: '/board',
      icon: <AppstoreOutlined />,
      label: '会议看板',
    },
    {
      key: '/dashboard',
      icon: <BarChartOutlined />,
      label: '运维面板',
    },
    {
      key: '/models',
      icon: <CloudServerOutlined />,
      label: '模型管理',
    },
  ]

  // 认证加载中：显示空白（避免闪烁）
  if (authLoading) {
    return <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }} />
  }

  // 未登录：显示登录页
  if (!isAuthenticated) {
    return <LoginPage />
  }

  // 第一层：封面页（仅 / 路由）
  if (path === '/') {
    return <LandingPage onEnter={() => navigate('/board')} />
  }

  // 第二层：看板/运维面板/模型管理（无 meetingId，有左侧抽屉菜单）
  if (!meetingId) {
    const pageTitles: Record<string, string> = {
      '/dashboard': '运维面板',
      '/models': '模型管理',
    }
    const pageTitle = pageTitles[path] || '会议看板'
    // 统一面包屑组件（可点击）
    const breadcrumbItems = [
      {
        title: <HomeOutlined onClick={() => navigate('/')} style={{ cursor: 'pointer' }} title="返回首页" />,
      },
      {
        title: path === '/board'
          ? '会议看板'
          : <a onClick={() => navigate('/board')}>会议看板</a>,
      },
      ...(path !== '/board' ? [{ title: pageTitle }] : []),
    ]
    return (
      <div className="app-shell board-shell">
        <DrawerMenu currentPath={path} />
        <div className="board-main">
          {/* 统一页面头部：标题 + 面包屑 + 工具栏 */}
          <div className="app-page-header">
            <div className="app-page-header-left">
              <Typography.Title level={4} className="app-page-title">{pageTitle}</Typography.Title>
              <Breadcrumb items={breadcrumbItems} className="app-page-breadcrumb" separator="/" />
            </div>
            <div className="toolbar-button-group" style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <GuardButton />
              <Divider type="vertical" style={{ height: 16, margin: '0 4px' }} />
              <Tooltip title={mode === 'light' ? '切换到暗色' : '切换到亮色'}>
                <Button type="text" size="small"
                  icon={mode === 'light' ? <MoonOutlined /> : <SunOutlined />}
                  onClick={toggleMode} />
              </Tooltip>
              <Tooltip title="主题设置">
                <Button type="text" size="small" icon={<SkinOutlined />}
                  onClick={() => setThemeOpen(true)} />
              </Tooltip>
              <Tooltip title="设置">
                <Button type="text" size="small" icon={<SettingOutlined />}
                  onClick={() => setSettingsOpen(true)} />
              </Tooltip>
              <UserMenu
                onOpenSettings={() => setSettingsOpen(true)}
                onNavigateBoard={() => navigate('/board')}
                onLogout={handleLogout}
              />
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
  const topic = store.meeting?.topic
    ? (store.meeting.topic.length > 30 ? store.meeting.topic.slice(0, 30) + '…' : store.meeting.topic)
    : meetingId

  // 会议级面包屑
  const meetingBreadcrumbItems = [
    {
      title: <HomeOutlined onClick={() => navigate('/')} style={{ cursor: 'pointer' }} title="返回首页" />,
    },
    {
      title: <a onClick={() => { selectMeeting(null); navigate('/board') }}>会议看板</a>,
    },
    {
      title: <span title={store.meeting?.topic}>{topic}</span>,
    },
  ]

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
        {/* 会议级统一导航栏：面包屑 + 全局导航 + 值守 + 主题/设置 */}
        <div className="app-meeting-navbar">
          <div className="breadcrumb-area" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Dropdown
              menu={{
                items: globalNavItems,
                onClick: ({ key }) => {
                  if (key === '/board') {
                    selectMeeting(null)
                  }
                  navigate(key)
                },
              }}
              placement="bottomLeft"
              trigger={['click']}
            >
              <Tooltip title="全局导航">
                <Button type="text" size="small" icon={<MenuOutlined />} />
              </Tooltip>
            </Dropdown>
            <Breadcrumb items={meetingBreadcrumbItems} separator="/" />
          </div>
          <div className="app-meeting-actions" style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <GuardButton />
            <Divider type="vertical" style={{ height: 16, margin: '0 4px' }} />
            <Tooltip title={mode === 'light' ? '切换到暗色' : '切换到亮色'}>
              <Button type="text" size="small"
                icon={mode === 'light' ? <MoonOutlined /> : <SunOutlined />}
                onClick={toggleMode} />
            </Tooltip>
            <Tooltip title="主题设置">
              <Button type="text" size="small" icon={<SkinOutlined />}
                onClick={() => setThemeOpen(true)} />
            </Tooltip>
            <Tooltip title="设置">
              <Button type="text" size="small" icon={<SettingOutlined />}
                onClick={() => setSettingsOpen(true)} />
            </Tooltip>
            <UserMenu
              onOpenSettings={() => setSettingsOpen(true)}
              onNavigateBoard={() => { selectMeeting(null); navigate('/board') }}
              onLogout={handleLogout}
            />
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
        <AuthProvider>
          <MeetingProvider>
            <AppShell />
          </MeetingProvider>
        </AuthProvider>
      </AntdThemeWrapper>
    </ThemeProvider>
  )
}
