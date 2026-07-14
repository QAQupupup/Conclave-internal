// 右上：议题 + 澄清结论 + key_questions + 团队组成
// 使用 AntD Card + Descriptions + Tag + Typography
import { Descriptions, Tag, Typography, Space } from 'antd'
import { QuestionCircleOutlined, TeamOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import { ROLE_LABELS } from '../types/events.ts'

const { Text } = Typography

export function TopicPanel() {
  const { store } = useMeeting()
  const m = store.meeting
  if (!m) return null

  const questions = m.key_questions ?? []
  const team = m.team_config ?? []

  return (
    <section className="panel topic-panel">
      <div className="panel-title">议题与澄清</div>

      <Descriptions column={1} size="small" bordered className="topic-panel-descriptions">
        <Descriptions.Item label="原始议题">{m.topic}</Descriptions.Item>
        <Descriptions.Item label="澄清结论">
          {m.clarified_topic || <Text type="secondary">（待 clarify 阶段产出）</Text>}
        </Descriptions.Item>
      </Descriptions>

      <div className="topic-panel-section">
        <Space size={4} className="topic-panel-subhead">
          <QuestionCircleOutlined />
          <Text strong>关键问题（{questions.length}）</Text>
        </Space>
        {questions.length === 0 ? (
          <Text type="secondary">暂无</Text>
        ) : (
          <ul className="topic-panel-questions">
            {questions.map((q, i) => (
              <li key={i} className="topic-panel-question-item">{q}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <Space size={4} className="topic-panel-subhead">
          <TeamOutlined />
          <Text strong>团队组成（{team.length}）</Text>
        </Space>
        {team.length === 0 ? (
          <Text type="secondary">待确认</Text>
        ) : (
          <Space wrap size={[4, 4]}>
            {team.map((member, i) => (
              <Tag key={i} color="blue">
                {ROLE_LABELS[member.role] ?? member.role} · {member.stance || '—'}
              </Tag>
            ))}
          </Space>
        )}
      </div>
    </section>
  )
}
