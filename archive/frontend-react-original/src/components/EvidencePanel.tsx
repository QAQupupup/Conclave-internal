// 右中：冲突列表 → 选中展开证据与裁决
// conflict → evidence → verdict 三段式
// 使用 AntD Card + Collapse + Tag + Typography + Empty
import { Card, Collapse, Tag, Typography, Empty } from 'antd'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { Decision, EvidenceSet } from '../types/events.ts'
import {
  EVIDENCE_SOURCE_LABEL as SOURCE_LABEL,
  classifyEvidenceSource as sourceType,
} from '../constants.ts'
import { EvidenceBadge, parseEvidenceRef } from './EvidenceBadge.tsx'

const { Text } = Typography

interface EvidencePanelProps {
  selectedConflictId: string | null
  onSelectConflict: (id: string | null) => void
}

const VERDICT_COLOR: Record<string, string> = {
  a: 'blue',
  b: 'purple',
  compromise: 'gold',
}

const VERDICT_LABEL: Record<string, string> = {
  a: '采纳 A 方',
  b: '采纳 B 方',
  compromise: '折中',
}

const SUPPORTS_COLOR: Record<string, string> = {
  a: 'blue',
  b: 'purple',
  neutral: 'default',
  irrelevant: 'default',
}

const SUPPORTS_LABEL: Record<string, string> = {
  a: '支持 A',
  b: '支持 B',
  neutral: '中立',
  irrelevant: '无关',
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

  const activeKey = selectedConflictId ? [selectedConflictId] : []

  return (
    <section className="panel evidence-panel">
      <div className="panel-title">冲突与证据</div>
      {conflicts.length === 0 ? (
        <Empty description="暂无冲突（cross_team 阶段产出）" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Collapse
          activeKey={activeKey}
          onChange={(keys) => {
            const key = keys[0]
            onSelectConflict(key === selectedConflictId ? null : (key ?? null))
          }}
          items={conflicts.map((c) => {
            const ev = evidenceOf(c.id)
            const dec = decisionOf(c.id)
            return {
              key: c.id,
              label: (
                <div>
                  <Tag className="evidence-panel-type-tag">{c.conflict_type ?? c.type ?? 'conflict'}</Tag>
                  <Text>{c.summary}</Text>
                </div>
              ),
              children: (
                <div>
                  <Card size="small" title="双方立场" className="evidence-panel-card">
                    <div className="evidence-panel-side">
                      <Tag color="blue">A 方</Tag>
                      <Text>{c.side_a}</Text>
                    </div>
                    <div>
                      <Tag color="purple">B 方</Tag>
                      <Text>{c.side_b}</Text>
                    </div>
                  </Card>

                  <Card size="small" title="证据" className="evidence-panel-card">
                    {!ev || ev.assessments.length === 0 ? (
                      <Text type="secondary">暂无证据</Text>
                    ) : (
                      <div className="evidence-panel-list">
                        {ev.assessments.map((a, i) => {
                          const st = sourceType(a.source)
                          return (
                            <div key={i} className="evidence-panel-item">
                              <Tag className="evidence-panel-item-tag">{SOURCE_LABEL[st]}</Tag>
                              <blockquote className="evidence-panel-quote">
                                <Text>{a.quote}</Text>
                              </blockquote>
                              <div className="evidence-panel-item-footer">
                                <EvidenceBadge
                                  item={{
                                    ...parseEvidenceRef(a.source ?? ''),
                                    quote: undefined,
                                  }}
                                />
                                {a.supports && (
                                  <Tag color={SUPPORTS_COLOR[a.supports] ?? 'default'}>
                                    {SUPPORTS_LABEL[a.supports] ?? a.supports}
                                  </Tag>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </Card>

                  <Card size="small" title="裁决">
                    {dec ? (
                      <div>
                        <Tag color={VERDICT_COLOR[dec.verdict] ?? 'default'} className="evidence-panel-verdict-tag">
                          {VERDICT_LABEL[dec.verdict] ?? dec.verdict}
                        </Tag>
                        <div>
                          <Text>{dec.rationale}</Text>
                        </div>
                      </div>
                    ) : (
                      <Text type="secondary">待 arbitrate 阶段裁决</Text>
                    )}
                  </Card>
                </div>
              ),
            }
          })}
        />
      )}
    </section>
  )
}
