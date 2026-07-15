// 实时日志面板内容：作为 Drawer 内容渲染，显示后端推送的结构化日志
import { useEffect, useRef, useState } from 'react'
import { Button, Tooltip, Select, Tag, Switch, Typography } from 'antd'
import {
  DownloadOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import type { LogEntry } from '../types/events.ts'

const { Text } = Typography

/** 日志级别颜色映射（使用 CSS 变量，遵循设计系统） */
const LEVEL_COLORS: Record<string, { bg: string; fg: string; tag: string; label: string }> = {
  ERROR:   { bg: 'var(--err-bg)',    fg: 'var(--err-fg)',  tag: 'red',    label: 'ERROR' },
  WARNING: { bg: 'var(--warn-bg)',   fg: 'var(--warn-fg)', tag: 'orange', label: 'WARN'  },
  INFO:    { bg: 'transparent',      fg: 'var(--text)',   tag: 'blue',   label: 'INFO'  },
  DEBUG:   { bg: 'transparent',      fg: 'var(--text-muted)', tag: 'default', label: 'DEBUG' },
}

/** 日志级别排序值 */
const LEVEL_RANK: Record<string, number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3 }

/** 格式化时间戳（只显示时分秒毫秒） */
function formatTs(ts: string): string {
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) {
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
        padding: '2px 12px',
        fontSize: 12,
        fontFamily: 'var(--font-mono)',
        lineHeight: '20px',
        background: style.bg,
        borderLeft: `3px solid ${style.fg}`,
        display: 'flex',
        gap: 8,
        alignItems: 'flex-start',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}
    >
      <span className="log-panel-time" style={{ color: 'var(--text-muted)', flexShrink: 0 }}>
        {formatTs(entry.timestamp)}
      </span>
      <Tag
        color={style.tag}
        className="log-panel-type-tag"
        style={{ marginRight: 0, flexShrink: 0, fontSize: 11, lineHeight: '18px' }}
      >
        {style.label}
      </Tag>
      {entry.stage && (
        <Tag
          color="purple"
          className="log-panel-stage-tag"
          style={{ marginRight: 0, flexShrink: 0, fontSize: 11, lineHeight: '18px' }}
        >
          {entry.stage}
        </Tag>
      )}
      <span
        className="log-panel-speaker"
        style={{
          color: 'var(--role-architect, #8b5cf6)',
          flexShrink: 0,
          fontSize: 11,
          maxWidth: 120,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {entry.logger?.replace('app.orchestrator.', '').replace('app.agents.', '').replace('orchestrator.nodes.', '')}
      </span>
      <span style={{ color: style.fg, flex: 1, minWidth: 0 }}>{entry.message}</span>
    </div>
  )
}

interface LogPanelContentProps {
  /** 内嵌模式（在 Drawer 内）时不显示头部边框 */
  embedded?: boolean
}

export function LogPanelContent({ embedded = false }: LogPanelContentProps) {
  const { store } = useMeeting()
  const logs = store.meeting?.logs ?? []
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

  // 当前过滤级别标签
  const levelLabels: Record<string, string> = {
    DEBUG: 'DEBUG+',
    INFO: 'INFO+',
    WARNING: 'WARN+',
    ERROR: 'ERROR',
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

  return (
    <div className="log-panel-content" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* 头部工具栏 */}
      <div
        className="log-panel-head"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: embedded ? '0 0 12px' : '12px 16px',
          borderBottom: embedded ? '1px solid var(--border-soft)' : 'none',
          flexShrink: 0,
        }}
      >
        <Text strong style={{ fontSize: 14, marginRight: 'auto' }}>实时日志</Text>

        {/* 错误/警告计数 */}
        <div style={{ display: 'flex', gap: 4 }}>
          {counts.ERROR > 0 && <Tag color="red" style={{ margin: 0 }}>{counts.ERROR} 错误</Tag>}
          {counts.WARNING > 0 && <Tag color="orange" style={{ margin: 0 }}>{counts.WARNING} 警告</Tag>}
        </div>

        {/* 级别过滤 */}
        <Select
          size="small"
          value={minLevel}
          onChange={setMinLevel}
          style={{ width: 90 }}
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
        style={{
          flex: 1,
          overflowY: 'auto',
          minHeight: 0,
          background: 'var(--bg)',
        }}
      >
        {filtered.length === 0 ? (
          <div
            className="log-panel-empty"
            style={{
              padding: '40px 20px',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: 13,
            }}
          >
            {logs.length === 0
              ? '等待日志输入...会议启动后将实时显示后端日志'
              : `当前过滤级别下无日志（共 ${logs.length} 条被过滤）`}
          </div>
        ) : (
          filtered.map((entry) => <LogLine key={entry.id} entry={entry} />)
        )}
        <div ref={bottomRef} className="log-panel-bottom-anchor" style={{ height: 1 }} />
      </div>

      {/* 底部状态栏 */}
      <div
        className="log-panel-footer"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 12px',
          borderTop: '1px solid var(--border-soft)',
          fontSize: 12,
          color: 'var(--text-muted)',
          flexShrink: 0,
        }}
      >
        <span>共 {logs.length} 条{paused && ' (已暂停)'}</span>
        <span>
          {filtered.length !== logs.length && `显示 ${filtered.length} 条 | `}
          {levelLabels[minLevel]}
        </span>
      </div>
    </div>
  )
}

/** 错误计数 Hook：供工具栏按钮显示 Badge */
export function useLogErrorCount(): number {
  const { store } = useMeeting()
  const logs = store.meeting?.logs ?? []
  return logs.filter((l) => l.level === 'ERROR').length
}
