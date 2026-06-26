// 右下：PRD 预览 + OpenAPI 代码块 + 借调入口
import { useMeeting } from '../store/MeetingContext.tsx'

interface ArtifactPanelProps {
  onOpenBorrow: () => void
}

export function ArtifactPanel({ onOpenBorrow }: ArtifactPanelProps) {
  const { store } = useMeeting()
  const artifact = store.meeting?.artifact

  return (
    <section className="panel artifact-panel">
      <div className="panel-title">
        产物预览
        <button type="button" className="btn btn-ghost borrow-btn" onClick={onOpenBorrow}>
          借调专家
        </button>
      </div>
      {!artifact ? (
        <div className="empty-hint">暂无产物（produce 阶段产出 PRD + OpenAPI）</div>
      ) : (
        <div className="artifact-body">
          <div className="prd-block">
            <div className="prd-title">{artifact.prd?.title || '未命名 PRD'}</div>
            <div className="prd-row">
              <span className="field-label">目标</span>
              <span>{artifact.prd?.goal || '—'}</span>
            </div>
            <div className="prd-row">
              <span className="field-label">范围</span>
              <span>{artifact.prd?.scope || '—'}</span>
            </div>
            <ListField label="假设" items={artifact.prd?.assumptions} />
            <ListField label="约束" items={artifact.prd?.constraints} />
            <ListField label="API 端点" items={artifact.prd?.api_endpoints} />
            <ListField label="遗留问题" items={artifact.prd?.open_questions} />
          </div>
          <div className="openapi-block">
            <div className="field-label">OpenAPI 片段</div>
            <pre className="code-block">{artifact.openapi || '# 暂无 OpenAPI'}</pre>
          </div>
        </div>
      )}
    </section>
  )
}

/** 字符串列表字段渲染 */
function ListField({ label, items }: { label: string; items?: string[] }) {
  const arr = items ?? []
  return (
    <div className="prd-row">
      <span className="field-label">{label}（{arr.length}）</span>
      <ul className="prd-list">
        {arr.length === 0 && <li className="muted">无</li>}
        {arr.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  )
}
