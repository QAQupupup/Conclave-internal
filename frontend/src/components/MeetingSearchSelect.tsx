// 历史会议搜索选择器：用于创建会议时引用历史会议，或会议中 @ 唤起注入
// 搜索框输入关键词 → 调 listMeetings API → 下拉展示结果 → 点击选择/取消
import { useState, useEffect, useRef, useCallback } from 'react'
import { listMeetings, getMeetingSummary, type MeetingListItem, type MeetingSummary } from '../lib/api.ts'

interface Props {
  /** 已选中的会议 ID 列表 */
  selectedIds: string[]
  /** 选择变更回调 */
  onChange: (ids: string[]) => void
  /** 占位符文本 */
  placeholder?: string
  /** 是否紧凑模式（用于聊天输入框中的 @ 唤起） */
  compact?: boolean
}

export function MeetingSearchSelect({ selectedIds, onChange, placeholder = '搜索历史会议...', compact = false }: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState<MeetingListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [summaries, setSummaries] = useState<Record<string, MeetingSummary>>({})
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // 搜索（300ms 防抖）
  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      setOpen(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await listMeetings({ q: q.trim(), limit: 10 })
      // 过滤掉当前正在运行的会议
      setResults(res.meetings.filter(m => !m.is_running))
      setOpen(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(query), 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, doSearch])

  // 点击外部关闭下拉
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const toggleSelect = async (id: string) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter(sid => sid !== id))
    } else {
      onChange([...selectedIds, id])
      // 预加载摘要
      if (!summaries[id]) {
        try {
          const s = await getMeetingSummary(id)
          setSummaries(prev => ({ ...prev, [id]: s }))
        } catch { /* 忽略 */ }
      }
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className={`meeting-search-select${compact ? ' compact' : ''}`}>
      <div className="mss-input-wrap">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (results.length > 0) setOpen(true) }}
          placeholder={placeholder}
          className="mss-input"
        />
        {loading && <span className="mss-spinner" />}
      </div>

      {selectedIds.length > 0 && (
        <div className="mss-selected">
          {selectedIds.map(id => {
            const s = summaries[id]
            return (
              <span key={id} className="mss-chip" title={s?.clarified_topic || s?.topic || id}>
                {s?.topic || id.slice(-8)}
                <button onClick={() => toggleSelect(id)} className="mss-chip-remove">&times;</button>
              </span>
            )
          })}
        </div>
      )}

      {open && (
        <div className="mss-dropdown">
          {error && <div className="mss-error">{error}</div>}
          {results.length === 0 && !loading && !error && (
            <div className="mss-empty">未找到匹配的会议</div>
          )}
          {results.map(m => {
            const isSelected = selectedIds.includes(m.meeting_id)
            const s = summaries[m.meeting_id]
            return (
              <div
                key={m.meeting_id}
                className={`mss-item${isSelected ? ' selected' : ''}`}
                onClick={() => toggleSelect(m.meeting_id)}
              >
                <span className="mss-checkbox">{isSelected ? '✓' : ''}</span>
                <div className="mss-item-body">
                  <div className="mss-item-topic">{m.topic}</div>
                  <div className="mss-item-meta">
                    <span className={`mss-status mss-${m.status}`}>{m.status}</span>
                    {s && <span className="mss-artifact-preview">{s.artifact_summary.slice(0, 60)}</span>}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}