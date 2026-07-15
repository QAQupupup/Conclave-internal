// 会议功能面板切换工具栏
// 放在 meeting-top-bar 右侧，统一管理议题/证据/产出/报告/Token/模型/介入/日志面板的开关
// 采用 Linear/Vercel 风格的精致字母徽章按钮：圆角小方块，极简字母标识，无阴影
import { Tooltip, Badge } from 'antd'
import {
  SearchOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import { useLogErrorCount } from './LogPanel.tsx'
import './FloatingBadges.css'

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

/** 字母徽章组件：白底黑字/主题色白字的极简方块 */
function LetterBadge({ letter, active }: { letter: string; active: boolean }) {
  return (
    <span className={`fb-letter ${active ? 'fb-letter-active' : ''}`}>
      {letter}
    </span>
  )
}

export function FloatingBadges({
  panels,
  onToggle,
  pendingBorrow,
  interventionCount,
}: FloatingBadgesProps) {
  const logErrorCount = useLogErrorCount()
  const interventionBadge = (pendingBorrow ? 1 : 0) + interventionCount

  // 设计说明：
  // - Token(T): 用户明确偏好的白底黑字T风格
  // - 报告(R)、产出(O)、证据(E)、模型(M)、日志(L): 首字母标识，极简一致
  // - 议题聚焦: 搜索图标更直观（功能本质是搜索/聚焦）
  // - 介入申请: 问号图标 + Badge 红点，符合"请求/询问"语义
  const buttons: Array<{
    key: keyof PanelToggleState
    content: React.ReactNode
    label: string
    badge?: number
  }> = [
    { key: 'topic', content: <SearchOutlined />, label: '议题聚焦' },
    { key: 'evidence', content: <LetterBadge letter="E" active={panels.evidence} />, label: '证据面板' },
    { key: 'output', content: <LetterBadge letter="O" active={panels.output} />, label: '产出物' },
    { key: 'report', content: <LetterBadge letter="R" active={panels.report} />, label: '最终报告' },
    { key: 'token', content: <LetterBadge letter="T" active={panels.token} />, label: 'Token 监控' },
    { key: 'model', content: <LetterBadge letter="M" active={panels.model} />, label: '模型调度' },
    { key: 'intervention', content: <QuestionCircleOutlined />, label: '介入申请', badge: interventionBadge },
    { key: 'logs', content: <LetterBadge letter="L" active={panels.logs} />, label: '实时日志', badge: logErrorCount },
  ]

  return (
    <div className="panel-toolbar fb-container">
      {buttons.map(({ key, content, label, badge }) => {
        const active = panels[key]
        const hasBadge = badge !== undefined && badge > 0
        return (
          <Tooltip key={key} title={label} placement="bottom">
            <button
              className={`fb-btn ${active ? 'fb-btn-active' : ''}`}
              onClick={() => onToggle(key)}
              aria-label={label}
            >
              {hasBadge ? (
                <Badge count={badge} size="small" offset={[-3, 3]}>
                  <span className={`fb-inner ${active ? 'fb-inner-active' : ''}`}>
                    {content}
                  </span>
                </Badge>
              ) : (
                <span className={`fb-inner ${active ? 'fb-inner-active' : ''}`}>
                  {content}
                </span>
              )}
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}
