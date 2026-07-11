// 左侧可折叠抽屉菜单：在看板/运维面板层级显示
// 使用 AntD Layout.Sider + Menu + Button
import { Layout, Menu, Button } from 'antd'
import { AppstoreOutlined, BarChartOutlined, CloudServerOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import { navigate } from '../lib/router.ts'
import { usePersistentState } from '../hooks/usePersistentState.ts'

const { Sider } = Layout

interface DrawerMenuProps {
  currentPath: string
}

export function DrawerMenu({ currentPath }: DrawerMenuProps) {
  const [collapsed, setCollapsed] = usePersistentState<boolean>(
    'conclave-drawer-collapsed',
    false,
  )

  const menuItems = [
    { key: '/board', icon: <AppstoreOutlined />, label: '会议看板' },
    { key: '/dashboard', icon: <BarChartOutlined />, label: '运维面板' },
    { key: '/models', icon: <CloudServerOutlined />, label: '模型管理' },
  ]

  const selectedKey = menuItems.find(item => item.key === currentPath)?.key ?? '/board'

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={setCollapsed}
      trigger={null}
      width={200}
      collapsedWidth={48}
      style={{
        background: 'var(--card-bg, #fff)',
        borderRight: '1px solid var(--border-color, #e5e7eb)',
        minHeight: '100vh',
      }}
    >
      <div style={{
        padding: collapsed ? '16px 8px' : '16px',
        display: 'flex',
        justifyContent: collapsed ? 'center' : 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid var(--border-color, #e5e7eb)',
      }}>
        {!collapsed && <span style={{ fontWeight: 600, fontSize: 16 }}>Conclave</span>}
        <Button
          type="text"
          size="small"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={() => setCollapsed(!collapsed)}
        />
      </div>
      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        style={{ borderRight: 'none' }}
      />
    </Sider>
  )
}
