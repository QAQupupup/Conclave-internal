// 右中：冲突列表 → 选中展开证据与裁决
// conflict → evidence → verdict 三段式
import { useMeeting } from '../store/MeetingContext.tsx'
import type { Decision, EvidenceSet } from '../types/events.ts'

interface EvidencePanelProps {
  selectedConflictId: string | null
  onSelectConflict: (id: string | null) => void
}

const VERDICT_LABEL: Record<string, string> = {
  a: '采纳 A 方',
  b: '采纳 B 方',
  compromise: '折中',
}

const SUPPORTS_LABEL: Record<string, string> = {
  a: '支持 A',
  b: '支持 B',
  neutral: '中立',
  irrelevant: '无关',
}

// 证据来源分类着色
function sourceType(source: string | undefined): 'doc' | 'web' | 'common' | 'unknown' {
  if (!source) return 'unknown'
  if (source.startsWith('doc:')) return 'doc'
  if (source.startsWith('web:')) return 'web'
  if (source.startsWith('common_knowledge')) return 'common'
  return 'unknown'
}

const SOURCE_LABEL: Record<string, string> = {
  doc: '文档证据',
  web: '网络检索',
  common: '通用知识',
  unknown: '未知来源',
}

export function EvidencePanel({ selectedConflictId, onSelectConflict }: EvidencePanelProps) {
  const { store } = useMeeting()
  const m = store.meeting
  const conflicts = m?.conflicts ?? []
  const evidenceSet = m?.evidence_set ?? []
  const decisions = m?.decision_record?.decisions ?? []

  // 取某冲突的证据集合
  const evidenceOf = (cid: string): EvidenceSet | undefined =>
    evidenceSet.find((e) => e.conflict_id === cid)
  // 取某冲突的裁决
  const decisionOf = (cid: string): Decision | undefined =>
    decisions.find((d) => d.conflict_id === cid)

  return (
    <section className="panel evidence-panel">
      <div className="panel-title">冲突与证据</div>
      {conflicts.length === 0 && <div className="empty-hint">暂无冲突（cross_team 阶段产出）</div>}
      <ul className="conflict-list">
        {conflicts.map((c) => {
          const isOpen = selectedConflictId === c.id
          const ev = evidenceOf(c.id)
          const dec = decisionOf(c.id)
          return (
            <li
              key={c.id}
              className={`conflict-item ${isOpen ? 'open' : ''}`}
              onClick={() => onSelectConflict(isOpen ? null : c.id)}
            >
              <div className="conflict-summary">
                <span className="conflict-type">{c.conflict_type ?? c.type ?? 'conflict'}</span>
                <span className="conflict-text">{c.summary}</span>
              </div>
              <div className="conflict-sides">
                <div className="side side-a">A：{c.side_a}</div>
                <div className="side side-b">B：{c.side_b}</div>
              </div>
              {isOpen && (
                <div className="conflict-detail">
                  <div className="detail-section">
                    <span className="field-label">证据</span>
                    {!ev || ev.assessments.length === 0 ? (
                      <div className="muted">暂无证据</div>
                    ) : (
                      <ul className="evidence-list">
                        {ev.assessments.map((a, i) => {
                          const st = sourceType(a.source)
                          return (
                          <li key={i} className="evidence-item">
                            <div className={`evidence-type-tag src-${st}`}>{SOURCE_LABEL[st]}</div>
                            <blockquote className="evidence-quote">{a.quote}</blockquote>
                            <div className="evidence-meta">
                              <span className="evidence-source">{a.source}</span>
                              {a.supports && (
                                <span className={`evidence-supports ${a.supports}`}>
                                  {SUPPORTS_LABEL[a.supports] ?? a.supports}
                                </span>
                              )}
                            </div>
                          </li>
                          )
                        })}
                      </ul>
                    )}
                  </div>
                  <div className="detail-section">
                    <span className="field-label">裁决</span>
                    {dec ? (
                      <div className="verdict">
                        <span className={`verdict-tag ${dec.verdict}`}>
                          {VERDICT_LABEL[dec.verdict] ?? dec.verdict}
                        </span>
                        <span className="verdict-rationale">{dec.rationale}</span>
                      </div>
                    ) : (
                      <div className="muted">待 arbitrate 阶段裁决</div>
                    )}
                  </div>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
