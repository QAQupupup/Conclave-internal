// 任务看板：搜索 / 标签筛选 / 分页 / 批量操作 / 内联创建会议
import { useState, useEffect, useCallback, useRef } from 'react'
import type { FormEvent } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import {
  listMeetings,
  listTags,
  addMeetingTag,
  removeMeetingTag,
  batchDeleteMeetings,
  deleteMeeting,
} from '../lib/api.ts'
import type { MeetingListItem, TagInfo } from '../lib/api.ts'

const PAGE_SIZE = 10

// 阶段中文映射
const STAGE_LABELS: Record<string, string> = {
  clarify: '议题澄清',
  intra_team: '团队内审议',
  cross_team: '跨团队对质',
  evidence_check: '证据检验',
  arbitrate: '仲裁裁决',
  produce: '产出整合',
  idle: '待启动',
}

// 状态颜色 class
const STATUS_CLASS: Record<string, string> = {
  running: 'badge-running',
  paused: 'badge-paused',
  done: 'badge-done',
  aborted: 'badge-aborted',
  idle: 'badge-idle',
}

const STATUS_LABEL: Record<string, string> = {
  running: '运行中',
  paused: '已暂停',
  done: '已完成',
  aborted: '已终止',
  idle: '待启动',
}

interface TaskBoardProps {
  onBackToLanding?: () => void
}

export function TaskBoard({ onBackToLanding }: TaskBoardProps) {
  const { selectMeeting, createMeeting, runMeeting, uploadDocument } = useMeeting()

  // 列表数据
  const [meetings, setMeetings] = useState<MeetingListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  // 搜索与过滤
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [page, setPage] = useState(0)

  // 标签数据
  const [allTags, setAllTags] = useState<TagInfo[]>([])

  // 批量选择
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchMode, setBatchMode] = useState<'soft' | 'hard'>('soft')
  const [showBatchConfirm, setShowBatchConfirm] = useState(false)
  const [batchBusy, setBatchBusy] = useState(false)

  // 内联创建
  const [showCreate, setShowCreate] = useState(false)
  const [createTopic, setCreateTopic] = useState('')
  const [createDeliverable, setCreateDeliverable] = useState('prd_openapi')
  const [createFile, setCreateFile] = useState<File | null>(null)
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // 每行标签编辑
  const [tagEditId, setTagEditId] = useState<string | null>(null)
  const [tagInput, setTagInput] = useState('')

  // 搜索防抖
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchQuery(searchInput)
      setPage(0)
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [searchInput])

  // 拉取列表
  const fetchMeetings = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listMeetings({
        q: searchQuery || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        tags: selectedTags.length ? selectedTags : undefined,
      })
      setMeetings(res.meetings)
      setTotal(res.total)
    } catch {
      // 静默
    } finally {
      setLoading(false)
    }
  }, [searchQuery, page, selectedTags])

  // 拉取标签
  const fetchTags = useCallback(async () => {
    try {
      const res = await listTags()
      setAllTags(res.tags)
    } catch {
      // 静默
    }
  }, [])

  useEffect(() => {
    void fetchMeetings()
  }, [fetchMeetings])

  // 初次加载 + 定时刷新
  useEffect(() => {
    void fetchTags()
    const timer = setInterval(() => {
      void fetchMeetings()
      void fetchTags()
    }, 5000)
    return () => clearInterval(timer)
  }, [fetchTags, fetchMeetings])

  // 切换标签选中
  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    )
    setPage(0)
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedIds.size === meetings.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(meetings.map((m) => m.meeting_id)))
    }
  }

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // 批量删除
  const handleBatchDelete = async () => {
    setBatchBusy(true)
    try {
      const res = await batchDeleteMeetings([...selectedIds], batchMode)
      // 刷新列表
      await fetchMeetings()
      await fetchTags()
      setSelectedIds(new Set())
      setShowBatchConfirm(false)
      // 如果有失败的，提示
      if (res.failed.length > 0) {
        // 简单提示
        console.warn(`批量删除部分失败: ${res.failed.join(', ')}`)
      }
    } catch {
      // 静默
    } finally {
      setBatchBusy(false)
    }
  }

  // 单个删除
  const handleSingleDelete = async (id: string, mode: 'soft' | 'hard') => {
    try {
      await deleteMeeting(id, mode)
      await fetchMeetings()
      await fetchTags()
    } catch {
      // 静默
    }
  }

  // 添加标签到会议
  const handleAddTag = async (meetingId: string, tag: string) => {
    const trimmed = tag.trim()
    if (!trimmed) return
    try {
      await addMeetingTag(meetingId, trimmed)
      // 更新本地数据
      setMeetings((prev) =>
        prev.map((m) =>
          m.meeting_id === meetingId
            ? { ...m, tags: [...(m.tags || []), trimmed] }
            : m,
        ),
      )
      await fetchTags()
    } catch {
      // 静默
    }
    setTagInput('')
  }

  // 移除标签
  const handleRemoveTag = async (meetingId: string, tag: string) => {
    try {
      await removeMeetingTag(meetingId, tag)
      setMeetings((prev) =>
        prev.map((m) =>
          m.meeting_id === meetingId
            ? { ...m, tags: (m.tags || []).filter((t) => t !== tag) }
            : m,
        ),
      )
      await fetchTags()
    } catch {
      // 静默
    }
  }

  // 创建会议
  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!createTopic.trim()) {
      setCreateError('请输入会议议题')
      return
    }
    setCreateBusy(true)
    setCreateError(null)
    try {
      const res = await createMeeting(createTopic.trim(), createDeliverable)
      if (createFile) {
        await uploadDocument(res.meeting_id, createFile)
      }
      // 创建后直接进入会议
      selectMeeting(res.meeting_id)
      // 异步触发运行
      void runMeeting(res.meeting_id)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreateBusy(false)
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const allSelected = meetings.length > 0 && selectedIds.size === meetings.length

  return (
    <div className="task-board">
      {/* 顶部工具栏 */}
      <div className="board-header">
        <div className="board-header-left">
          <h2 className="board-title">会议看板</h2>
          <span className="board-count">{total} 条记录</span>
        </div>
        <div className="board-header-right">
          {onBackToLanding && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onBackToLanding}
              title="返回封面"
            >
              封面
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setShowCreate((v) => !v)}
          >
            {showCreate ? '收起' : '新建会议'}
          </button>
        </div>
      </div>

      {/* 内联创建表单 */}
      {showCreate && (
        <div className="board-create-panel">
          <form onSubmit={handleCreate} className="board-create-form">
            <input
              className="board-search-input"
              type="text"
              value={createTopic}
              onChange={(e) => setCreateTopic(e.target.value)}
              placeholder="输入会议议题…"
              disabled={createBusy}
            />
            <select
              className="board-select"
              value={createDeliverable}
              onChange={(e) => setCreateDeliverable(e.target.value)}
              disabled={createBusy}
            >
              <option value="prd_openapi">PRD + OpenAPI</option>
              <option value="design_doc">设计文档</option>
              <option value="comprehensive">综合文档</option>
              <option value="research_report">调研报告</option>
              <option value="business_report">商业报告</option>
              <option value="code_analysis">代码分析</option>
              <option value="tested_system">测试系统</option>
              <option value="deployable_service">可部署服务</option>
            </select>
            <label className="board-file-label">
              <input
                type="file"
                accept=".md,.markdown,text/markdown"
                onChange={(e) => setCreateFile(e.target.files?.[0] ?? null)}
                disabled={createBusy}
              />
              {createFile && <span className="board-file-name">{createFile.name}</span>}
            </label>
            <button type="submit" className="btn btn-primary btn-sm" disabled={createBusy || !createTopic.trim()}>
              {createBusy ? '创建中…' : '创建并运行'}
            </button>
          </form>
          {createError && <div className="board-error">{createError}</div>}
        </div>
      )}

      {/* 搜索栏 + 批量操作 */}
      <div className="board-toolbar">
        <div className="board-search-wrap">
          <input
            className="board-search-input"
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索议题…"
          />
          {searchInput && (
            <button
              type="button"
              className="board-search-clear"
              onClick={() => setSearchInput('')}
            >
              ×
            </button>
          )}
        </div>
        {selectedIds.size > 0 && (
          <div className="board-batch-bar">
            <span className="board-selected-count">已选 {selectedIds.size} 项</span>
            <select
              className="board-select board-select-sm"
              value={batchMode}
              onChange={(e) => setBatchMode(e.target.value as 'soft' | 'hard')}
            >
              <option value="soft">软删除</option>
              <option value="hard">永久删除</option>
            </select>
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => setShowBatchConfirm(true)}
            >
              批量删除
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setSelectedIds(new Set())}
            >
              取消选择
            </button>
          </div>
        )}
      </div>

      {/* 主体：标签侧栏 + 会议列表 */}
      <div className="board-body">
        {/* 标签侧栏 */}
        <aside className="board-tag-sidebar">
          <div className="board-tag-header">标签筛选</div>
          <button
            className={`board-tag-item${selectedTags.length === 0 ? ' active' : ''}`}
            onClick={() => setSelectedTags([])}
          >
            <span className="board-tag-name">全部</span>
            <span className="board-tag-count">{total}</span>
          </button>
          {allTags.map((t) => (
            <button
              key={t.tag}
              className={`board-tag-item${selectedTags.includes(t.tag) ? ' active' : ''}`}
              onClick={() => toggleTag(t.tag)}
            >
              <span className="board-tag-name">{t.tag}</span>
              <span className="board-tag-count">{t.count}</span>
            </button>
          ))}
          {allTags.length === 0 && (
            <div className="board-tag-empty">暂无标签</div>
          )}
        </aside>

        {/* 会议列表 */}
        <div className="board-list-area">
          {/* 全选 */}
          {meetings.length > 0 && (
            <div className="board-list-header">
              <label className="board-checkbox-label">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                />
                <span>全选</span>
              </label>
              <span className="board-list-info">
                第 {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} 条 / 共 {total} 条
              </span>
            </div>
          )}

          {loading && meetings.length === 0 ? (
            <div className="board-loading">加载中…</div>
          ) : meetings.length === 0 ? (
            <div className="board-empty">
              {searchQuery || selectedTags.length
                ? '没有匹配的会议记录'
                : '暂无会议，点击"新建会议"创建'}
            </div>
          ) : (
            <div className="board-meeting-list">
              {meetings.map((m) => (
                <div
                  key={m.meeting_id}
                  className={`board-meeting-card${selectedIds.has(m.meeting_id) ? ' selected' : ''}`}
                >
                  <label className="board-card-checkbox">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(m.meeting_id)}
                      onChange={() => toggleSelect(m.meeting_id)}
                    />
                  </label>
                  <div
                    className="board-card-main"
                    onClick={() => selectMeeting(m.meeting_id)}
                  >
                    <div className="board-card-top">
                      <span
                        className={`board-status-badge ${STATUS_CLASS[m.status] || 'badge-idle'}`}
                      >
                        {STATUS_LABEL[m.status] || m.status}
                      </span>
                      {m.is_running && <span className="board-running-dot" title="正在运行" />}
                      <span className="board-stage-tag">
                        {STAGE_LABELS[m.stage] || m.stage}
                      </span>
                    </div>
                    <div className="board-card-topic">{m.topic}</div>
                    <div className="board-card-meta">
                      <span className="board-card-id">{m.meeting_id}</span>
                      {m.created_at && (
                        <span className="board-card-time">
                          {new Date(m.created_at).toLocaleString('zh-CN')}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* 标签区域 */}
                  <div className="board-card-tags">
                    {(m.tags || []).map((tag) => (
                      <span key={tag} className="board-chip">
                        {tag}
                        <button
                          type="button"
                          className="board-chip-remove"
                          onClick={() => handleRemoveTag(m.meeting_id, tag)}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                    {tagEditId === m.meeting_id ? (
                      <input
                        className="board-tag-input"
                        type="text"
                        value={tagInput}
                        autoFocus
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            void handleAddTag(m.meeting_id, tagInput)
                          } else if (e.key === 'Escape') {
                            setTagEditId(null)
                            setTagInput('')
                          }
                        }}
                        onBlur={() => {
                          if (tagInput.trim()) void handleAddTag(m.meeting_id, tagInput)
                          setTagEditId(null)
                          setTagInput('')
                        }}
                        placeholder="标签名"
                      />
                    ) : (
                      <button
                        type="button"
                        className="board-chip-add"
                        onClick={() => {
                          setTagEditId(m.meeting_id)
                          setTagInput('')
                        }}
                      >
                        + 标签
                      </button>
                    )}
                  </div>

                  {/* 单个删除 */}
                  <div className="board-card-actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm board-card-delete"
                      onClick={() => handleSingleDelete(m.meeting_id, 'soft')}
                      title="软删除（可恢复）"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 分页 */}
          {totalPages > 1 && (
            <div className="board-pagination">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPage(0)}
                disabled={page === 0}
              >
                首页
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
              >
                ‹
              </button>
              <span className="board-page-info">
                {page + 1} / {totalPages}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
              >
                ›
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPage(totalPages - 1)}
                disabled={page >= totalPages - 1}
              >
                末页
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 批量删除确认 */}
      {showBatchConfirm && (
        <div className="modal-overlay" onClick={() => !batchBusy && setShowBatchConfirm(false)}>
          <div className="modal-card abort-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">
              确认批量删除 {selectedIds.size} 个会议？
            </div>
            <p className="abort-confirm-text">
              {batchMode === 'soft'
                ? '软删除：会议标记为已删除，数据保留，可从数据库恢复。'
                : '永久删除：会议及全部关联数据将被永久删除，不可恢复。'}
            </p>
            <div className="abort-confirm-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setShowBatchConfirm(false)}
                disabled={batchBusy}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => void handleBatchDelete()}
                disabled={batchBusy}
              >
                {batchBusy ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
