// 设置面板：管理 LLM 默认模型、API Key 等本地偏好
// 使用 AntD Drawer + Form + Switch + Button + List + Typography + Popconfirm + Alert + Divider
import { useState, useEffect, useCallback } from 'react'
import type { FC } from 'react'
import { Drawer, Switch, Button, List, Typography, Alert, Divider, Space } from 'antd'
import { SaveOutlined, DeleteOutlined, UndoOutlined } from '@ant-design/icons'
import { ModelSelector, type ModelSelection } from './ModelSelector.tsx'
import {
  loadPreferences,
  savePreferences,
  resetPreferences,
  exportPreferences,
  onPreferencesChanged,
  type LLMPreferences,
} from '../lib/llmPreferences.ts'

const { Text, Title } = Typography

interface Props {
  onClose: () => void
}

export const SettingsPanel: FC<Props> = ({ onClose }) => {
  const [prefs, setPrefs] = useState<LLMPreferences>(() => loadPreferences())
  const [sel, setSel] = useState<ModelSelection>(() => {
    const p = loadPreferences()
    return {
      provider_id: p.default_provider_id,
      model: p.default_model,
      api_key: p.api_keys[p.default_provider_id] || '',
      base_url: p.default_provider_id === 'custom' ? p.custom_base_url : '',
    }
  })
  const [savedMsg, setSavedMsg] = useState<string | null>(null)
  const [showResetConfirm, setShowResetConfirm] = useState(false)

  useEffect(() => {
    return onPreferencesChanged(() => {
      setPrefs(loadPreferences())
    })
  }, [])

  const handleSaveDefault = useCallback(() => {
    const newPrefs: LLMPreferences = {
      ...prefs,
      default_provider_id: sel.provider_id,
      default_model: sel.model,
      custom_base_url: sel.provider_id === 'custom' ? sel.base_url : prefs.custom_base_url,
      api_keys: { ...prefs.api_keys },
    }
    if (sel.api_key) {
      newPrefs.api_keys[sel.provider_id] = sel.api_key
    } else {
      delete newPrefs.api_keys[sel.provider_id]
    }
    savePreferences(newPrefs)
    setPrefs(newPrefs)
    setSavedMsg('已保存默认设置')
    setTimeout(() => setSavedMsg(null), 2000)
  }, [prefs, sel])

  const handleRemoveKey = (providerId: string) => {
    const newPrefs = { ...prefs, api_keys: { ...prefs.api_keys } }
    delete newPrefs.api_keys[providerId]
    savePreferences(newPrefs)
    setPrefs(newPrefs)
    if (sel.provider_id === providerId) {
      setSel(s => ({ ...s, api_key: '' }))
    }
  }

  const handleToggleAutoSave = () => {
    const newPrefs = { ...prefs, auto_save_model: !prefs.auto_save_model }
    savePreferences(newPrefs)
    setPrefs(newPrefs)
  }

  const handleReset = () => {
    resetPreferences()
    const fresh = loadPreferences()
    setPrefs(fresh)
    setSel({
      provider_id: fresh.default_provider_id,
      model: fresh.default_model,
      api_key: '',
      base_url: '',
    })
    setShowResetConfirm(false)
    setSavedMsg('已重置为默认设置')
    setTimeout(() => setSavedMsg(null), 2000)
  }

  const savedKeyProviders = Object.entries(prefs.api_keys).filter(([, v]) => v)

  return (
    <Drawer
      open
      title={
        <div>
          <Title level={4} className="settings-panel-title">设置</Title>
          <Text type="secondary" className="settings-panel-hint">LLM 模型和 API Key 偏好保存在浏览器本地</Text>
        </div>
      }
      onClose={onClose}
      width={480}
      footer={
        <div className="settings-panel-footer">
          {showResetConfirm ? (
            <Space>
              <Text type="danger" className="settings-panel-hint">确定重置所有设置？</Text>
              <Button size="small" onClick={() => setShowResetConfirm(false)}>取消</Button>
              <Button size="small" danger onClick={handleReset}>确认重置</Button>
            </Space>
          ) : (
            <>
              <Button size="small" icon={<UndoOutlined />} onClick={() => setShowResetConfirm(true)}>
                重置全部
              </Button>
              <Button type="primary" size="small" onClick={onClose}>完成</Button>
            </>
          )}
        </div>
      }
    >
      {savedMsg && <Alert message={savedMsg} type="success" showIcon className="settings-panel-alert" />}

      <div className="settings-panel-section">
        <Text strong>默认模型</Text>
        <Text type="secondary" className="settings-panel-section-hint">
          新创建的会议将默认使用此模型。会议中可随时切换。
        </Text>
        <ModelSelector value={sel} onChange={setSel} showHeader={false} />
        <div className="settings-panel-mt-8">
          <Button type="primary" size="small" icon={<SaveOutlined />} onClick={handleSaveDefault} disabled={!sel.model}>
            保存为默认
          </Button>
        </div>
      </div>

      <Divider />

      <div className="settings-panel-section">
        <Text strong>会议中切换</Text>
        <div className="settings-panel-switch-row">
          <Switch checked={prefs.auto_save_model} onChange={handleToggleAutoSave} />
          <Text>会议中切换模型时自动保存为默认</Text>
        </div>
      </div>

      <Divider />

      <div className="settings-panel-section">
        <Text strong>已保存的 API Key</Text>
        {savedKeyProviders.length === 0 ? (
          <Text type="secondary" className="settings-panel-block-hint">
            暂无保存的 Key。在上方选择厂商并输入 Key 后点"保存为默认"即可保存。
          </Text>
        ) : (
          <List
            size="small"
            className="settings-panel-mt-8"
            dataSource={savedKeyProviders}
            renderItem={([pid, key]) => (
              <List.Item
                actions={[
                  <Button key="del" type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => handleRemoveKey(pid)}>
                    删除
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={pid}
                  description={`${key.slice(0, 6)}...${key.slice(-4)}`}
                />
              </List.Item>
            )}
          />
        )}
      </div>

      <Divider />

      <div>
        <Text strong>数据管理</Text>
        <Text type="secondary" className="settings-panel-block-hint">
          设置存储在浏览器 localStorage 中，清除浏览器数据会丢失。
          当前配置：{exportPreferences().length > 10 ? '已配置默认模型' : '未配置'}
          {savedKeyProviders.length > 0 && `，${savedKeyProviders.length} 个 Key`}
        </Text>
      </div>
    </Drawer>
  )
}
