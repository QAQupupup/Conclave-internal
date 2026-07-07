// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → 顶部流程指示器+控制按钮 / 拓扑图 / 左侧聊天流 + 右侧三块
import { useState } from 'react'
import { MeetingProvider, useMeeting } from './store/MeetingContext.tsx'
import { ThemeProvider, useTheme } from './store/ThemeContext.tsx'
import { usePersistentState } from './hooks/usePersistentState.ts'
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
import { CreateMeeting } from './components/CreateMeeting.tsx'
import { MeetingSidebar } from './components/MeetingSidebar.tsx'
import { WorkspacePanel } from './components/WorkspacePanel.tsx'
import { ThemeSettings } from './components/ThemeSettings.tsx'

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
function MeetingView() {
  const { reset } = useMeeting()
  // 右侧证据面板选中冲突（聊天流点击证据 ref 时联动高亮）
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  // 借调表单模态开关
  const [borrowOpen, setBorrowOpen] = useState(false)
  // 右侧面板当前激活 Tab
  const [rightTab, setRightTab] = useState<RightPanelTab>('topic')
  // 拓扑图折叠/展开状态（持久化到 localStorage）
  const [graphCollapsed, setGraphCollapsed] = usePersistentState<boolean>(
    'conclave-graph-collapsed',
    false,
  )

  return (
    <div className={`meeting-view${graphCollapsed ? ' graph-collapsed' : ''}`}>
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
          <ChatPanel onSelectRef={(ref) => setSelectedConflictId(ref)} />
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
            {rightTab === 'artifact' && <ArtifactPanel onOpenBorrow={() => setBorrowOpen(true)} />}
            {rightTab === 'report' && <ReportViewer />}
            {rightTab === 'token' && <TokenPanel />}
          </div>
        </div>
        <button type="button" className="btn btn-ghost new-meeting-btn" onClick={reset}>
          新建会议
        </button>
        <BorrowDialog open={borrowOpen} onClose={() => setBorrowOpen(false)} />
      </div>
    </div>
  )
}

/** 工作区视图：文件树 + 编辑器 + 终端 */
function WorkspaceView() {
  return (
    <div className="app-layout">
      <div className="workspace-view">
        <WorkspacePanel />
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

/** 根据是否已选会议切换视图 */
function AppShell() {
  const { meetingId } = useMeeting()
  const [tab, setTab] = useState<ViewTab>('meeting')
  // 左侧会议列表侧边栏的折叠/展开状态（持久化到 localStorage）
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState<boolean>(
    'conclave-sidebar-collapsed',
    false,
  )
  // 主题设置面板开关
  const [themeOpen, setThemeOpen] = useState(false)
  const { mode, toggleMode } = useTheme()

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
        {/* 顶部工具栏：主题切换 + 设置入口 */}
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
        {!meetingId ? (
          <CreateMeeting />
        ) : (
          <>
            <TabBar tab={tab} onChange={setTab} />
            {tab === 'meeting' ? <MeetingView /> : <WorkspaceView />}
          </>
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
