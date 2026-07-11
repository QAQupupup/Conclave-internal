// 六步流程指示器：使用 AntD Steps 组件渲染六阶段进度
// 当前步骤高亮、已完成步骤标记 ✓
import { Steps } from 'antd'
import { useMeeting } from '../store/MeetingContext.tsx'
import { STAGE_LABELS, STAGE_ORDER } from '../types/events.ts'

export function StageIndicator() {
  const { store } = useMeeting()
  const currentStage = store.meeting?.stage ?? 'clarify'
  const currentIndex = STAGE_ORDER.indexOf(currentStage)

  return (
    <div className="stage-indicator">
      <Steps
        size="small"
        current={currentIndex}
        items={STAGE_ORDER.map((stage) => ({
          title: STAGE_LABELS[stage],
        }))}
        style={{ maxWidth: 680 }}
      />
    </div>
  )
}
