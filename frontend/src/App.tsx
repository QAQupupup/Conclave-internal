// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → Header(顶部) + 左侧 ChatPanel + 右侧三块
import { useState } from 'react'
import { MeetingProvider, useMeeting } from './store/MeetingContext.tsx'
import { Header } from './components/Header.tsx'
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

/** 会议主视图：四块布局 + 借调模态 + 冲突联动选中态 + 右侧 Tab 切换 */
function MeetingView() {
  const { reset } = useMeeting()
  // 右侧证据面板选中冲突（聊天流点击证据 ref 时联动高亮）
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  // 借调表单模态开关
  const [borrowOpen, setBorrowOpen] = useState(false)
  // 右侧面板当前激活 Tab
  const [rightTab, setRightTab] = useState<RightPanelTab>('topic')

  return (
    <div className="app-layout">
      <Header />
      <AgentGraph />
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

/** 根据是否已选会议切换视图 */
function AppShell() {
  const { meetingId } = useMeeting()
  const [tab, setTab] = useState<ViewTab>('meeting')

  return (
    <div className="app-shell">
      <MeetingSidebar />
      <div className="app-main">
        {!meetingId ? (
          <CreateMeeting />
        ) : (
          <>
            <TabBar tab={tab} onChange={setTab} />
            {tab === 'meeting' ? <MeetingView /> : <WorkspaceView />}
          </>
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <MeetingProvider>
      <AppShell />
    </MeetingProvider>
  )
}
