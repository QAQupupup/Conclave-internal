/**
 * WorkspacePanel 组件单元测试
 *
 * 测试目标：
 *  - 工具栏按钮渲染（刷新/新建/保存/运行代码）
 *  - 文件树懒加载 + 递归展开
 *  - 代码编辑器打开/编辑/保存
 *  - 终端命令执行 + 输出
 *  - 沙箱状态徽章
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'

// ---------- Mock Monaco Editor ----------
vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange, language }: { value: string; onChange?: (v: string) => void; language: string }) => (
    <textarea
      data-testid="monaco-editor"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      data-language={language}
    />
  ),
}))

// ---------- Mock API ----------
const mockListFiles = vi.fn()
const mockReadFile = vi.fn()
const mockWriteFile = vi.fn()
const mockExecCommand = vi.fn()
const mockRunCode = vi.fn()
const mockSandboxStatus = vi.fn()

vi.mock('../lib/api.ts', async () => {
  const actual = await vi.importActual<typeof import('../lib/api.ts')>('../lib/api.ts')
  return {
    ...actual,
    listFiles: (...args: Parameters<typeof actual.listFiles>) => mockListFiles(...args),
    readFile: (...args: Parameters<typeof actual.readFile>) => mockReadFile(...args),
    writeFile: (...args: Parameters<typeof actual.writeFile>) => mockWriteFile(...args),
    execCommand: (...args: Parameters<typeof actual.execCommand>) => mockExecCommand(...args),
    runCode: (...args: Parameters<typeof actual.runCode>) => mockRunCode(...args),
    sandboxStatus: (...args: Parameters<typeof actual.sandboxStatus>) => mockSandboxStatus(...args),
  }
})

import { WorkspacePanel } from '../components/WorkspacePanel.tsx'

// ---------- 工厂函数 ----------
function makeFile(name: string, path: string): any {
  return { name, path, type: 'file', size: 100, modified: 0 }
}

function makeDir(name: string, path: string, childCount = 0): any {
  return { name, path, type: 'directory', size: 0, modified: 0, child_count: childCount }
}

function makeListResponse(items: any[]) {
  return { path: '', type: 'directory', items }
}

function renderPanel(props: { meetingId?: string; initialFile?: string } = {}) {
  return render(<WorkspacePanel meetingId={props.meetingId} initialFile={props.initialFile} />)
}

// ---------- 测试 ----------
describe('WorkspacePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认 mock 返回值
    mockListFiles.mockResolvedValue(makeListResponse([]))
    mockSandboxStatus.mockResolvedValue({
      mode: 'docker',
      docker_available: true,
      image: 'python:3.12-slim',
      mem_limit: '512m',
      cpu_limit: '1.0',
      active: true,
    })
  })

  describe('工具栏渲染', () => {
    it('渲染刷新/新建/保存/运行代码按钮', async () => {
      renderPanel()
      expect(screen.getByText('刷新')).toBeTruthy()
      expect(screen.getByText('新建')).toBeTruthy()
      expect(screen.getByText('保存')).toBeTruthy()
      expect(screen.getByText('运行代码')).toBeTruthy()
    })

    it('保存按钮初始禁用', async () => {
      renderPanel()
      const saveBtn = screen.getByText('保存').closest('button')!
      expect(saveBtn.disabled).toBe(true)
    })

    it('运行代码按钮在无内容时禁用', async () => {
      renderPanel()
      const runBtn = screen.getByText('运行代码').closest('button')!
      expect(runBtn.disabled).toBe(true)
    })
  })

  describe('文件树', () => {
    it('mount 时调用 listFiles 加载根目录', async () => {
      renderPanel()
      await waitFor(() => {
        expect(mockListFiles).toHaveBeenCalledWith('')
      })
    })

    it('显示文件列表中的文件名', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([
        makeFile('main.py', 'main.py'),
        makeFile('utils.py', 'utils.py'),
      ]))
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('main.py')).toBeTruthy()
        expect(screen.getByText('utils.py')).toBeTruthy()
      })
    })

    it('空目录显示提示', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([]))
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('空目录')).toBeTruthy()
      })
    })

    it('点击文件调用 readFile 打开', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([
        makeFile('main.py', 'main.py'),
      ]))
      mockReadFile.mockResolvedValue({
        path: 'main.py',
        content: 'print("hello")',
        size: 14,
        language: 'python',
      })
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('main.py')).toBeTruthy()
      })
      fireEvent.click(screen.getByText('main.py'))
      await waitFor(() => {
        expect(mockReadFile).toHaveBeenCalledWith('main.py')
      })
      await waitFor(() => {
        const editor = screen.getByTestId('monaco-editor') as HTMLTextAreaElement
        expect(editor.value).toBe('print("hello")')
      })
    })

    it('点击目录调用 listFiles 加载子节点', async () => {
      mockListFiles.mockResolvedValueOnce(makeListResponse([
        makeDir('src', 'src', 2),
      ]))
      mockListFiles.mockResolvedValueOnce(makeListResponse([
        makeFile('app.py', 'src/app.py'),
        makeFile('config.py', 'src/config.py'),
      ]))
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('src')).toBeTruthy()
      })
      // 点击目录展开
      fireEvent.click(screen.getByText('src'))
      await waitFor(() => {
        expect(mockListFiles).toHaveBeenCalledWith('src')
      })
      await waitFor(() => {
        expect(screen.getByText('app.py')).toBeTruthy()
        expect(screen.getByText('config.py')).toBeTruthy()
      })
    })

    it('再次点击已展开目录时收起', async () => {
      // mount 调用返回目录列表
      mockListFiles.mockResolvedValueOnce(makeListResponse([
        makeDir('src', 'src', 1),
      ]))
      // 展开时调用返回子文件
      mockListFiles.mockResolvedValueOnce(makeListResponse([
        makeFile('app.py', 'src/app.py'),
      ]))
      // 后续调用默认返回空（收起不触发 API）
      mockListFiles.mockResolvedValue(makeListResponse([]))
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('src')).toBeTruthy()
      })
      // 第一次点击：展开
      fireEvent.click(screen.getByText('src'))
      await waitFor(() => {
        expect(screen.getByText('app.py')).toBeTruthy()
      })
      // 第二次点击：收起（不触发 API，仅切换 expanded 状态）
      fireEvent.click(screen.getByText('src'))
      await waitFor(() => {
        expect(screen.queryByText('app.py')).toBeNull()
      })
    })
  })

  describe('代码编辑器', () => {
    it('编辑内容后保存按钮可用', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([
        makeFile('main.py', 'main.py'),
      ]))
      mockReadFile.mockResolvedValue({
        path: 'main.py',
        content: 'original',
        size: 8,
        language: 'python',
      })
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('main.py')).toBeTruthy()
      })
      fireEvent.click(screen.getByText('main.py'))
      await waitFor(() => {
        const editor = screen.getByTestId('monaco-editor') as HTMLTextAreaElement
        expect(editor.value).toBe('original')
      })
      // 编辑内容
      const editor = screen.getByTestId('monaco-editor')
      fireEvent.change(editor, { target: { value: 'modified' } })
      // 保存按钮应变为可用
      await waitFor(() => {
        const saveBtn = screen.getByText('保存').closest('button')!
        expect(saveBtn.disabled).toBe(false)
      })
    })

    it('点击保存调用 writeFile', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([
        makeFile('main.py', 'main.py'),
      ]))
      mockReadFile.mockResolvedValue({
        path: 'main.py',
        content: 'original',
        size: 8,
        language: 'python',
      })
      mockWriteFile.mockResolvedValue({ path: 'main.py', size: 8, saved: true })
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('main.py')).toBeTruthy()
      })
      fireEvent.click(screen.getByText('main.py'))
      await waitFor(() => {
        expect(screen.getByTestId('monaco-editor')).toBeTruthy()
      })
      // 编辑 + 保存
      fireEvent.change(screen.getByTestId('monaco-editor'), { target: { value: 'new content' } })
      fireEvent.click(screen.getByText('保存'))
      await waitFor(() => {
        expect(mockWriteFile).toHaveBeenCalledWith('main.py', 'new content')
      })
    })

    it('新建按钮清空编辑器', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([
        makeFile('main.py', 'main.py'),
      ]))
      mockReadFile.mockResolvedValue({
        path: 'main.py',
        content: 'print("hello")',
        size: 14,
        language: 'python',
      })
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('main.py')).toBeTruthy()
      })
      fireEvent.click(screen.getByText('main.py'))
      await waitFor(() => {
        const editor = screen.getByTestId('monaco-editor') as HTMLTextAreaElement
        expect(editor.value).toBe('print("hello")')
      })
      // 点击新建
      fireEvent.click(screen.getByText('新建'))
      const editor = screen.getByTestId('monaco-editor') as HTMLTextAreaElement
      expect(editor.value).toBe('')
    })
  })

  describe('终端', () => {
    it('输入命令 + Enter 调用 execCommand', async () => {
      mockExecCommand.mockResolvedValue({
        command: 'ls',
        exit_code: 0,
        stdout: 'file1.py\nfile2.py',
        stderr: '',
        sandboxed: true,
        image: 'python:3.12-slim',
        fallback_reason: '',
        duration_hint: '0.5s',
      })
      renderPanel()
      await waitFor(() => {
        expect(mockListFiles).toHaveBeenCalled()
      })
      const input = screen.getByPlaceholderText('$ 输入命令...') as HTMLInputElement
      fireEvent.change(input, { target: { value: 'ls' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await waitFor(() => {
        expect(mockExecCommand).toHaveBeenCalledWith('ls')
      })
      // stdout 应出现在终端（在 <pre> 内）
      await waitFor(() => {
        const terminal = document.querySelector('.ws-terminal-output')
        expect(terminal?.textContent).toContain('file1.py')
        expect(terminal?.textContent).toContain('file2.py')
      })
    })

    it('execCommand 抛错时终端显示错误', async () => {
      mockExecCommand.mockRejectedValue(new Error('连接失败'))
      renderPanel()
      await waitFor(() => {
        expect(mockListFiles).toHaveBeenCalled()
      })
      const input = screen.getByPlaceholderText('$ 输入命令...') as HTMLInputElement
      fireEvent.change(input, { target: { value: 'ls' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await waitFor(() => {
        expect(mockExecCommand).toHaveBeenCalled()
      })
      await waitFor(() => {
        expect(screen.getByText('连接失败')).toBeTruthy()
      })
    })

    it('点击运行代码调用 runCode', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([
        makeFile('main.py', 'main.py'),
      ]))
      mockReadFile.mockResolvedValue({
        path: 'main.py',
        content: 'print("hello")',
        size: 14,
        language: 'python',
      })
      mockRunCode.mockResolvedValue({
        language: 'python',
        exit_code: 0,
        stdout: 'hello',
        stderr: '',
        sandboxed: true,
        image: 'python:3.12-slim',
        fallback_reason: '',
        duration_hint: '0.3s',
      })
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText('main.py')).toBeTruthy()
      })
      // 打开文件
      fireEvent.click(screen.getByText('main.py'))
      await waitFor(() => {
        expect(screen.getByTestId('monaco-editor')).toBeTruthy()
      })
      // 点击运行代码
      fireEvent.click(screen.getByText('运行代码'))
      await waitFor(() => {
        expect(mockRunCode).toHaveBeenCalledWith('print("hello")', 'python')
      })
      await waitFor(() => {
        const terminal = document.querySelector('.ws-terminal-output')
        expect(terminal?.textContent).toContain('hello')
      })
    })

    it('命令执行中输入框禁用', async () => {
      // 用一个永不 resolve 的 promise 模拟长时间执行
      mockExecCommand.mockReturnValue(new Promise(() => {}))
      renderPanel()
      await waitFor(() => {
        expect(mockListFiles).toHaveBeenCalled()
      })
      const input = screen.getByPlaceholderText('$ 输入命令...') as HTMLInputElement
      fireEvent.change(input, { target: { value: 'sleep 10' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await waitFor(() => {
        expect(input.disabled).toBe(true)
      })
    })
  })

  describe('沙箱状态', () => {
    it('mount 时调用 sandboxStatus', async () => {
      renderPanel()
      await waitFor(() => {
        expect(mockSandboxStatus).toHaveBeenCalled()
      })
    })

    it('沙箱激活时显示容器隔离徽章', async () => {
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText(/🛡 容器隔离/)).toBeTruthy()
      })
    })

    it('沙箱未激活时显示宿主机直连', async () => {
      mockSandboxStatus.mockResolvedValue({
        mode: 'host',
        docker_available: false,
        image: '',
        mem_limit: '',
        cpu_limit: '',
        active: false,
      })
      renderPanel()
      await waitFor(() => {
        expect(screen.getByText(/⚠ 宿主机直连/)).toBeTruthy()
      })
    })
  })

  describe('meetingId 隔离', () => {
    it('有 meetingId 时 listFiles 带前缀', async () => {
      renderPanel({ meetingId: 'm1' })
      await waitFor(() => {
        expect(mockListFiles).toHaveBeenCalledWith('m1/')
      })
    })

    it('打开文件时 readFile 带前缀', async () => {
      mockListFiles.mockResolvedValue(makeListResponse([
        makeFile('main.py', 'm1/main.py'),
      ]))
      mockReadFile.mockResolvedValue({
        path: 'm1/main.py',
        content: 'code',
        size: 4,
        language: 'python',
      })
      renderPanel({ meetingId: 'm1' })
      await waitFor(() => {
        expect(screen.getByText('main.py')).toBeTruthy()
      })
      fireEvent.click(screen.getByText('main.py'))
      await waitFor(() => {
        expect(mockReadFile).toHaveBeenCalledWith('m1/main.py')
      })
    })
  })
})
