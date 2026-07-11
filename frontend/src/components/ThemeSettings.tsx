/**
 * ThemeSettings：主题设置面板（亮暗切换 + Token 级覆盖）
 * 使用 AntD Drawer + Segmented + Collapse + ColorPicker + Button + Typography
 */
import { useState } from 'react'
import { Drawer, Segmented, Collapse, ColorPicker, Button, Typography, Space, Input, Tag } from 'antd'
import { UndoOutlined } from '@ant-design/icons'
import { OVERRIDABLE_TOKENS, useTheme } from '../store/ThemeContext'

const { Text } = Typography

interface Props {
  onClose: () => void
}

export function ThemeSettings({ onClose }: Props) {
  const { mode, setMode, overrides, setTokenOverride, resetToken, resetAllTokens, syncStatus } = useTheme()
  const [expandedGroup, setExpandedGroup] = useState<string>('色彩')

  // 按 group 分组
  type Entry = [string, { label: string; type: string; group: string }]
  const grouped: Record<string, Entry[]> = {}
  for (const [token, meta] of Object.entries(OVERRIDABLE_TOKENS)) {
    if (!grouped[meta.group]) grouped[meta.group] = []
    grouped[meta.group].push([token, meta])
  }

  const syncLabel = {
    idle: '未同步',
    syncing: '同步中…',
    synced: '已同步',
    error: '同步失败',
  }[syncStatus]

  const syncColor = {
    idle: 'default',
    syncing: 'processing',
    synced: 'success',
    error: 'error',
  }[syncStatus] as string

  const collapseItems = Object.entries(grouped).map(([group, tokens]) => ({
    key: group,
    label: (
      <Space>
        <Text>{group}</Text>
        <Tag>{tokens.length}</Tag>
      </Space>
    ),
    children: (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {tokens.map(([token, meta]) => (
          <div key={token} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <Text style={{ fontSize: 13 }}>{meta.label}</Text>
              <br />
              <Text type="secondary" style={{ fontSize: 11 }}>--{token}</Text>
            </div>
            <Space size={4}>
              {meta.type === 'color' && (
                <ColorPicker
                  size="small"
                  value={overrides[token] || getComputedStyle(document.documentElement).getPropertyValue(`--${token}`).trim() || '#000000'}
                  onChange={(_, hex) => setTokenOverride(token, hex)}
                />
              )}
              {(meta.type === 'size' || meta.type === 'font') && (
                <Input
                  size="small"
                  placeholder={meta.type === 'size' ? '如 6px' : '字体栈'}
                  value={overrides[token] || ''}
                  onChange={e => setTokenOverride(token, e.target.value)}
                  style={{ width: meta.type === 'font' ? 160 : 80 }}
                />
              )}
              {overrides[token] && (
                <Button type="text" size="small" icon={<UndoOutlined />} onClick={() => resetToken(token)} style={{ fontSize: 11 }}>
                  重置
                </Button>
              )}
            </Space>
          </div>
        ))}
      </div>
    ),
  }))

  return (
    <Drawer
      open
      title={
        <Space>
          <Text strong>主题设置</Text>
          <Tag color={syncColor}>{syncLabel}</Tag>
        </Space>
      }
      onClose={onClose}
      width={420}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Button icon={<UndoOutlined />} onClick={resetAllTokens}>
            重置全部 Token
          </Button>
          <Button type="primary" onClick={onClose}>完成</Button>
        </div>
      }
    >
      <div style={{ marginBottom: 24 }}>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>主题模式</Text>
        <Segmented
          value={mode}
          onChange={(val) => setMode(val as 'light' | 'dark')}
          options={[
            { label: '亮色', value: 'light' },
            { label: '暗色', value: 'dark' },
          ]}
          block
        />
      </div>

      <div>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>Token 覆盖</Text>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
          默认规则基于设计规范，此处可覆盖
        </Text>
        <Collapse
          activeKey={expandedGroup || undefined}
          onChange={(keys) => setExpandedGroup(Array.isArray(keys) ? keys[0] ?? '' : keys ?? '')}
          items={collapseItems}
          size="small"
        />
      </div>
    </Drawer>
  )
}
