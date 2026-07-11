// 工作区面板：递归文件树 + 代码编辑器 + 终端输出
// 让 Conclave 产出能直接被写入文件、运行、查看结果
//
// [CON-11 修复] 文件树改为递归结构 + 按需展开：
//   旧版：buildTree 只看一层，目录点击 = 切换根目录（不是展开），
//         内嵌项目（src/utils/helper.py）无法直达，需要反复刷新。
//   新版：
//     1) 客户端维护扁平 tree map（path -> NodeState），目录有 children 数组
//     2) 点击目录 = 切换 expanded 状态（不重新拉根目录）
//     3) 首次展开某目录时调 listFiles 懒加载子节点
//     4) 用后端返回的 child_count 字段（>= 1）判断目录是否可展开
//
// [CON-11 修复] 文件名后缀 → Monaco language 映射：
//   旧版 hardcode 永远 'python'（readFile 也会带 language 后端字段，
//   但客户端忽略，统一用 python）。现在按扩展名做 lookup 表。
import { useState, useEffect, useRef, useCallback } from 'react'
import type React from 'react'
import { Button, Space } from 'antd'
import { ReloadOutlined, PlusOutlined, SaveOutlined, PlayCircleOutlined } from '@ant-design/icons'
import Editor from '@monaco-editor/react'
import {
  listFiles,
  readFile,
  writeFile,
  execCommand,
  runCode,
  sandboxStatus,
  type FileItem,
} from '../lib/api.ts'

/** 文件树节点（递归） */
interface TreeNode {
  name: string
  path: string
  type: 'file' | 'directory'
  /** 仅 directory 有：是否已展开 */
  expanded?: boolean
  /** 仅 directory 有：子节点是否已加载 */
  loaded?: boolean
  /** 仅 directory 有：子节点（懒加载） */
  children?: TreeNode[]
  /** 仅 directory 有：可见子节点数（用于折叠态显示 (3)） */
  child_count?: number
  /** 加载状态：防止重复请求 */
  loading?: boolean
}

/**
 * [CON-11] 文件扩展名 → Monaco language id 映射
 * 覆盖 Conclave 主要产出场景（数据分析、代码生成、报告）
 * 未列出的扩展名 fallback 到后端 readFile 返回的 language 字段
 */
const EXT_LANG_MAP: Record<string, string> = {
  // Python 系列
  '.py': 'python', '.pyi': 'python', '.pyw': 'python',
  // Web/前端
  '.ts': 'typescript', '.tsx': 'typescript', '.js': 'javascript',
  '.jsx': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
  '.html': 'html', '.htm': 'html', '.css': 'css', '.scss': 'scss',
  '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'ini',
  // 通用脚本
  '.sh': 'shell', '.bash': 'shell', '.zsh': 'shell',
  '.ps1': 'powershell', '.bat': 'bat', '.cmd': 'bat',
  // 系统语言
  '.go': 'go', '.rs': 'rust', '.java': 'java', '.kt': 'kotlin',
  '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.hpp': 'cpp', '.cc': 'cpp',
  '.cs': 'csharp', '.rb': 'ruby', '.php': 'php', '.lua': 'lua',
  '.sql': 'sql', '.r': 'r',
  // 数据
  '.md': 'markdown', '.markdown': 'markdown',
  '.xml': 'xml', '.svg': 'xml', '.tex': 'latex',
  // 配置
  '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini', '.env': 'ini',
  '.dockerfile': 'dockerfile', 'Dockerfile': 'dockerfile',
}

/** 根据文件路径推断 Monaco language */
function detectLanguage(path: string, fallback: string = 'plaintext'): string {
  const lower = path.toLowerCase()
  // Dockerfile（无扩展名）
  if (lower.endsWith('dockerfile')) return 'dockerfile'
  // 找扩展名
  const dotIdx = lower.lastIndexOf('.')
  if (dotIdx > 0 && dotIdx < lower.length - 1) {
    const ext = lower.slice(dotIdx)
    if (EXT_LANG_MAP[ext]) return EXT_LANG_MAP[ext]
  }
  return fallback
}

interface WorkspacePanelProps {
  /** 当前会议 ID，用于文件隔离（工作区按 meeting_id/ 分目录） */
  meetingId?: string
  /** 初始打开的文件路径（相对于 meeting_id/ 子目录） */
  initialFile?: string
}

export function WorkspacePanel({ meetingId, initialFile }: WorkspacePanelProps) {
  // 当前路径前缀：会议隔离时为 meetingId/，否则为空
  const pathPrefix = meetingId ? `${meetingId}/` : ''

  // 文件树
  // [CON-11 修复] 改用嵌套 tree（递归） + 扁平化 pathMap 索引
  // 旧版是单层 tree.map，遇到 src/ 下多个子文件就进不去
  const [tree, setTree] = useState<TreeNode[]>([])
  // path → node，便于 O(1) 更新目录的 expanded/children
  const [pathMap, setPathMap] = useState<Map<string, TreeNode>>(new Map())
  const [currentPath, setCurrentPath] = useState<string>('')
  const [loading, setLoading] = useState(false)

  /**
   * 将扁平 FileItem 列表转为树节点列表（顶层）
   * [BUG FIX] 后端 listFiles 返回的 path 是相对 WORKSPACE_ROOT 的完整路径
   * （含 meetingId 前缀），需剥离 pathPrefix 使树节点路径始终相对会议根目录。
   * 否则 openFile / toggleExpand 再拼一次前缀会导致路径翻倍。
   */
  const buildRootTreeItems = useCallback(
    (items: FileItem[]): TreeNode[] =>
      items.map((i) => {
        let relPath = i.path
        if (pathPrefix && relPath.startsWith(pathPrefix)) {
          relPath = relPath.slice(pathPrefix.length)
        }
        return {
          name: i.name,
          path: relPath,
          type: i.type,
          expanded: false,
          loaded: false,
          child_count: i.child_count ?? 0,
        }
      }),
    [pathPrefix],
  )

  // 编辑器
  const [fileContent, setFileContent] = useState('')
  const [filePath, setFilePath] = useState('')
  const [fileLang, setFileLang] = useState('python')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  // 终端
  const [terminalInput, setTerminalInput] = useState('')
  const [terminalHistory, setTerminalHistory] = useState<
    Array<{ type: 'cmd' | 'out' | 'err'; text: string }>
  >([])
  const [running, setRunning] = useState(false)

  // 沙箱状态
  const [sandbox, setSandbox] = useState<{
    active: boolean
    image: string
    mode: string
  } | null>(null)

  // 编辑器内容变化标记
  const editorRef = useRef<Parameters<NonNullable<Parameters<typeof Editor>[0]['onMount']>>[0] | null>(null)

  /** 刷新文件列表（顶层） */
  const refreshTree = useCallback(async (path = '') => {
    setLoading(true)
    try {
      const fullPath = pathPrefix + path
      const res = await listFiles(fullPath)
      const nodes = buildRootTreeItems(res.items)
      setTree(nodes)
      // 重建 pathMap
      const map = new Map<string, TreeNode>()
      nodes.forEach((n) => map.set(n.path, n))
      setPathMap(map)
      setCurrentPath(path)
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: `读取目录失败: ${(e as Error).message}` },
      ])
    } finally {
      setLoading(false)
    }
  }, [pathPrefix])

  /**
   * [CON-11 修复] 切换目录展开状态 + 懒加载子节点
   * - 旧版：点击目录直接 refreshTree(node.path)，丢失父目录上下文
   * - 新版：保持根目录不变，仅加载该目录的子节点
   */
  const toggleExpand = useCallback(async (dirPath: string) => {
    const node = pathMap.get(dirPath)
    if (!node || node.type !== 'directory') return

    // 已展开 → 收起
    if (node.expanded) {
      setPathMap((prev) => {
        const next = new Map(prev)
        const target = next.get(dirPath)
        if (target) {
          next.set(dirPath, { ...target, expanded: false })
        }
        return next
      })
      return
    }

    // 未展开 → 标记展开
    setPathMap((prev) => {
      const next = new Map(prev)
      const target = next.get(dirPath)
      if (target) {
        next.set(dirPath, { ...target, expanded: true, loading: !target.loaded })
      }
      return next
    })

    // 懒加载：未加载过的才请求
    if (!node.loaded) {
      try {
        const fullPath = pathPrefix + dirPath
        const res = await listFiles(fullPath)
        const childNodes: TreeNode[] = buildRootTreeItems(res.items)
        setPathMap((prev) => {
          const next = new Map(prev)
          const target = next.get(dirPath)
          if (target) {
            next.set(dirPath, {
              ...target,
              loaded: true,
              loading: false,
              children: childNodes,
            })
            // 索引子节点
            childNodes.forEach((c) => next.set(c.path, c))
          }
          return next
        })
      } catch (e) {
        setPathMap((prev) => {
          const next = new Map(prev)
          const target = next.get(dirPath)
          if (target) {
            next.set(dirPath, { ...target, loading: false })
          }
          return next
        })
        setTerminalHistory((h) => [
          ...h,
          { type: 'err', text: `展开目录失败: ${(e as Error).message}` },
        ])
      }
    }
  }, [pathMap, pathPrefix, buildRootTreeItems])

  /** 打开文件 */
  const openFile = useCallback(async (path: string) => {
    try {
      const fullPath = pathPrefix + path
      const res = await readFile(fullPath)
      setFilePath(res.path)
      setFileContent(res.content)
      // [CON-11 修复] 优先用后端 language 字段，客户端扩展名映射作为 fallback
      // 旧版固定 'python'，导致 .ts/.json/.md 等文件被当作 Python 高亮
      setFileLang(detectLanguage(res.path, res.language || 'plaintext'))
      setDirty(false)
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: `打开文件失败: ${(e as Error).message}` },
      ])
    }
  }, [pathPrefix])

  /** 保存文件 */
  const saveFile = useCallback(async () => {
    if (!filePath) return
    setSaving(true)
    try {
      // filePath 是相对会议根的路径，需加 pathPrefix 拼接完整路径
      const fullPath = pathPrefix + filePath
      await writeFile(fullPath, fileContent)
      setDirty(false)
      setTerminalHistory((h) => [
        ...h,
        { type: 'out', text: `已保存: ${filePath}` },
      ])
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: `保存失败: ${(e as Error).message}` },
      ])
    } finally {
      setSaving(false)
    }
  }, [filePath, fileContent, pathPrefix])

  /** 执行终端命令 */
  const runTerminalCommand = useCallback(async () => {
    if (!terminalInput.trim() || running) return
    const cmd = terminalInput.trim()
    setTerminalInput('')
    setTerminalHistory((h) => [...h, { type: 'cmd', text: cmd }])
    setRunning(true)
    try {
      const res = await execCommand(cmd)
      if (res.stdout) {
        setTerminalHistory((h) => [...h, { type: 'out', text: res.stdout }])
      }
      if (res.stderr) {
        setTerminalHistory((h) => [...h, { type: 'err', text: res.stderr }])
      }
      if (res.exit_code !== 0) {
        setTerminalHistory((h) => [
          ...h,
          { type: 'err', text: `[退出码 ${res.exit_code}]` },
        ])
      }
      if (!res.sandboxed) {
        setTerminalHistory((h) => [
          ...h,
          { type: 'err', text: `[警告] ${res.fallback_reason || '执行未隔离'}` },
        ])
      }
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: (e as Error).message },
      ])
    } finally {
      setRunning(false)
    }
  }, [terminalInput, running])

  /** 运行当前编辑器代码 */
  const runEditorCode = useCallback(async () => {
    if (!fileContent.trim() || running) return
    setRunning(true)
    setTerminalHistory((h) => [
      ...h,
      { type: 'cmd', text: `[运行代码] ${filePath || 'untitled'}` },
    ])
    try {
      const res = await runCode(fileContent, fileLang === 'python' ? 'python' : 'python')
      if (res.stdout) {
        setTerminalHistory((h) => [...h, { type: 'out', text: res.stdout }])
      }
      if (res.stderr) {
        setTerminalHistory((h) => [...h, { type: 'err', text: res.stderr }])
      }
      if (!res.sandboxed) {
        setTerminalHistory((h) => [
          ...h,
          { type: 'err', text: `[警告] ${res.fallback_reason || '执行未隔离'}` },
        ])
      }
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: (e as Error).message },
      ])
    } finally {
      setRunning(false)
    }
  }, [fileContent, filePath, fileLang, running])

  /** 新建文件 */
  const newFile = useCallback(() => {
    setFilePath('')
    setFileContent('')
    setFileLang('python')
    setDirty(false)
  }, [])

  /** 终端自动滚动 */
  const terminalRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight
    }
  }, [terminalHistory])

  // 初始加载文件树 + 沙箱状态；meetingId 或 initialFile 变化时重新加载
  useEffect(() => {
    refreshTree('')
    sandboxStatus()
      .then((s) =>
        setSandbox({ active: s.active, image: s.image, mode: s.mode }),
      )
      .catch(() => null)
    // 若指定了初始文件，自动打开
    if (initialFile) {
      openFile(initialFile)
    }
  }, [refreshTree, openFile, initialFile])

  // [CON-11 修复] 递归渲染文件树
  // 旧版只渲染顶层，内嵌项目无法展示。
  // 新版：递归组件 TreeNodeView 接收 nodes 数组 + depth 缩进，依次渲染
  // 目录点击 → toggleExpand；文件点击 → openFile
  const renderTreeNodes = (nodes: TreeNode[], depth: number = 0): React.ReactElement => {
    if (nodes.length === 0) {
      return <div className="ws-tree-empty">空目录</div>
    }
    return (
      <>
        {nodes.map((node) => {
          const isDir = node.type === 'directory'
          const expanded = node.expanded ?? false
          const childCount = node.child_count ?? 0
          const isActive = filePath === node.path
          return (
            <div key={node.path} className="ws-tree-entry">
              <div
                className={`ws-tree-item ${node.type} ${isActive ? 'active' : ''}`}
                style={{ paddingLeft: `${depth * 14 + 8}px` }}
                onClick={() => {
                  if (isDir) {
                    toggleExpand(node.path)
                  } else {
                    openFile(node.path)
                  }
                }}
              >
                <span className="ws-icon">
                  {isDir ? (expanded ? '📂' : '📁') : '📄'}
                </span>
                <span className="ws-name">{node.name}</span>
                {isDir && childCount > 0 && !expanded && (
                  <span className="ws-count">({childCount})</span>
                )}
                {isDir && node.loading && <span className="ws-spin">…</span>}
              </div>
              {/* 递归渲染子节点：仅当目录已展开且有 children */}
              {isDir && expanded && node.children && (
                <div className="ws-tree-children">
                  {renderTreeNodes(node.children, depth + 1)}
                </div>
              )}
            </div>
          )
        })}
      </>
    )
  }

  return (
    <div className="workspace-panel">
      {/* 工具栏 */}
      <div className="ws-toolbar">
        <Space size={4}>
          <Button
            size="small"
            icon={<ReloadOutlined spin={loading} />}
            onClick={() => refreshTree(currentPath)}
            disabled={loading}
          >
            刷新
          </Button>
          <Button size="small" icon={<PlusOutlined />} onClick={newFile}>
            新建
          </Button>
          <Button
            type="primary"
            size="small"
            icon={<SaveOutlined />}
            onClick={saveFile}
            disabled={!dirty || saving}
            loading={saving}
          >
            保存
          </Button>
          <Button
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={runEditorCode}
            disabled={running || !fileContent.trim()}
          >
            运行代码
          </Button>
        </Space>
        {dirty && <span className="ws-dirty">●</span>}
        {/* 沙箱状态徽章 */}
        {sandbox && (
          <span
            className={`ws-sandbox-badge ${sandbox.active ? 'active' : 'inactive'}`}
            title={
              sandbox.active
                ? `容器隔离: ${sandbox.image}`
                : `未隔离 (${sandbox.mode})`
            }
          >
            {sandbox.active ? '🛡 容器隔离' : '⚠ 宿主机直连'}
          </span>
        )}
      </div>

      <div className="ws-body">
        {/* 左侧：文件树 */}
        <div className="ws-sidebar">
          <div className="ws-sidebar-header">
            {currentPath || '/'}
          </div>
          <div className="ws-file-tree">
            {tree.length === 0 && !loading ? (
              <div className="ws-empty">空目录</div>
            ) : (
              renderTreeNodes(tree)
            )}
          </div>
        </div>

        {/* 中间：编辑器 */}
        <div className="ws-editor-area">
          {filePath ? (
            <div className="ws-file-tab">{filePath}</div>
          ) : (
            <div className="ws-file-tab">untitled.py</div>
          )}
          <div className="ws-editor-container">
            <Editor
              height="100%"
              language={fileLang}
              value={fileContent}
              onChange={(val) => {
                setFileContent(val || '')
                setDirty(true)
              }}
              onMount={(editor) => {
                editorRef.current = editor
              }}
              theme="vs"
              options={{
                fontSize: 13,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                wordWrap: 'on',
                tabSize: 4,
                automaticLayout: true,
              }}
            />
          </div>
        </div>

        {/* 右侧：终端 */}
        <div className="ws-terminal">
          <div className="ws-terminal-header">
            终端
            {running && <span className="ws-running">运行中...</span>}
          </div>
          <div className="ws-terminal-output" ref={terminalRef}>
            {terminalHistory.length === 0 ? (
              <div className="ws-terminal-empty">
                终端就绪。输入命令或点击"运行代码"。
              </div>
            ) : (
              terminalHistory.map((entry, i) => (
                <div
                  key={i}
                  className={`ws-terminal-line ws-${entry.type}`}
                >
                  <pre>{entry.text}</pre>
                </div>
              ))
            )}
          </div>
          <div className="ws-terminal-input-row">
            <input
              type="text"
              className="ws-terminal-input"
              value={terminalInput}
              onChange={(e) => setTerminalInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') runTerminalCommand()
              }}
              placeholder="$ 输入命令..."
              disabled={running}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
