// 初始页面：输入议题 + 上传 md + 创建 + 运行
// 流程：输入议题 →（可选）选择模型/Key → 上传 md → 创建 → 点 Run 触发 → 自动连 WS → 实时看发言流
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMeeting } from '../store/MeetingContext.tsx'
import { MeetingSearchSelect } from './MeetingSearchSelect.tsx'
import { ModelSelector, type ModelSelection } from './ModelSelector.tsx'
import { setMeetingModel as apiSetMeetingModel } from '../lib/api.ts'
import { getDefaultSelection, setApiKey as saveApiKey, setDefaultSelection, loadPreferences } from '../lib/llmPreferences.ts'

export function CreateMeeting() {
  const { createMeeting, uploadDocument, selectMeeting, runMeeting } = useMeeting()
  const [topic, setTopic] = useState('')
  const [deliverableType, setDeliverableType] = useState('prd_openapi')
  const [file, setFile] = useState<File | null>(null)
  const [referenceIds, setReferenceIds] = useState<string[]>([])
  // 初始值从本地偏好读取
  const [modelSel, setModelSel] = useState<ModelSelection>(() => getDefaultSelection())
  const [modelExpanded, setModelExpanded] = useState(false)
  const [createdId, setCreatedId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  // 获取默认选择用于对比是否自定义
  const defaultSel = getDefaultSelection()
  // 判断是否自定义了模型配置（与本地默认偏好不同）
  const isCustomModel = modelSel.provider_id !== defaultSel.provider_id
    || modelSel.model !== defaultSel.model
    || (modelSel.api_key !== '' && modelSel.api_key !== defaultSel.api_key)
    || modelSel.base_url !== defaultSel.base_url

  // 创建会议
  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!topic.trim()) {
      setError('请输入会议议题')
      return
    }
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      const res = await createMeeting(topic.trim(), deliverableType, referenceIds.length > 0 ? referenceIds : undefined)
      setCreatedId(res.meeting_id)
      // 如果用户自定义了模型/Key，在会议创建后立即应用
      if (isCustomModel) {
        try {
          await apiSetMeetingModel(res.meeting_id, {
            provider_id: modelSel.provider_id,
            model: modelSel.model,
            api_key: modelSel.api_key || undefined,
            base_url: modelSel.base_url || undefined,
          })
          // 保存 API Key 到本地偏好
          if (modelSel.api_key) {
            saveApiKey(modelSel.provider_id, modelSel.api_key)
          }
          // 如果开启了自动保存，将当前模型设为默认
          const prefs = loadPreferences()
          if (prefs.auto_save_model) {
            setDefaultSelection({
              provider_id: modelSel.provider_id,
              model: modelSel.model,
              base_url: modelSel.base_url,
            })
          }
          setInfo(`会议已创建，已设置模型：${modelSel.model}`)
        } catch (me) {
          setInfo(`会议已创建，但模型设置失败：${me instanceof Error ? me.message : String(me)}`)
        }
      }
      // 可选：上传 md 文档
      if (file) {
        const up = await uploadDocument(res.meeting_id, file)
        setInfo(prev => `${prev ? prev + '；' : ''}已上传 ${up.doc_id}，切块 ${up.chunks} 段`)
      } else if (!isCustomModel) {
        setInfo('会议已创建，可点击"运行"开始六阶段流程')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  // 运行会议：先连 WS（selectMeeting），再触发同步 run（阻塞到六阶段完成）
  const handleRun = async () => {
    if (!createdId) return
    setBusy(true)
    setError(null)
    setInfo('正在运行会议……')
    // 先切换到会议视图并连接 WS，期间实时接收事件
    selectMeeting(createdId)
    try {
      await runMeeting(createdId)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="create-page">
      <div className="create-card">
        <h1 className="create-title">Conclave</h1>
        <p className="create-subtitle">会议型多智能体系统 · 迭代一</p>

        <form onSubmit={handleCreate} className="create-form">
          <label className="form-row">
            <span className="field-label">会议议题</span>
            <textarea
              className="topic-input"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="例如：设计一个支持 Markdown 资料检索的多智能体会议系统"
              rows={3}
              disabled={!!createdId || busy}
            />
          </label>

          <label className="form-row">
            <span className="field-label">产出类型</span>
            <select
              className="topic-input"
              value={deliverableType}
              onChange={(e) => setDeliverableType(e.target.value)}
              disabled={!!createdId || busy}
              style={{ height: 'auto', minHeight: '38px', padding: '6px 10px' }}
            >
              <option value="prd_openapi">PRD + OpenAPI（产品设计文档）</option>
              <option value="design_doc">设计文档</option>
              <option value="comprehensive">综合文档</option>
              <option value="research_report">调研报告</option>
              <option value="business_report">商业报告</option>
              <option value="code_analysis">代码分析（数据科学沙箱）</option>
              <option value="tested_system">测试系统（代码 + pytest）</option>
              <option value="deployable_service">可部署服务（Docker 镜像）</option>
            </select>
          </label>

          <label className="form-row">
            <span className="field-label">引用历史会议（可选）</span>
            <MeetingSearchSelect
              selectedIds={referenceIds}
              onChange={setReferenceIds}
              placeholder="搜索历史会议作为参考依据…"
            />
          </label>

          <label className="form-row">
            <span className="field-label">上传资料（可选 .md）</span>
            <input
              type="file"
              accept=".md,.markdown,text/markdown"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={!!createdId || busy}
            />
            {file && <span className="file-name">{file.name}</span>}
          </label>

          {/* 模型选择（可折叠） */}
          <div className="form-row">
            <button
              type="button"
              className="model-section-toggle"
              onClick={() => setModelExpanded(v => !v)}
              disabled={!!createdId || busy}
            >
              <span className="model-toggle-arrow">{modelExpanded ? '▾' : '▸'}</span>
              <span className="field-label">模型与 API Key</span>
              {!modelExpanded && (
                <span className="model-current-brief">
                  {isCustomModel ? modelSel.model : `默认：${defaultSel.model}`}
                  {modelSel.api_key && ' · 自定义Key'}
                </span>
              )}
            </button>
            {modelExpanded && (
              <div className="model-section-body">
                <ModelSelector
                  value={modelSel}
                  onChange={setModelSel}
                  disabled={!!createdId || busy}
                />
              </div>
            )}
          </div>

          {!createdId ? (
            <button type="submit" className="btn btn-primary" disabled={busy || !topic.trim()}>
              {busy ? '创建中…' : '创建会议'}
            </button>
          ) : (
            <div className="created-actions">
              <div className="created-info">
                会议已创建：<code>{createdId}</code>
              </div>
              {info && <div className="info-line">{info}</div>}
              <button
                type="button"
                className="btn btn-primary run-btn"
                onClick={handleRun}
                disabled={busy}
              >
                {busy ? '运行中…' : '运行会议'}
              </button>
            </div>
          )}
          {error && <div className="error-line">{error}</div>}
        </form>
      </div>
    </div>
  )
}
