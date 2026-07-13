// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → 顶部流程指示器+控制按钮 / 拓扑图 / 左侧聊天流 + 右侧三块
import { useState, useRef, useEffect } from 'react'
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
  SafetyOutlined,
  SafetyCertificateOutlined,
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
import { ModelsView } from './components/ModelsView.tsx'
import { PanelErrorBoundary } from './components/ErrorBoundary.tsx'
import { LogPanel } from './components/LogPanel.tsx'
import { CaptchaGuard } from './components/CaptchaGuard.tsx'
import type { BadgeItem } from './components/FloatingBadges.tsx'

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
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
      <div className="app-shell board-shell" style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
        <DrawerMenu currentPath={path} />
        <div className="board-main" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
          {/* 统一页面头部：标题 + 面包屑 + 工具栏 */}
          <div style={{
            padding: '16px 32px 12px',
            borderBottom: '1px solid var(--border, #e5e7eb)',
            background: 'var(--bg, #fff)',
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            gap: 16,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Typography.Title level={4} style={{ margin: 0, fontSize: 18 }}>{pageTitle}</Typography.Title>
              <div style={{ fontSize: 12, color: 'var(--text-secondary, #888)', marginTop: 2 }}>
                会议看板 / {pageTitle}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
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
          <div style={{
            flex: 1,
            overflowY: 'auto',
            padding: '24px 32px 32px',
            background: 'var(--bg-secondary, #f8f9fb)',
          }}>
            {path === '/dashboard' ? (
              <DashboardView />
            ) : path === '/models' ? (
              <ModelsView />
            ) : (
              <TaskBoard onBackToLanding={() => navigate('/')} />
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
    <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`} style={{ display: 'flex' }}>
      <aside className={`sidebar-zone${sidebarCollapsed ? ' is-collapsed' : ''}`}>
        {!sidebarCollapsed ? (
          <div className="sidebar-expanded-pane" style={{ position: 'relative' }}>
            <MeetingSidebar onCollapseSidebar={() => setSidebarCollapsed(true)} />
          </div>
        ) : (
          <div className="sidebar-collapsed-pane">
            <CollapsedSidebar onExpand={() => setSidebarCollapsed(false)} />
          </div>
        )}
      </aside>
      <div className="app-main" style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
        {/* 会议级统一导航栏：面包屑 + 返回 + 工具栏合为一行 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '10px 24px', borderBottom: '1px solid var(--border, #e5e7eb)',
          flexShrink: 0, minHeight: 44, background: 'var(--bg, #fff)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, minWidth: 0 }}>
            <a style={{ color: 'var(--accent, #4f46e5)', cursor: 'pointer', whiteSpace: 'nowrap' }}
               onClick={() => { selectMeeting(null); navigate('/board') }}>
              会议看板
            </a>
            <span style={{ color: 'var(--text-secondary, #999)' }}>/</span>
            <span style={{ color: 'var(--text-secondary, #666)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {store.meeting?.topic
                ? (store.meeting.topic.length > 30 ? store.meeting.topic.slice(0, 30) + '…' : store.meeting.topic)
                : meetingId}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
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
          style={{ padding: '0 24px', flexShrink: 0 }}
        />
        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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

/** CAPTCHA 守卫挂载点：仅在非首页显示，保持 WS 连接跨视图存活
 *  右侧吸边隐藏设计：
 *    - 常态：只露出浅蓝色小盾牌图标，贴紧右边缘，尽量少的遮挡内容
 *    - 悬停：向右展开为完整值守开关 + 状态标签
 *    - 鼠标移出 800ms 后自动收回为小盾牌
 */
function CaptchaGuardLayer() {
  const { path } = useRouter()
  const [expanded, setExpanded] = useState(false)
  const [guardStatus, setGuardStatus] = useState<{ guardMode: boolean; hasPending: boolean }>({ guardMode: false, hasPending: false })
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  if (path === '/') return null

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const handleMouseEnter = () => {
    clearTimer()
    setExpanded(true)
  }

  const handleMouseLeave = () => {
    timerRef.current = setTimeout(() => setExpanded(false), 800)
  }

  useEffect(() => {
    return () => { clearTimer() }
  }, [])

  const active = guardStatus.guardMode
  const pending = guardStatus.hasPending
  const shieldColor = pending ? '#ff4d4f' : active ? '#0958d9' : '#1677ff'
  const shieldBg = pending ? '#fff2f0' : active ? '#e6f4ff' : '#f0f7ff'

  return (
    <div
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        position: 'fixed',
        top: 56,
        right: 0,
        zIndex: 1100,
        display: 'flex',
        alignItems: 'center',
        width: expanded ? 260 : 28,
        height: 28,
        padding: expanded ? '5px 10px' : '5px 0 5px 5px',
        background: 'var(--bg, #fff)',
        border: '1px solid var(--border, #e5e7eb)',
        borderRight: 'none',
        borderRadius: '6px 0 0 6px',
        boxShadow: expanded ? '0 2px 8px rgba(0,0,0,0.08)' : '-2px 0 6px rgba(0,0,0,0.04)',
        overflow: 'hidden',
        whiteSpace: 'nowrap',
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        cursor: 'pointer',
      }}
    >
      {/* 小盾牌（常态与展开态均显示，作为视觉锚点） */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 18,
          height: 18,
          borderRadius: '50%',
          background: shieldBg,
          color: shieldColor,
          flexShrink: 0,
          transition: 'all 0.25s ease',
        }}
        title={active ? (pending ? '值守中 · 有待处理验证码' : '值守中') : '值守已关闭'}
      >
        {active ? <SafetyCertificateOutlined style={{ fontSize: 11 }} /> : <SafetyOutlined style={{ fontSize: 11 }} />}
      </div>

      {/* 展开面板 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginLeft: 8,
          opacity: expanded ? 1 : 0,
          transition: 'opacity 0.2s ease',
        }}
      >
        <CaptchaGuard compact onStatusChange={setGuardStatus} />
      </div>
    </div>
  )
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
