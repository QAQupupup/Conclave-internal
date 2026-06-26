// 右上：议题 + 澄清结论 + key_questions + 团队组成
import { useMeeting } from '../store/MeetingContext.tsx'
import { ROLE_LABELS } from '../types/events.ts'

export function TopicPanel() {
  const { store } = useMeeting()
  const m = store.meeting
  if (!m) return null

  const questions = m.key_questions ?? []
  const team = m.team_config ?? []

  return (
    <section className="panel topic-panel">
      <div className="panel-title">议题与澄清</div>
      <div className="topic-field">
        <span className="field-label">原始议题</span>
        <div className="field-value">{m.topic}</div>
      </div>
      <div className="topic-field">
        <span className="field-label">澄清结论</span>
        <div className="field-value">{m.clarified_topic || '（待 clarify 阶段产出）'}</div>
      </div>
      <div className="topic-field">
        <span className="field-label">关键问题（{questions.length}）</span>
        <ul className="key-questions">
          {questions.length === 0 && <li className="muted">暂无</li>}
          {questions.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ul>
      </div>
      <div className="topic-field">
        <span className="field-label">团队组成（{team.length}）</span>
        <div className="team-list">
          {team.length === 0 && <span className="muted">待确认</span>}
          {team.map((member, i) => (
            <span key={i} className="team-chip">
              {ROLE_LABELS[member.role] ?? member.role} · {member.stance || '—'}
            </span>
          ))}
        </div>
      </div>
    </section>
  )
}
