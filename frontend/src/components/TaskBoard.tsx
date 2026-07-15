// 会议看板：使用 AntD Table + Tag + Input.Search + Dropdown + Button + Modal
import { useState, useEffect, useCallback, useRef } from 'react'
import type { FormEvent } from 'react'
import { Table, Tag, Input, Button, Modal, Select, Space, Typography, Alert, Card, Divider, Popconfirm, Row, Col } from 'antd'
import { PlusOutlined, DeleteOutlined, HomeOutlined, TagsOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useMeeting } from '../store/MeetingContext.tsx'
import {
  listMeetings, listTags, addMeetingTag, removeMeetingTag,
  batchDeleteMeetings, deleteMeeting, generateRoles,
} from '../lib/api.ts'
import type { MeetingListItem, TagInfo } from '../lib/api.ts'
import type { AgentRole } from '../types/events.ts'
import { MeetingSearchSelect } from './MeetingSearchSelect.tsx'

const { Text, Title } = Typography

const PAGE_SIZE = 10

const STAGE_LABELS: Record<string, string> = {
  clarify: '议题澄清', intra_team: '团队内审议', cross_team: '跨团队对质',
  evidence_check: '证据检验', arbitrate: '仲裁裁决', produce: '产出整合', idle: '待启动',
}

const AVATAR_COLORS = ['#4F46E5', '#0891B2', '#059669', '#D97706', '#DC2626', '#7C3AED', '#2563EB', '#C026D3', '#0D9488', '#EA580C']

function RoleAvatar({ roleId, displayName, size = 32 }: { roleId: string; displayName: string; size?: number }) {
  const colorIdx = roleId.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0) % AVATAR_COLORS.length
  const bg = AVATAR_COLORS[colorIdx]
  const initial = (displayName || roleId).charAt(0).toUpperCase()
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className="task-board-avatar">
      <circle cx="16" cy="16" r="15" fill={bg} opacity="0.12" />
      <circle cx="16" cy="16" r="15" fill="none" stroke={bg} strokeWidth="1.5" opacity="0.8" />
      <text x="16" y="21" textAnchor="middle" fontSize="14" fontWeight="600" fill={bg} fontFamily="system-ui, sans-serif">{initial}</text>
    </svg>
  )
}

const STATUS_COLOR: Record<string, string> = {
  running: 'processing', paused: 'warning', done: 'success', aborted: 'error', idle: 'default',
}
const STATUS_LABEL: Record<string, string> = {
  running: '运行中', paused: '已暂停', done: '已完成', aborted: '已终止', idle: '待启动',
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
  const [createdRoles, setCreatedRoles] = useState<AgentRole[]>([])
  const [rolesLoading, setRolesLoading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { setSearchQuery(searchInput); setPage(0) }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchInput])

  const fetchMeetings = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listMeetings({ q: searchQuery || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE, tags: selectedTags.length ? selectedTags : undefined })
      setMeetings(res.meetings); setTotal(res.total)
    } catch (err) { console.error('加载会议列表失败:', err) }
    finally { setLoading(false) }
  }, [searchQuery, page, selectedTags])

  const fetchTags = useCallback(async () => {
    try { const res = await listTags(); setAllTags(res.tags) } catch (err) { console.error('加载标签列表失败:', err) }
  }, [])

  useEffect(() => { void fetchMeetings() }, [fetchMeetings])
  useEffect(() => {
    void fetchTags()
    const timer = setInterval(() => { void fetchMeetings(); void fetchTags() }, 5000)
    return () => clearInterval(timer)
  }, [fetchTags, fetchMeetings])


  const handleBatchDelete = async () => {
    setBatchBusy(true)
    try { await batchDeleteMeetings([...selectedIds], batchMode); await fetchMeetings(); await fetchTags() }
    catch (err) { console.error('批量删除失败:', err) }
    finally { setSelectedIds(new Set()); setShowBatchConfirm(false); setBatchBusy(false) }
  }

  const handleSingleDelete = async (id: string, mode: 'soft' | 'hard') => {
    setDeletingId(id)
    try { await deleteMeeting(id, mode); await fetchMeetings(); await fetchTags() }
    catch (err) { console.error('删除会议失败:', err) }
    finally { setDeletingId(null) }
  }

  const handleAddTag = async (meetingId: string, tag: string) => {
    const trimmed = tag.trim()
    if (!trimmed) return
    try {
      await addMeetingTag(meetingId, trimmed)
      setMeetings(prev => prev.map(m => m.meeting_id === meetingId ? { ...m, tags: [...(m.tags || []), trimmed] } : m))
      await fetchTags()
    } catch (err) { console.error('添加标签失败:', err) }
    setTagInput('')
  }

  const handleRemoveTag = async (meetingId: string, tag: string) => {
    try {
      await removeMeetingTag(meetingId, tag)
      setMeetings(prev => prev.map(m => m.meeting_id === meetingId ? { ...m, tags: (m.tags || []).filter(t => t !== tag) } : m))
      await fetchTags()
    } catch (err) { console.error('移除标签失败:', err) }
  }

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!createTopic.trim()) { setCreateError('请输入会议议题'); return }
    setCreateBusy(true); setCreateError(null)
    try {
      const res = await createMeeting(createTopic.trim(), createDeliverable, referenceIds.length > 0 ? referenceIds : undefined)
      if (createFile) await uploadDocument(res.meeting_id, createFile)
      selectMeeting(res.meeting_id); void runMeeting(res.meeting_id)
    } catch (err) { setCreateError(err instanceof Error ? err.message : String(err)) }
    finally { setCreateBusy(false) }
  }

  const handleGenerateRoles = useCallback(async () => {
    if (!createTopic.trim() || createTopic.trim().length < 3) return
    setRolesLoading(true)
    try { const res = await generateRoles(createTopic.trim()); setCreatedRoles(res.roles) }
    catch (err) { console.error('角色生成失败:', err) }
    finally { setRolesLoading(false) }
  }, [createTopic])

  const formatTime = (ts?: string) => {
    if (!ts) return '-'
    const d = new Date(ts)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }

  const rowSelection = {
    selectedRowKeys: [...selectedIds],
    onChange: (keys: React.Key[]) => setSelectedIds(new Set(keys as string[])),
  }

  const columns: ColumnsType<MeetingListItem> = [
    {
      title: '状态', dataIndex: 'status', width: 100, align: 'center',
      render: (status: string) => (
        <Tag color={STATUS_COLOR[status] ?? 'default'}>{STATUS_LABEL[status] ?? status}</Tag>
      ),
    },
    {
      title: '议题', dataIndex: 'topic', ellipsis: true, align: 'left',
      render: (topic: string, record: MeetingListItem) => (
        <div className="task-board-topic-cell">
          <Text className="task-board-topic-title">{topic || '(无议题)'}</Text>
          <Text type="secondary" className="task-board-text-sm">{record.meeting_id.slice(-8)}</Text>
        </div>
      ),
    },
    {
      title: '阶段', dataIndex: 'stage', width: 120, align: 'center',
      render: (stage: string) => <Tag>{STAGE_LABELS[stage] || stage}</Tag>,
    },
    {
      title: '标签', dataIndex: 'tags', width: 220, align: 'left',
      render: (tags: string[] | undefined, record: MeetingListItem) => (
        <Space wrap size={[4, 4]}>
          {(tags || []).map(tag => (
            <Tag key={tag} closable onClose={(e: React.MouseEvent) => { e.preventDefault(); handleRemoveTag(record.meeting_id, tag) }}>
              {tag}
            </Tag>
          ))}
          {tagEditId === record.meeting_id ? (
            <Input
              size="small" autoFocus className="task-board-tag-input"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { void handleAddTag(record.meeting_id, tagInput) }
                else if (e.key === 'Escape') { setTagEditId(null); setTagInput('') }
              }}
              onBlur={() => { if (tagInput.trim()) void handleAddTag(record.meeting_id, tagInput); setTagEditId(null); setTagInput('') }}
              placeholder="标签名"
            />
          ) : (
            <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={(e) => { e.stopPropagation(); setTagEditId(record.meeting_id); setTagInput('') }} />
          )}
        </Space>
      ),
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 160, align: 'center',
      render: (ts: string) => formatTime(ts),
    },
    {
      title: '操作', key: 'actions', width: 80, align: 'center',
      render: (_: unknown, record: MeetingListItem) => (
        <Popconfirm title="确认删除？" onConfirm={() => handleSingleDelete(record.meeting_id, 'soft')} okText="确认" cancelText="取消">
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            loading={deletingId === record.meeting_id}
            className="task-board-delete-btn"
          />
        </Popconfirm>
      ),
    },
  ]

  const DELIVERABLE_OPTIONS = [
    { value: 'prd_openapi', label: 'PRD + OpenAPI' }, { value: 'design_doc', label: '设计文档' },
    { value: 'comprehensive', label: '综合文档' }, { value: 'research_report', label: '调研报告' },
    { value: 'business_report', label: '商业报告' }, { value: 'code_analysis', label: '代码分析' },
    { value: 'data_science', label: '数据科学' }, { value: 'tested_system', label: '测试系统' },
    { value: 'deployable_service', label: '可部署服务' },
  ]

  return (
    <div className="task-board task-board-pad">
      {/* 顶部标题栏 */}
      <div className="task-board-toolbar">
        <Space>
          <Title level={3} className="task-board-page-title">会议看板</Title>
          <Text type="secondary">{total} 条记录</Text>
        </Space>
        <Space>
          {onBackToLanding && <Button icon={<HomeOutlined />} onClick={onBackToLanding}>封面</Button>}
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowCreate(v => !v)}>
            {showCreate ? '收起' : '新建会议'}
          </Button>
        </Space>
      </div>

      {/* 内联创建表单 */}
      {showCreate && (
        <Card size="small" className="task-board-mb-16">
          <form onSubmit={handleCreate}>
            <Space direction="vertical" className="task-board-w-full" size={8}>
              <Space.Compact className="task-board-w-full">
                <Input
                  value={createTopic}
                  onChange={(e) => { setCreateTopic(e.target.value); setCreatedRoles([]) }}
                  placeholder="输入会议议题…"
                  disabled={createBusy}
                  className="task-board-grow"
                />
                <Button onClick={handleGenerateRoles} disabled={rolesLoading || createTopic.trim().length < 3}>
                  {rolesLoading ? '生成中…' : createdRoles.length > 0 ? '重新生成角色' : '生成角色'}
                </Button>
              </Space.Compact>
              <MeetingSearchSelect selectedIds={referenceIds} onChange={setReferenceIds} placeholder="引用历史会议…" compact />
              <Space wrap>
                <Select value={createDeliverable} onChange={setCreateDeliverable} options={DELIVERABLE_OPTIONS} disabled={createBusy} className="task-board-deliverable-select" />
                <input type="file" accept=".md,.markdown,text/markdown" onChange={(e) => setCreateFile(e.target.files?.[0] ?? null)} disabled={createBusy} />
                {createFile && <Text type="secondary">{createFile.name}</Text>}
                <Button type="primary" htmlType="submit" loading={createBusy} disabled={!createTopic.trim()}>
                  创建并运行
                </Button>
              </Space>
            </Space>
          </form>

          {createdRoles.length > 0 && (
            <div className="task-board-mt-16">
              <Divider>角色阵容 ({createdRoles.length})</Divider>
              <Row gutter={[8, 8]}>
                {createdRoles.map(role => (
                  <Col key={role.id} xs={24} sm={12} md={8}>
                    <Card size="small" actions={[
                      <Button type="text" size="small" icon={<DeleteOutlined />} onClick={() => setCreatedRoles(prev => prev.filter(r => r.id !== role.id))} />,
                    ]}>
                      <Space>
                        <RoleAvatar roleId={role.id} displayName={role.display_name} />
                        <div>
                          <Text strong>{role.display_name}</Text>
                          <br />
                          <Text type="secondary" className="task-board-text-sm">{role.perspective}</Text>
                        </div>
                      </Space>
                      <div className="task-board-mt-8">
                        <Space wrap size={[4, 4]}>
                          {role.expertise_domains.map(d => <Tag key={d}>{d}</Tag>)}
                          <Tag color={role.risk_appetite === 'aggressive' ? 'red' : role.risk_appetite === 'conservative' ? 'blue' : 'default'}>
                            {role.risk_appetite === 'aggressive' ? '激进' : role.risk_appetite === 'conservative' ? '保守' : '均衡'}
                          </Tag>
                        </Space>
                      </div>
                      {role.background_brief && <Text type="secondary" className="task-board-role-brief">{role.background_brief}</Text>}
                    </Card>
                  </Col>
                ))}
              </Row>
            </div>
          )}

          {createError && <Alert message={createError} type="error" showIcon className="task-board-mt-8" />}
        </Card>
      )}

      {/* 工具栏 */}
      <Space wrap className="task-board-mb-12">
        <Input.Search
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="搜索议题…"
          allowClear
          className="task-board-search-input"
        />
        <Select
          mode="multiple"
          placeholder="标签筛选"
          value={selectedTags}
          onChange={(vals) => { setSelectedTags(vals); setPage(0) }}
          options={allTags.map(t => ({ value: t.tag, label: `${t.tag} (${t.count})` }))}
          className="task-board-tag-filter"
          suffixIcon={<TagsOutlined />}
          allowClear
        />
      </Space>

      {/* 批量操作 */}
      {selectedIds.size > 0 && (
        <Alert
          className="task-board-mb-12"
          message={`已选 ${selectedIds.size} 项`}
          action={
            <Space>
              <Select size="small" value={batchMode} onChange={setBatchMode} className="task-board-batch-mode-select"
                options={[{ value: 'soft', label: '软删除' }, { value: 'hard', label: '永久删除' }]}
              />
              <Button size="small" danger onClick={() => setShowBatchConfirm(true)}>批量删除</Button>
              <Button size="small" onClick={() => setSelectedIds(new Set())}>取消选择</Button>
            </Space>
          }
          type="info" showIcon closable
        />
      )}

      {/* 表格 */}
      <Table<MeetingListItem>
        rowKey="meeting_id"
        columns={columns}
        dataSource={meetings}
        loading={loading}
        rowSelection={rowSelection}
        onRow={(record) => ({ onClick: () => selectMeeting(record.meeting_id), style: { cursor: 'pointer' } })}
        pagination={{
          current: page + 1,
          pageSize: PAGE_SIZE,
          total,
          onChange: (p) => setPage(p - 1),
          showTotal: (t) => `共 ${t} 条`,
          showSizeChanger: false,
        }}
        size="middle"
      />

      {/* 批量删除确认弹窗 */}
      <Modal
        open={showBatchConfirm}
        title="确认批量删除"
        onCancel={() => !batchBusy && setShowBatchConfirm(false)}
        footer={
          <Space>
            <Button onClick={() => setShowBatchConfirm(false)} disabled={batchBusy}>取消</Button>
            <Button danger type="primary" onClick={() => void handleBatchDelete()} loading={batchBusy}>确认删除</Button>
          </Space>
        }
      >
        <div>
          <Text>即将删除 <Text strong>{selectedIds.size}</Text> 个会议</Text>
          <br />
          <Text type="secondary" className="task-board-batch-hint">
            {batchMode === 'soft' ? '软删除：会议标记为已删除，数据保留，可从数据库恢复。' : '永久删除：会议及全部关联数据将被永久删除，不可恢复。'}
          </Text>
        </div>
      </Modal>
    </div>
  )
}
