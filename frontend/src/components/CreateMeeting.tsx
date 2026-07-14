// 初始页面：输入议题 + 上传 md + 创建 + 运行
// 使用 AntD Form + Input.TextArea + Select + Upload + Button + Card + Alert + Collapse
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Form, Input, Select, Upload, Button, Card, Alert, Collapse, Typography, Space } from 'antd'
import { UploadOutlined, PlayCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { useMeeting } from '../store/MeetingContext.tsx'
import { MeetingSearchSelect } from './MeetingSearchSelect.tsx'
import { ModelSelector, type ModelSelection } from './ModelSelector.tsx'
import { setMeetingModel as apiSetMeetingModel } from '../lib/api.ts'
import { getDefaultSelection, setApiKey as saveApiKey, setDefaultSelection, loadPreferences } from '../lib/llmPreferences.ts'

const { Title, Text } = Typography

const DELIVERABLE_OPTIONS = [
  { value: 'prd_openapi', label: 'PRD + OpenAPI（产品设计文档）' },
  { value: 'design_doc', label: '设计文档' },
  { value: 'comprehensive', label: '综合文档' },
  { value: 'research_report', label: '调研报告' },
  { value: 'business_report', label: '商业报告' },
  { value: 'code_analysis', label: '代码分析（数据科学沙箱）' },
  { value: 'data_science', label: '数据科学分析（证据驱动）' },
  { value: 'tested_system', label: '测试系统（代码 + pytest）' },
  { value: 'deployable_service', label: '可部署服务（Docker 镜像）' },
]

export function CreateMeeting() {
  const { createMeeting, uploadDocument, selectMeeting, runMeeting } = useMeeting()
  const [topic, setTopic] = useState('')
  const [deliverableType, setDeliverableType] = useState('prd_openapi')
  const [file, setFile] = useState<File | null>(null)
  const [referenceIds, setReferenceIds] = useState<string[]>([])
  const [modelSel, setModelSel] = useState<ModelSelection>(() => getDefaultSelection())
  const [modelExpanded, setModelExpanded] = useState(false)
  const [createdId, setCreatedId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  const defaultSel = getDefaultSelection()
  const isCustomModel = modelSel.provider_id !== defaultSel.provider_id
    || modelSel.model !== defaultSel.model
    || (modelSel.api_key !== '' && modelSel.api_key !== defaultSel.api_key)
    || modelSel.base_url !== defaultSel.base_url

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
      if (isCustomModel) {
        try {
          await apiSetMeetingModel(res.meeting_id, {
            provider_id: modelSel.provider_id,
            model: modelSel.model,
            api_key: modelSel.api_key || undefined,
            base_url: modelSel.base_url || undefined,
          })
          if (modelSel.api_key) {
            saveApiKey(modelSel.provider_id, modelSel.api_key)
          }
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

  const handleRun = async () => {
    if (!createdId) return
    setBusy(true)
    setError(null)
    setInfo('正在运行会议……')
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
    <div className="create-page create-meeting-page">
      <Card className="create-meeting-card">
        <Title level={2} className="create-meeting-title">Conclave</Title>
        <Text type="secondary" className="create-meeting-subtitle">
          会议型多智能体系统 · 迭代一
        </Text>

        <form onSubmit={handleCreate}>
          <Form layout="vertical">
            <Form.Item label="会议议题" required>
              <Input.TextArea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="例如：设计一个支持 Markdown 资料检索的多智能体会议系统"
                rows={3}
                disabled={!!createdId || busy}
              />
            </Form.Item>

            <Form.Item label="产出类型">
              <Select
                value={deliverableType}
                onChange={setDeliverableType}
                options={DELIVERABLE_OPTIONS}
                disabled={!!createdId || busy}
              />
            </Form.Item>

            <Form.Item label="引用历史会议（可选）">
              <MeetingSearchSelect
                selectedIds={referenceIds}
                onChange={setReferenceIds}
                placeholder="搜索历史会议作为参考依据…"
              />
            </Form.Item>

            <Form.Item label="上传资料（可选 .md）">
              <Upload
                accept=".md,.markdown,text/markdown"
                maxCount={1}
                beforeUpload={(f) => { setFile(f as unknown as File); return false }}
                onRemove={() => setFile(null)}
                fileList={file ? [{ uid: '-1', name: file.name, status: 'done' } as any] : []}
                disabled={!!createdId || busy}
              >
                <Button icon={<UploadOutlined />}>选择文件</Button>
              </Upload>
            </Form.Item>

            <Collapse
              activeKey={modelExpanded ? ['model'] : []}
              onChange={(keys) => setModelExpanded(keys.includes('model'))}
              items={[{
                key: 'model',
                label: (
                  <Space>
                    <Text>模型与 API Key</Text>
                    {!modelExpanded && (
                      <Text type="secondary" className="create-meeting-model-hint">
                        {isCustomModel ? modelSel.model : `默认：${defaultSel.model}`}
                        {modelSel.api_key && ' · 自定义Key'}
                      </Text>
                    )}
                  </Space>
                ),
                children: (
                  <ModelSelector
                    value={modelSel}
                    onChange={setModelSel}
                    disabled={!!createdId || busy}
                  />
                ),
              }]}
              className="create-meeting-collapse"
            />
          </Form>

          {!createdId ? (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              htmlType="submit"
              block
              loading={busy}
              disabled={!topic.trim()}
            >
              创建会议
            </Button>
          ) : (
            <Space direction="vertical" className="create-meeting-actions">
              <Alert
                message={`会议已创建：${createdId}`}
                description={info || undefined}
                type="success"
                showIcon
              />
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                block
                onClick={handleRun}
                loading={busy}
              >
                运行会议
              </Button>
            </Space>
          )}

          {error && <Alert message={error} type="error" showIcon className="create-meeting-error" />}
        </form>
      </Card>
    </div>
  )
}
