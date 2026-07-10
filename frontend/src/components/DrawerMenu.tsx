// 左侧可折叠抽屉菜单：在看板/运维面板层级显示
// 与会议视图内的 MeetingSidebar 互斥（不同层级）
import { navigate } from '../lib/router.ts'
import { usePersistentState } from '../hooks/usePersistentState.ts'

interface DrawerMenuProps {
  currentPath: string
}

export function DrawerMenu({ currentPath }: DrawerMenuProps) {
  const [collapsed, setCollapsed] = usePersistentState<boolean>(
    'conclave-drawer-collapsed',
    false,
  )

  const items = [
    { id: 'board', label: '会议看板', path: '/board' },
    { id: 'dashboard', label: '运维面板', path: '/dashboard' },
  ]

  const activeItem = items.find((item) => item.path === currentPath)?.id || 'board'

  if (collapsed) {
    return (
      <div className="drawer-menu drawer-collapsed">
        <button
          type="button"
          className="drawer-expand-btn"
          onClick={() => setCollapsed(false)}
          title="展开菜单"
          aria-label="展开菜单"
        >
          <span className="drawer-icon">›</span>
        </button>
      </div>
    )
  }

  return (
    <div className="drawer-menu">
      <div className="drawer-header">
        <span className="drawer-title">Conclave</span>
        <button
          type="button"
          className="drawer-collapse-btn"
          onClick={() => setCollapsed(true)}
          title="收起菜单"
          aria-label="收起菜单"
        >
          ‹
        </button>
      </div>
      <nav className="drawer-nav">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`drawer-item ${item.id === activeItem ? 'active' : ''}`}
            onClick={() => navigate(item.path)}
          >
            <span className="drawer-item-icon">
              {item.id === 'board' ? (
                <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <rect x="1" y="1" width="6" height="6" rx="1" />
                  <rect x="9" y="1" width="6" height="6" rx="1" />
                  <rect x="1" y="9" width="6" height="6" rx="1" />
                  <rect x="9" y="9" width="6" height="6" rx="1" />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="1" y="3" width="4" height="10" rx="1" />
                  <rect x="6.5" y="6" width="4" height="7" rx="1" />
                  <rect x="12" y="1" width="4" height="12" rx="1" />
                </svg>
              )}
            </span>
            <span className="drawer-item-label">{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}