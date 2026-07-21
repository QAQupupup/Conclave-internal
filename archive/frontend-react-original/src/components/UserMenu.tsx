// 用户中心菜单：头像按钮 + Popover 弹出层
// 设计：Linear/GitHub 风格的圆形头像（首字母缩写），点击弹出用户信息卡片
import { useState } from 'react'
import { Popover, Divider } from 'antd'
import {
  SettingOutlined,
  LogoutOutlined,
  AppstoreOutlined,
  CrownOutlined,
} from '@ant-design/icons'
import { useAuth } from '../store/AuthContext.tsx'
import './UserMenu.css'

interface UserMenuProps {
  onOpenSettings?: () => void
  onNavigateBoard?: () => void
  onLogout?: () => void
}

/** 获取用户名首字母（支持中英文） */
function getInitials(name: string): string {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  // 中文取第一个字，英文取首字母
  const firstChar = trimmed[0]
  if (/[\u4e00-\u9fff]/.test(firstChar)) {
    return firstChar
  }
  // 英文取首字母大写
  return firstChar.toUpperCase()
}

/** 角色标签颜色 */
function getRoleStyle(role: string): { bg: string; color: string; label: string } {
  if (role === 'admin') {
    return { bg: '#fef3c7', color: '#92400e', label: '管理员' }
  }
  return { bg: '#eff6ff', color: '#1e40af', label: '用户' }
}

export function UserMenu({ onOpenSettings, onNavigateBoard, onLogout }: UserMenuProps) {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)

  if (!user) return null

  const initials = getInitials(user.display_name || user.username)
  const roleStyle = getRoleStyle(user.role)

  const handleLogout = () => {
    setOpen(false)
    if (onLogout) {
      onLogout()
    } else {
      logout()
    }
  }

  const handleSettings = () => {
    setOpen(false)
    onOpenSettings?.()
  }

  const handleBoard = () => {
    setOpen(false)
    onNavigateBoard?.()
  }

  const popoverContent = (
    <div className="um-popover">
      <div className="um-user-info">
        <div className="um-avatar um-avatar-lg">
          {initials}
        </div>
        <div className="um-user-meta">
          <div className="um-display-name">{user.display_name || user.username}</div>
          <div className="um-username">@{user.username}</div>
        </div>
      </div>
      <div className="um-role-badge" style={{ background: roleStyle.bg, color: roleStyle.color }}>
        {user.role === 'admin' && <CrownOutlined style={{ fontSize: 11, marginRight: 4 }} />}
        {roleStyle.label}
      </div>
      <Divider style={{ margin: '12px 0' }} />
      <div className="um-menu-list">
        {onNavigateBoard && (
          <button className="um-menu-item" onClick={handleBoard}>
            <AppstoreOutlined />
            <span>我的会议</span>
          </button>
        )}
        {onOpenSettings && (
          <button className="um-menu-item" onClick={handleSettings}>
            <SettingOutlined />
            <span>偏好设置</span>
          </button>
        )}
      </div>
      <Divider style={{ margin: '12px 0' }} />
      <button className="um-menu-item um-menu-danger" onClick={handleLogout}>
        <LogoutOutlined />
        <span>退出登录</span>
      </button>
    </div>
  )

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      content={popoverContent}
      trigger="click"
      placement="bottomRight"
      overlayClassName="um-popover-overlay"
      arrow={false}
    >
      <button className="um-trigger" aria-label="用户菜单">
        <span className="um-avatar">
          {initials}
        </span>
      </button>
    </Popover>
  )
}
