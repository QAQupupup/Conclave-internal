// 会议看板：中后台表格列表页 — 搜索 / 标签筛选 / 分页 / 批量操作 / 内联创建
// 参考 Ant Design Table 模式，适配 Linear/Notion 扁平极简风格
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
  generateRoles,
} from '../lib/api.ts'
import type { MeetingListItem, TagInfo } from '../lib/api.ts'
import type { AgentRole } from '../types/events.ts'
import { MeetingSearchSelect } from './MeetingSearchSelect.tsx'

const PAGE_SIZE = 10

const STAGE_LABELS: Record<string, string> = {
  clarify: '议题澄清',
  intra_team: '团队内审议',
  cross_team: '跨团队对质',
  evidence_check: '证据检验',
  arbitrate: '仲裁裁决',
  produce: '产出整合',
  idle: '待启动',
}

// 角色头像颜色池
const AVATAR_COLORS = [
  '#4F46E5', '#0891B2', '#059669', '#D97706', '#DC2626',
  '#7C3AED', '#2563EB', '#C026D3', '#0D9488', '#EA580C',
]

/** 根据角色 ID 生成极简 SVG 头像：圆形 + 首字母 */
function RoleAvatar({ roleId, displayName, size = 32 }: { roleId: string; displayName: string; size?: number }) {
  const colorIdx = roleId.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0) % AVATAR_COLORS.length
  const bg = AVATAR_COLORS[colorIdx]
  const initial = (displayName || roleId).charAt(0).toUpperCase()
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" style={{ flexShrink: 0 }}>
      <circle cx="16" cy="16" r="15" fill={bg} opacity="0.12" />
      <circle cx="16" cy="16" r="15" fill="none" stroke={bg} strokeWidth="1.5" opacity="0.8" />
      <text x="16" y="21" textAnchor="middle" fontSize="14" fontWeight="600" fill={bg} fontFamily="system-ui, sans-serif">
        {initial}
      </text>
    </svg>
  )
}

const STATUS_LABEL: Record<string, string> = {
  running: '运行中',
  paused: '已暂停',
  done: '已完成',
  aborted: '已终止',
  idle: '待启动',
}

const STATUS_DOT: Record<string, string> = {
  running: 'dot-running',
  paused: 'dot-paused',
  done: 'dot-done',
  aborted: 'dot-aborted',
  idle: 'dot-idle',
}

interface TaskBoardProps {
  onBackToLanding?: () => void
}

export function TaskBoard({ onBackToLanding }: TaskBoardProps) {
  const { selectMeeting, createMeeting, runMeeting, uploadDocument } = useMeeting()

  const [meetings, setMeetings] = useState<MeetingListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [page, setPage] = useState(0)

  const [allTags, setAllTags] = useState<TagInfo[]>([])
  const [tagDropdownOpen, setTagDropdownOpen] = useState(false)
  const tagDropdownRef = useRef<HTMLDivElement>(null)

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchMode, setBatchMode] = useState<'soft' | 'hard'>('soft')
  const [showBatchConfirm, setShowBatchConfirm] = useState(false)
  const [batchBusy, setBatchBusy] = useState(false)

  const [showCreate, setShowCreate] = useState(false)
  const [createTopic, setCreateTopic] = useState('')
  const [createDeliverable, setCreateDeliverable] = useState('prd_openapi')
  const [createFile, setCreateFile] = useState<File | null>(null)
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [referenceIds, setReferenceIds] = useState<string[]>([])

  const [tagEditId, setTagEditId] = useState<string | null>(null)
  const [tagInput, setTagInput] = useState('')

  // 角色卡片
  const [createdRoles, setCreatedRoles] = useState<AgentRole[]>([])
  const [rolesLoading, setRolesLoading] = useState(false)
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null)
  const [editRoleForm, setEditRoleForm] = useState<Partial<AgentRole>>({})

  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

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

  // 点击外部关闭标签下拉
  useEffect(() => {
    if (!tagDropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (tagDropdownRef.current && !tagDropdownRef.current.contains(e.target as Node)) {
        setTagDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [tagDropdownOpen])

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
    } catch (err) {
      console.error('加载会议列表失败:', err)
    } finally {
      setLoading(false)
    }
  }, [searchQuery, page, selectedTags])

  const fetchTags = useCallback(async () => {
    try {
      const res = await listTags()
      setAllTags(res.tags)
    } catch (err) {
      console.error('加载标签列表失败:', err)
    }
  }, [])

  useEffect(() => {
    void fetchMeetings()
  }, [fetchMeetings])

  useEffect(() => {
    void fetchTags()
    const timer = setInterval(() => {
      void fetchMeetings()
      void fetchTags()
    }, 5000)
    return () => clearInterval(timer)
  }, [fetchTags, fetchMeetings])

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    )
    setPage(0)
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === meetings.length && meetings.length > 0) {
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

  const handleBatchDelete = async () => {
    setBatchBusy(true)
    try {
      const res = await batchDeleteMeetings([...selectedIds], batchMode)
      if (res.failed.length > 0) {
        console.warn(`批量删除部分失败: ${res.failed.join(', ')}`)
      }
      await fetchMeetings()
      await fetchTags()
    } catch (err) {
      console.error('批量删除失败:', err)
    } finally {
      setSelectedIds(new Set())
      setShowBatchConfirm(false)
      setBatchBusy(false)
    }
  }

  const handleSingleDelete = async (id: string, mode: 'soft' | 'hard') => {
    setDeletingId(id)
    setDeleteError(null)
    try {
      await deleteMeeting(id, mode)
      await fetchMeetings()
      await fetchTags()
    } catch (err) {
      console.error('删除会议失败:', err)
      setDeleteError('删除失败，请重试')
    } finally {
      setDeletingId(null)
    }
  }

  const handleAddTag = async (meetingId: string, tag: string) => {
    const trimmed = tag.trim()
    if (!trimmed) return
    const prevMeetings = meetings
    try {
      await addMeetingTag(meetingId, trimmed)
      setMeetings((prev) =>
        prev.map((m) =>
          m.meeting_id === meetingId
            ? { ...m, tags: [...(m.tags || []), trimmed] }
            : m,
        ),
      )
      await fetchTags()
    } catch (err) {
      console.error('添加标签失败:', err)
      setMeetings(prevMeetings)
    }
    setTagInput('')
  }

  const handleRemoveTag = async (meetingId: string, tag: string) => {
    const prevMeetings = meetings
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
    } catch (err) {
      console.error('移除标签失败:', err)
      setMeetings(prevMeetings)
    }
  }

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!createTopic.trim()) {
      setCreateError('请输入会议议题')
      return
    }
    setCreateBusy(true)
    setCreateError(null)
    try {
      const res = await createMeeting(createTopic.trim(), createDeliverable, referenceIds.length > 0 ? referenceIds : undefined)
      if (createFile) {
        await uploadDocument(res.meeting_id, createFile)
      }
      selectMeeting(res.meeting_id)
      void runMeeting(res.meeting_id)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreateBusy(false)
    }
  }

  // 生成角色：输入议题后自动触发
  const handleGenerateRoles = useCallback(async () => {
    if (!createTopic.trim() || createTopic.trim().length < 3) return
    setRolesLoading(true)
    try {
      const res = await generateRoles(createTopic.trim())
      setCreatedRoles(res.roles)
    } catch (err) {
      console.error('角色生成失败:', err)
    } finally {
      setRolesLoading(false)
    }
  }, [createTopic])

  // 编辑角色
  const handleEditRole = (role: AgentRole) => {
    setEditingRoleId(role.id)
    setEditRoleForm({ ...role })
  }
  const handleSaveRoleEdit = () => {
    if (!editingRoleId) return
    setCreatedRoles((prev) =>
      prev.map((r) => (r.id === editingRoleId ? { ...r, ...editRoleForm } as AgentRole : r)),
    )
    setEditingRoleId(null)
  }
  const handleRemoveRole = (roleId: string) => {
    setCreatedRoles((prev) => prev.filter((r) => r.id !== roleId))
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const allSelected = meetings.length > 0 && selectedIds.size === meetings.length
  const hasSelection = selectedIds.size > 0

  const formatTime = (ts?: string) => {
    if (!ts) return '-'
    const d = new Date(ts)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }

  return (
    <div className="task-board">
      {/* 顶部标题栏 */}
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
            <div className="board-create-row">
              <input
                className="board-search-input"
                type="text"
                value={createTopic}
                onChange={(e) => { setCreateTopic(e.target.value); setCreatedRoles([]) }}
                placeholder="输入会议议题…"
                disabled={createBusy}
              />
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={handleGenerateRoles}
                disabled={rolesLoading || createTopic.trim().length < 3}
              >
                {rolesLoading ? '生成中…' : createdRoles.length > 0 ? '重新生成角色' : '生成角色'}
              </button>
            </div>
            <div className="board-create-row">
              <MeetingSearchSelect
                selectedIds={referenceIds}
                onChange={setReferenceIds}
                placeholder="引用历史会议…"
                compact
              />
            </div>
            <div className="board-create-row">
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
                <option value="data_science">数据科学</option>
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
            </div>
          </form>

          {/* 角色卡片网格 */}
          {createdRoles.length > 0 && (
            <div className="role-cards-section">
              <div className="role-cards-header">
                <span className="role-cards-title">角色阵容</span>
                <span className="role-cards-count">{createdRoles.length} 个角色</span>
              </div>
              <div className="role-cards-grid">
                {createdRoles.map((role) => (
                  <div key={role.id} className={`role-card${editingRoleId === role.id ? ' editing' : ''}`}>
                    {editingRoleId === role.id ? (
                      <div className="role-card-edit">
                        <div className="role-card-edit-fields">
                          <input
                            className="role-edit-input"
                            value={editRoleForm.display_name || ''}
                            onChange={(e) => setEditRoleForm((f) => ({ ...f, display_name: e.target.value }))}
                            placeholder="角色名称"
                          />
                          <textarea
                            className="role-edit-textarea"
                            value={editRoleForm.perspective || ''}
                            onChange={(e) => setEditRoleForm((f) => ({ ...f, perspective: e.target.value }))}
                            placeholder="核心视角"
                            rows={2}
                          />
                          <textarea
                            className="role-edit-textarea"
                            value={editRoleForm.background_brief || ''}
                            onChange={(e) => setEditRoleForm((f) => ({ ...f, background_brief: e.target.value }))}
                            placeholder="一句话背景"
                            rows={2}
                          />
                          <input
                            className="role-edit-input"
                            value={(editRoleForm.expertise_domains || []).join(', ')}
                            onChange={(e) => setEditRoleForm((f) => ({
                              ...f,
                              expertise_domains: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                            }))}
                            placeholder="专业领域，逗号分隔"
                          />
                          <select
                            className="board-select"
                            value={editRoleForm.risk_appetite || 'balanced'}
                            onChange={(e) => setEditRoleForm((f) => ({ ...f, risk_appetite: e.target.value as AgentRole['risk_appetite'] }))}
                          >
                            <option value="conservative">保守</option>
                            <option value="balanced">均衡</option>
                            <option value="aggressive">激进</option>
                          </select>
                        </div>
                        <div className="role-card-edit-actions">
                          <button type="button" className="btn btn-primary btn-sm" onClick={handleSaveRoleEdit}>保存</button>
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditingRoleId(null)}>取消</button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="role-card-header">
                          <RoleAvatar roleId={role.id} displayName={role.display_name} />
                          <div className="role-card-meta">
                            <span className="role-card-name">{role.display_name}</span>
                            <span className="role-card-perspective">{role.perspective}</span>
                          </div>
                          <div className="role-card-actions">
                            <button
                              type="button"
                              className="btn btn-ghost btn-xs"
                              onClick={() => handleEditRole(role)}
                              title="编辑"
                            >
                              &#9998;
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-xs"
                              onClick={() => handleRemoveRole(role.id)}
                              title="移除"
                            >
                              &times;
                            </button>
                          </div>
                        </div>
                        <div className="role-card-tags">
                          {role.expertise_domains.map((d) => (
                            <span key={d} className="role-card-tag">{d}</span>
                          ))}
                          <span className="role-card-tag role-card-risk">{role.risk_appetite === 'aggressive' ? '激进' : role.risk_appetite === 'conservative' ? '保守' : '均衡'}</span>
                        </div>
                        {role.background_brief && (
                          <div className="role-card-brief">{role.background_brief}</div>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {createError && <div className="board-error">{createError}</div>}
        </div>
      )}

      {/* 工具栏：搜索 + 标签筛选 */}
      <div className="board-toolbar">
        <div className="board-search-wrap">
          <svg className="board-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
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

        {/* 标签多选下拉 */}
        <div className="board-tag-dropdown" ref={tagDropdownRef}>
          <button
            type="button"
            className={`board-tag-dropdown-btn${tagDropdownOpen ? ' open' : ''}${selectedTags.length > 0 ? ' has-value' : ''}`}
            onClick={() => setTagDropdownOpen((v) => !v)}
          >
            <span className="board-tag-dropdown-icon">🏷</span>
            <span className="board-tag-dropdown-label">
              {selectedTags.length > 0 ? `标签 (${selectedTags.length})` : '标签筛选'}
            </span>
            <span className="board-tag-dropdown-arrow">{tagDropdownOpen ? '▴' : '▾'}</span>
          </button>
          {tagDropdownOpen && (
            <div className="board-tag-dropdown-menu">
              {allTags.length === 0 ? (
                <div className="board-tag-dropdown-empty">暂无标签</div>
              ) : (
                allTags.map((t) => (
                  <label
                    key={t.tag}
                    className={`board-tag-dropdown-item${selectedTags.includes(t.tag) ? ' checked' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedTags.includes(t.tag)}
                      onChange={() => toggleTag(t.tag)}
                    />
                    <span className="board-tag-dropdown-name">{t.tag}</span>
                    <span className="board-tag-dropdown-count">{t.count}</span>
                  </label>
                ))
              )}
              {selectedTags.length > 0 && (
                <button
                  type="button"
                  className="board-tag-dropdown-clear"
                  onClick={() => { setSelectedTags([]); setPage(0) }}
                >
                  清除筛选
                </button>
              )}
            </div>
          )}
        </div>

        {/* 已选标签 chips */}
        {selectedTags.length > 0 && (
          <div className="board-active-tags">
            {selectedTags.map((tag) => (
              <span key={tag} className="board-active-tag-chip">
                {tag}
                <button
                  type="button"
                  className="board-active-tag-remove"
                  onClick={() => toggleTag(tag)}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 选择提示条 */}
      {hasSelection && (
        <div className="board-alert">
          <span className="board-alert-text">已选 {selectedIds.size} 项</span>
          <div className="board-alert-actions">
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
        </div>
      )}

      {/* 删除错误提示 */}
      {deleteError && (
        <div className="board-error" style={{ marginBottom: 8 }}>
          {deleteError}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setDeleteError(null)}
            style={{ marginLeft: 8 }}
          >
            ×
          </button>
        </div>
      )}

      {/* 表格 */}
      <div className="board-table-wrap">
        <table className="board-table">
          <thead>
            <tr>
              <th className="board-th board-th-check">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                />
              </th>
              <th className="board-th board-th-status">状态</th>
              <th className="board-th board-th-topic">议题</th>
              <th className="board-th board-th-stage">阶段</th>
              <th className="board-th board-th-tags">标签</th>
              <th className="board-th board-th-time">创建时间</th>
              <th className="board-th board-th-actions">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && meetings.length === 0 ? (
              <tr>
                <td colSpan={7} className="board-td-empty">加载中…</td>
              </tr>
            ) : meetings.length === 0 ? (
              <tr>
                <td colSpan={7} className="board-td-empty">
                  {searchQuery || selectedTags.length
                    ? '没有匹配的会议记录'
                    : '暂无会议，点击"新建会议"创建'}
                </td>
              </tr>
            ) : (
              meetings.map((m) => {
                const isSelected = selectedIds.has(m.meeting_id)
                const isDeleting = deletingId === m.meeting_id
                return (
                  <tr
                    key={m.meeting_id}
                    className={`board-row${isSelected ? ' selected' : ''}`}
                    onClick={() => selectMeeting(m.meeting_id)}
                  >
                    <td className="board-td board-td-check" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(m.meeting_id)}
                      />
                    </td>
                    <td className="board-td board-td-status">
                      <span className={`board-status-dot ${STATUS_DOT[m.status] || 'dot-idle'}`} />
                      <span className="board-status-text">{STATUS_LABEL[m.status] || m.status}</span>
                    </td>
                    <td className="board-td board-td-topic">
                      <span className="board-topic-text">{m.topic || '(无议题)'}</span>
                      <span className="board-topic-id">{m.meeting_id.slice(-8)}</span>
                    </td>
                    <td className="board-td board-td-stage">
                      <span className="board-stage-tag">{STAGE_LABELS[m.stage] || m.stage}</span>
                    </td>
                    <td className="board-td board-td-tags" onClick={(e) => e.stopPropagation()}>
                      <div className="board-tags-inline">
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
                            +
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="board-td board-td-time">
                      {formatTime(m.created_at)}
                    </td>
                    <td className="board-td board-td-actions" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => handleSingleDelete(m.meeting_id, 'soft')}
                        disabled={isDeleting}
                      >
                        {isDeleting ? '…' : '删除'}
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      <div className="board-pagination">
        <span className="board-pagination-total">共 {total} 条</span>
        <div className="board-pagination-nav">
          <button
            type="button"
            className="board-page-btn"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ‹
          </button>
          {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
            // 显示页码逻辑：尽量显示当前页附近的页码
            let pageNum: number
            if (totalPages <= 7) {
              pageNum = i
            } else if (page < 3) {
              pageNum = i
            } else if (page > totalPages - 4) {
              pageNum = totalPages - 7 + i
            } else {
              pageNum = page - 3 + i
            }
            return (
              <button
                key={pageNum}
                type="button"
                className={`board-page-btn${pageNum === page ? ' active' : ''}`}
                onClick={() => setPage(pageNum)}
              >
                {pageNum + 1}
              </button>
            )
          })}
          <button
            type="button"
            className="board-page-btn"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
          >
            ›
          </button>
        </div>
      </div>

      {/* 批量删除确认弹窗 */}
      {showBatchConfirm && (
        <div className="modal-overlay" onClick={() => !batchBusy && setShowBatchConfirm(false)}>
          <div className="modal batch-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>确认批量删除</h3>
            </div>
            <div className="batch-confirm-body">
              <div className="batch-confirm-count">
                即将删除 <strong>{selectedIds.size}</strong> 个会议
              </div>
              <p className="batch-confirm-text">
                {batchMode === 'soft'
                  ? '软删除：会议标记为已删除，数据保留，可从数据库恢复。'
                  : '永久删除：会议及全部关联数据将被永久删除，不可恢复。'}
              </p>
            </div>
            <div className="batch-confirm-actions">
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