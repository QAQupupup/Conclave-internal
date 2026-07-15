// 会议功能面板切换工具栏
// 放在 meeting-top-bar 右侧，统一管理议题/证据/产出/报告/Token/模型/介入/日志面板的开关
// 使用 AntD Tooltip + Button，统一尺寸、基线对齐
import { Tooltip, Badge, Button } from 'antd'
import {
  FileSearchOutlined,
  ProfileOutlined,
  FileDoneOutlined,
  LineChartOutlined,
  ThunderboltOutlined,
  RobotOutlined,
  QuestionCircleOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useLogErrorCount } from './LogPanel.tsx'

export interface PanelToggleState {
  topic: boolean
  evidence: boolean
  output: boolean
  report: boolean
  token: boolean
  model: boolean
  intervention: boolean
  logs: boolean
}

interface FloatingBadgesProps {
  panels: PanelToggleState
  onToggle: (key: keyof PanelToggleState) => void
  pendingBorrow: boolean
  interventionCount: number
}

export function FloatingBadges({
  panels,
  onToggle,
  pendingBorrow,
  interventionCount,
}: FloatingBadgesProps) {
  const logErrorCount = useLogErrorCount()
  const interventionBadge = (pendingBorrow ? 1 : 0) + interventionCount

  const buttons: Array<{
    key: keyof PanelToggleState
    icon: React.ReactNode
    label: string
    badge?: number
  }> = [
    { key: 'topic', icon: <FileSearchOutlined />, label: '议题聚焦' },
    { key: 'evidence', icon: <ProfileOutlined />, label: '证据面板' },
    { key: 'output', icon: <FileDoneOutlined />, label: '产出物' },
    { key: 'report', icon: <LineChartOutlined />, label: '最终报告' },
    { key: 'token', icon: <ThunderboltOutlined />, label: 'Token 监控' },
    { key: 'model', icon: <RobotOutlined />, label: '模型调度' },
    { key: 'intervention', icon: <QuestionCircleOutlined />, label: '介入申请', badge: interventionBadge },
    { key: 'logs', icon: <FileTextOutlined />, label: '实时日志', badge: logErrorCount },
  ]

  return (
    <div
      className="panel-toolbar"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 2,
      }}
    >
      {buttons.map(({ key, icon, label, badge }) => {
        const active = panels[key]
        const iconEl = badge && badge > 0
          ? <Badge count={badge} size="small" offset={[-2, 2]}>{icon}</Badge>
          : icon
        return (
          <Tooltip key={key} title={label} placement="bottom">
            <Button
              type={active ? 'primary' : 'text'}
              size="small"
              icon={iconEl}
              onClick={() => onToggle(key)}
            />
          </Tooltip>
        )
      })}
    </div>
  )
}
