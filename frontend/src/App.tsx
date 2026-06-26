// 应用根组件：组装四块布局
// meetingId 为空 → 创建页；否则 → Header(顶部) + 左侧 ChatPanel + 右侧三块
import { useState } from 'react'
import { MeetingProvider, useMeeting } from './store/MeetingContext.tsx'
import { Header } from './components/Header.tsx'
import { ChatPanel } from './components/ChatPanel.tsx'
import { TopicPanel } from './components/TopicPanel.tsx'
import { EvidencePanel } from './components/EvidencePanel.tsx'
import { ArtifactPanel } from './components/ArtifactPanel.tsx'
import { BorrowDialog } from './components/BorrowDialog.tsx'
import { CreateMeeting } from './components/CreateMeeting.tsx'

/** 会议主视图：四块布局 + 借调模态 + 冲突联动选中态 */
function MeetingView() {
  const { reset } = useMeeting()
  // 右侧证据面板选中冲突（聊天流点击证据 ref 时联动高亮）
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  // 借调表单模态开关
  const [borrowOpen, setBorrowOpen] = useState(false)

  return (
    <div className="app-layout">
      <Header />
      <div className="app-body">
        <ChatPanel onSelectRef={(ref) => setSelectedConflictId(ref)} />
        <div className="right-column">
          <TopicPanel />
          <EvidencePanel
            selectedConflictId={selectedConflictId}
            onSelectConflict={setSelectedConflictId}
          />
          <ArtifactPanel onOpenBorrow={() => setBorrowOpen(true)} />
        </div>
      </div>
      <button type="button" className="btn btn-ghost new-meeting-btn" onClick={reset}>
        新建会议
      </button>
      <BorrowDialog open={borrowOpen} onClose={() => setBorrowOpen(false)} />
    </div>
  )
}

/** 根据是否已选会议切换视图 */
function AppShell() {
  const { meetingId } = useMeeting()
  if (!meetingId) return <CreateMeeting />
  return <MeetingView />
}

export default function App() {
  return (
    <MeetingProvider>
      <AppShell />
    </MeetingProvider>
  )
}
