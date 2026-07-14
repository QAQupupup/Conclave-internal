// 历史会议搜索选择器：用于创建会议时引用历史会议，或会议中 @ 唤起注入
// 使用 AntD Select (mode="multiple") + showSearch
import { useState, useEffect, useRef, useCallback } from 'react'
import { Select, Tag, Spin, Typography } from 'antd'
import { listMeetings, getMeetingSummary, type MeetingListItem, type MeetingSummary } from '../lib/api.ts'

const { Text } = Typography

interface Props {
  selectedIds: string[]
  onChange: (ids: string[]) => void
  placeholder?: string
  compact?: boolean
}

export function MeetingSearchSelect({ selectedIds, onChange, placeholder = '搜索历史会议...', compact = false }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<MeetingListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [summaries, setSummaries] = useState<Record<string, MeetingSummary>>({})
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      return
    }
    setLoading(true)
    try {
      const res = await listMeetings({ q: q.trim(), limit: 10 })
      setResults(res.meetings.filter(m => !m.is_running))
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(query), 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, doSearch])

  // 预加载已选会议的摘要
  useEffect(() => {
    for (const id of selectedIds) {
      if (!summaries[id]) {
        getMeetingSummary(id).then(s => {
          setSummaries(prev => ({ ...prev, [id]: s }))
        }).catch(() => { /* ignore */ })
      }
    }
  }, [selectedIds])

  const options = results.map(m => ({
    value: m.meeting_id,
    label: (
      <div>
        <Text>{m.topic}</Text>
        <div>
          <Tag color={m.status === 'completed' ? 'green' : 'blue'} className="meeting-search-select-status-tag">{m.status}</Tag>
          <Text type="secondary" className="meeting-search-select-id-text">{m.meeting_id.slice(-8)}</Text>
        </div>
      </div>
    ),
  }))

  return (
    <Select
      mode="multiple"
      showSearch
      value={selectedIds}
      onChange={onChange}
      onSearch={setQuery}
      placeholder={placeholder}
      options={options}
      filterOption={false}
      loading={loading}
      notFoundContent={loading ? <Spin size="small" /> : query ? '未找到匹配的会议' : null}
      className="meeting-search-select-field"
      size={compact ? 'small' : 'middle'}
      tagRender={({ label: _label, value, closable, onClose }) => {
        const s = summaries[value]
        return (
          <Tag
            closable={closable}
            onClose={onClose}
            className="meeting-search-select-chip-tag"
            title={s?.clarified_topic || s?.topic || value}
          >
            {s?.topic || value.slice(-8)}
          </Tag>
        )
      }}
    />
  )
}
