// 六步流程指示器：六个圆形节点 + 连接线，当前步骤高亮、已完成步骤浅色填充
// 替代原 Header 中的阶段进度条，置于顶部 meeting-top-bar 内
import { useMeeting } from '../store/MeetingContext.tsx'
import { STAGE_LABELS, STAGE_ORDER } from '../types/events.ts'

export function StageIndicator() {
  const { store } = useMeeting()
  // 未选会议时默认处于第一阶段（全部节点保持 pending）
  const currentStage = store.meeting?.stage ?? 'clarify'

  const currentIndex = STAGE_ORDER.indexOf(currentStage)

  return (
    <div className="stage-indicator">
      {STAGE_ORDER.map((stage, i) => {
        const isCurrent = stage === currentStage
        const isDone = i < currentIndex
        const isLast = i === STAGE_ORDER.length - 1

        return (
          <div key={stage} className="stage-node-wrap">
            <div className="stage-node-container">
              <div
                className={`stage-node ${isCurrent ? 'current' : isDone ? 'done' : 'pending'}`}
              >
                {isDone ? '✓' : i + 1}
              </div>
              <span className={`stage-label ${isCurrent ? 'current' : ''}`}>
                {STAGE_LABELS[stage]}
              </span>
            </div>
            {!isLast && <div className={`stage-connector ${isDone ? 'done' : ''}`} />}
          </div>
        )
      })}
    </div>
  )
}
