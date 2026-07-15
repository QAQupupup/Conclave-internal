// 六步流程指示器：使用 AntD Steps 组件渲染六阶段进度
// 当前步骤高亮、已完成步骤标记 ✓，旁边展示 flow_plan / debate_depth 标签
import { Steps, Tag, Tooltip } from 'antd'
import {
  ThunderboltOutlined,
  ScheduleOutlined,
  FireOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  ApiOutlined,
} from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import { STAGE_LABELS, STAGE_ORDER } from '../types/events.ts'

/** flow_plan 中文标签 + 颜色 + 图标 */
const FLOW_PLAN_META: Record<string, { label: string; color: string; icon: React.ReactNode; tip: string }> = {
  fast: {
    label: 'Fast',
    color: 'blue',
    icon: <ThunderboltOutlined />,
    tip: '快速通道：简单问题直接回答，跳过大部分辩论阶段',
  },
  simple: {
    label: 'Simple',
    color: 'cyan',
    icon: <ApiOutlined />,
    tip: '简化流程：跳过跨组辩论、证据核查、仲裁阶段',
  },
  plan: {
    label: 'Plan',
    color: 'purple',
    icon: <ScheduleOutlined />,
    tip: '计划模式：先由 Planner 生成执行计划，再按计划推进',
  },
  standard: {
    label: 'Standard',
    color: 'geekblue',
    icon: <CheckCircleOutlined />,
    tip: '标准流程：六阶段完整辩论',
  },
  full: {
    label: 'Deep',
    color: 'gold',
    icon: <FireOutlined />,
    tip: '深度研讨：完整六阶段 + 深度辩论',
  },
}

/** debate_depth 标签 */
const DEPTH_META: Record<string, { label: string; color: string; tip: string }> = {
  light: { label: '轻量', color: 'default', tip: '轻量辩论：快速收敛' },
  standard: { label: '标准', color: 'default', tip: '标准辩论深度' },
  deep: { label: '深度', color: 'orange', tip: '深度辩论：多轮充分讨论' },
}

export function StageIndicator() {
  const { store } = useMeeting()
  const meeting = store.meeting
  const currentStage = meeting?.stage ?? 'clarify'
  const currentIndex = STAGE_ORDER.indexOf(currentStage)
  const flowPlan = meeting?.flow_plan ?? 'standard'
  const debateDepth = meeting?.debate_depth ?? 'standard'

  const flowMeta = FLOW_PLAN_META[flowPlan] ?? FLOW_PLAN_META.standard
  const depthMeta = DEPTH_META[debateDepth] ?? DEPTH_META.standard

  return (
    <div className="stage-indicator" style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
      <Steps
        size="small"
        current={currentIndex}
        items={STAGE_ORDER.map((stage) => ({
          title: STAGE_LABELS[stage],
        }))}
        className="stage-indicator-steps"
        style={{ flex: 1, minWidth: 0 }}
      />
      {/* Flow plan 标签 */}
      <Tooltip title={flowMeta.tip} placement="bottom">
        <Tag
          color={flowMeta.color}
          icon={flowMeta.icon}
          style={{ margin: 0, flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 4, lineHeight: '20px' }}
        >
          {flowMeta.label}
        </Tag>
      </Tooltip>
      {/* Debate depth 标签（非 standard 时才展示，避免冗余） */}
      {debateDepth !== 'standard' && (
        <Tooltip title={depthMeta.tip} placement="bottom">
          <Tag
            color={depthMeta.color}
            icon={<ExperimentOutlined />}
            style={{ margin: 0, flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 4, lineHeight: '20px' }}
          >
            {depthMeta.label}
          </Tag>
        </Tooltip>
      )}
    </div>
  )
}
