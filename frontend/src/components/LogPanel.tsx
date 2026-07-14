// 实时日志面板：右侧可折叠抽屉，显示后端推送的结构化日志
import { useEffect, useRef, useState } from 'react'
import { Button, Tooltip, Select, Tag, Switch, Typography } from 'antd'
import {
  LeftOutlined,
  RightOutlined,
  DownloadOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { LogEntry } from '../types/events.ts'

const { Text } = Typography

/** 日志级别颜色映射 */
const LEVEL_COLORS: Record<string, { bg: string; fg: string; tag: string; label: string }> = {
  ERROR:   { bg: '#fff1f0', fg: '#cf1322', tag: 'red',    label: 'ERROR' },
  WARNING: { bg: '#fffbe6', fg: '#d48806', tag: 'orange', label: 'WARN'  },
  INFO:    { bg: 'transparent', fg: 'var(--text, #333)', tag: 'blue',  label: 'INFO' },
  DEBUG:   { bg: 'transparent', fg: '#8c8c8c', tag: 'default', label: 'DEBUG' },
}

/** 日志级别排序值 */
const LEVEL_RANK: Record<string, number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3 }

/** 格式化时间戳（只显示时分秒毫秒） */
function formatTs(ts: string): string {
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) {
      // 如果是本地时间格式
      return ts.slice(11, 23)
    }
    const h = String(d.getHours()).padStart(2, '0')
    const m = String(d.getMinutes()).padStart(2, '0')
    const s = String(d.getSeconds()).padStart(2, '0')
    const ms = String(d.getMilliseconds()).padStart(3, '0')
    return `${h}:${m}:${s}.${ms}`
  } catch {
    return ts.slice(11, 19)
  }
}

/** 单条日志行 */
function LogLine({ entry }: { entry: LogEntry }) {
  const style = LEVEL_COLORS[entry.level] || LEVEL_COLORS.INFO
  return (
    <div
      className="log-line"
      style={{
        padding: '2px 8px',
        fontSize: 12,
        fontFamily: '"JetBrains Mono", "Fira Code", "Consolas", monospace',
        lineHeight: '18px',
        background: style.bg,
        borderLeft: `3px solid ${style.fg}`,
        display: 'flex',
        gap: 8,
        alignItems: 'flex-start',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}
    >
      <span className="log-panel-time">
        {formatTs(entry.timestamp)}
      </span>
      <Tag
        color={style.tag}
        className="log-panel-type-tag"
      >
        {style.label}
      </Tag>
      {entry.stage && (
        <Tag
          color="purple"
          className="log-panel-stage-tag"
        >
          {entry.stage}
        </Tag>
      )}
      <span className="log-panel-speaker">
        {entry.logger?.replace('app.orchestrator.', '').replace('app.agents.', '').replace('orchestrator.nodes.', '')}
      </span>
      <span style={{ color: style.fg, flex: 1 }}>{entry.message}</span>
    </div>
  )
}

export function LogPanel() {
  const { store } = useMeeting()
  const logs = store.meeting?.logs ?? []
  const [open, setOpen] = useState(false)
  const [minLevel, setMinLevel] = useState<string>('INFO')
  const [autoScroll, setAutoScroll] = useState(true)
  const [paused, setPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (autoScroll && !paused && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [logs, autoScroll, paused])

  // 过滤日志
  const filtered = logs.filter(
    (l) => LEVEL_RANK[l.level] >= LEVEL_RANK[minLevel],
  )

  // 统计各级别数量
  const counts = {
    ERROR: logs.filter((l) => l.level === 'ERROR').length,
    WARNING: logs.filter((l) => l.level === 'WARNING').length,
    INFO: logs.filter((l) => l.level === 'INFO').length,
  }

  // 导出日志
  const handleExport = () => {
    const text = logs
      .map(
        (l) =>
          `[${formatTs(l.timestamp)}] [${l.level}] [${l.logger}] ${l.message}${l.stage ? ` (${l.stage})` : ''}`,
      )
      .join('\n')
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `meeting-logs-${new Date().toISOString().slice(0, 19).replace(/:/g, '')}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  // 收起状态：只显示一个窄条+箭头
  if (!open) {
    return (
      <div className="log-panel-toggle log-panel-toggle-bar">
        <Tooltip title="打开实时日志面板" placement="left">
          <Button
            type="primary"
            icon={<LeftOutlined />}
            onClick={() => setOpen(true)}
            className="log-panel-toggle-btn"
          />
        </Tooltip>
        {counts.ERROR > 0 && (
          <Tag
            color="red"
            className="log-panel-toggle-badge"
          >
            {counts.ERROR}
          </Tag>
        )}
      </div>
    )
  }

  // 展开状态：完整日志面板
  return (
    <div className="log-panel log-panel-container">
      {/* 头部工具栏 */}
      <div className="log-panel-head">
        <Tooltip title="收起日志面板" placement="bottom">
          <Button
            type="text"
            size="small"
            icon={<RightOutlined />}
            onClick={() => setOpen(false)}
          />
        </Tooltip>
        <Text strong className="log-panel-title">实时日志</Text>

        {/* 错误/警告计数 */}
        <div className="log-panel-counts">
          {counts.ERROR > 0 && <Tag color="red" className="log-panel-count-tag">{counts.ERROR} 错误</Tag>}
          {counts.WARNING > 0 && <Tag color="orange" className="log-panel-count-tag">{counts.WARNING} 警告</Tag>}
        </div>

        <div className="log-panel-spacer" />

        {/* 级别过滤 */}
        <Select
          size="small"
          value={minLevel}
          onChange={setMinLevel}
          className="log-panel-filter-select"
          options={[
            { value: 'DEBUG', label: 'DEBUG+' },
            { value: 'INFO', label: 'INFO+' },
            { value: 'WARNING', label: 'WARN+' },
            { value: 'ERROR', label: 'ERROR' },
          ]}
        />

        <Tooltip title={paused ? '继续接收' : '暂停接收'}>
          <Button
            type="text"
            size="small"
            icon={paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
            onClick={() => setPaused((p) => !p)}
          />
        </Tooltip>

        <Tooltip title="自动滚动">
          <Switch
            size="small"
            checked={autoScroll}
            onChange={setAutoScroll}
            checkedChildren="自动"
            unCheckedChildren="手动"
          />
        </Tooltip>

        <Tooltip title="导出日志">
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            onClick={handleExport}
          />
        </Tooltip>
      </div>

      {/* 日志列表 */}
      <div
        ref={scrollRef}
        className="log-panel-scroll"
      >
        {filtered.length === 0 ? (
          <div className="log-panel-empty">
            {logs.length === 0
              ? '等待日志输入...会议启动后将实时显示后端日志'
              : `当前过滤级别下无日志（共 ${logs.length} 条被过滤）`}
          </div>
        ) : (
          filtered.map((entry) => <LogLine key={entry.id} entry={entry} />)
        )}
        <div ref={bottomRef} className="log-panel-bottom-anchor" />
      </div>

      {/* 底部状态栏 */}
      <div className="log-panel-footer">
        <span>
          共 {logs.length} 条{paused && ' (已暂停)'}
        </span>
        <span>
          {filtered.length !== logs.length && `显示 ${filtered.length} 条 | `}
          INFO+
        </span>
      </div>
    </div>
  )
}
