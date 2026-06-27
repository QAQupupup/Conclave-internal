// 工作区面板：文件树 + 代码编辑器 + 终端输出
// 让 Conclave 产出能直接被写入文件、运行、查看结果
import { useState, useEffect, useRef, useCallback } from 'react'
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

/** 文件树节点 */
interface TreeNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: TreeNode[]
}

/** 将扁平 FileItem 列表转为树结构（仅一层展开，简化实现） */
function buildTree(items: FileItem[]): TreeNode[] {
  const dirs = items.filter((i) => i.type === 'directory')
  const files = items.filter((i) => i.type === 'file')
  return [...dirs, ...files].map((i) => ({
    name: i.name,
    path: i.path,
    type: i.type as 'file' | 'directory',
  }))
}

export function WorkspacePanel() {
  // 文件树
  const [tree, setTree] = useState<TreeNode[]>([])
  const [currentPath, setCurrentPath] = useState<string>('')
  const [loading, setLoading] = useState(false)

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

  /** 刷新文件列表 */
  const refreshTree = useCallback(async (path = '') => {
    setLoading(true)
    try {
      const res = await listFiles(path)
      setTree(buildTree(res.items))
      setCurrentPath(path)
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: `读取目录失败: ${(e as Error).message}` },
      ])
    } finally {
      setLoading(false)
    }
  }, [])

  /** 打开文件 */
  const openFile = useCallback(async (path: string) => {
    try {
      const res = await readFile(path)
      setFilePath(res.path)
      setFileContent(res.content)
      setFileLang(res.language)
      setDirty(false)
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: `打开文件失败: ${(e as Error).message}` },
      ])
    }
  }, [])

  /** 保存文件 */
  const saveFile = useCallback(async () => {
    if (!filePath) return
    setSaving(true)
    try {
      await writeFile(filePath, fileContent)
      setDirty(false)
      setTerminalHistory((h) => [
        ...h,
        { type: 'out', text: `[已保存] ${filePath} (${fileContent.length} chars)` },
      ])
    } catch (e) {
      setTerminalHistory((h) => [
        ...h,
        { type: 'err', text: `保存失败: ${(e as Error).message}` },
      ])
    } finally {
      setSaving(false)
    }
  }, [filePath, fileContent])

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

  // 初始加载文件树 + 沙箱状态
  useEffect(() => {
    refreshTree('')
    sandboxStatus()
      .then((s) =>
        setSandbox({ active: s.active, image: s.image, mode: s.mode }),
      )
      .catch(() => null)
  }, [refreshTree])

  return (
    <div className="workspace-panel">
      {/* 工具栏 */}
      <div className="ws-toolbar">
        <button
          className="btn btn-sm"
          onClick={() => refreshTree(currentPath)}
          disabled={loading}
        >
          {loading ? '...' : '刷新'}
        </button>
        <button className="btn btn-sm" onClick={newFile}>
          新建
        </button>
        <button
          className="btn btn-sm btn-primary"
          onClick={saveFile}
          disabled={!dirty || saving}
        >
          {saving ? '保存中...' : '保存'}
        </button>
        <button
          className="btn btn-sm"
          onClick={runEditorCode}
          disabled={running || !fileContent.trim()}
        >
          ▶ 运行代码
        </button>
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
              tree.map((node) => (
                <div
                  key={node.path}
                  className={`ws-tree-item ${node.type} ${
                    filePath === node.path ? 'active' : ''
                  }`}
                  onClick={() => {
                    if (node.type === 'file') {
                      openFile(node.path)
                    } else {
                      refreshTree(node.path)
                    }
                  }}
                >
                  <span className="ws-icon">
                    {node.type === 'directory' ? '📁' : '📄'}
                  </span>
                  <span className="ws-name">{node.name}</span>
                </div>
              ))
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
