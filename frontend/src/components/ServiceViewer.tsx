// ServiceViewer - VSCode风格的可部署服务查看器
// 解析 app_code（files dict），提供文件树+标签页+代码高亮
import { useState, useMemo, useCallback } from 'react';

interface FileNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: FileNode[];
  content?: string;
}

interface ServiceViewerProps {
  appCode: Record<string, string> | string;
  title?: string;
  port?: number;
  runCommand?: string;
}

// 从路径列表构建文件树
function buildFileTree(files: Record<string, string>): FileNode[] {
  const root: FileNode[] = [];
  const dirMap = new Map<string, FileNode>();

  // 确保所有目录节点存在
  const ensureDir = (dirPath: string) => {
    if (dirMap.has(dirPath)) return dirMap.get(dirPath)!;
    const parts = dirPath.split('/');
    let parentPath = '';
    for (let i = 0; i < parts.length; i++) {
      const curPath = parts.slice(0, i + 1).join('/');
      if (!dirMap.has(curPath)) {
        const node: FileNode = {
          name: parts[i],
          path: curPath,
          is_dir: true,
          children: [],
        };
        dirMap.set(curPath, node);
        if (i === 0) {
          root.push(node);
        } else {
          const parent = dirMap.get(parentPath)!;
          parent.children!.push(node);
        }
      }
      parentPath = curPath;
    }
    return dirMap.get(dirPath)!;
  };

  // 排序：目录在前，文件在后，字母序
  const sortNodes = (nodes: FileNode[]) => {
    nodes.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    nodes.forEach(n => n.children && sortNodes(n.children));
  };

  Object.entries(files).forEach(([path, content]) => {
    const parts = path.split('/');
    const fileName = parts.pop()!;
    const dirPath = parts.join('/');

    const fileNode: FileNode = {
      name: fileName,
      path,
      is_dir: false,
      content,
    };

    if (dirPath) {
      const dir = ensureDir(dirPath);
      dir.children!.push(fileNode);
    } else {
      root.push(fileNode);
    }
  });

  sortNodes(root);
  return root;
}

// 根据文件扩展名推断语言
function inferLang(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || '';
  const map: Record<string, string> = {
    py: 'python', ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx',
    json: 'json', yaml: 'yaml', yml: 'yaml', md: 'markdown', css: 'css',
    html: 'html', dockerfile: 'dockerfile', sh: 'bash', bash: 'bash',
    sql: 'sql', toml: 'toml', env: 'env', txt: 'text', lock: 'text',
  };
  const base = path.split('/').pop()?.toLowerCase() || '';
  if (base === 'dockerfile') return 'dockerfile';
  if (base.endsWith('dockerfile')) return 'dockerfile';
  return map[ext] || 'text';
}

// 文件图标（简单的基于扩展名的图标色点）
function FileIcon({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  let color = '#a1a1aa';
  if (['py'].includes(ext)) color = '#38bdf8';
  else if (['ts', 'tsx'].includes(ext)) color = '#60a5fa';
  else if (['js', 'jsx'].includes(ext)) color = '#facc15';
  else if (['json', 'yaml', 'yml', 'toml'].includes(ext)) color = '#fbbf24';
  else if (['css'].includes(ext)) color = '#c084fc';
  else if (['md', 'txt'].includes(ext)) color = '#a3e635';
  else if (['html'].includes(ext)) color = '#fb923c';
  else if (name === 'Dockerfile' || name.toLowerCase().includes('dockerfile')) color = '#60a5fa';
  else if (name === 'requirements.txt' || name === 'pyproject.toml' || name === 'package.json') color = '#f472b6';
  else if (name.startsWith('.env')) color = '#a78bfa';

  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.8}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

function FolderIcon({ open }: { open: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d4d4d8" strokeWidth={1.8}>
      {open ? (
        <path d="M6 14l1.5-5h12L18 14H6z M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2" />
      ) : (
        <path d="M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
      )}
    </svg>
  );
}

// 极简语法高亮（基于正则，覆盖Python/TS/TSX/JSON/YAML/Dockerfile/bash的主要token）
function highlightCode(code: string, lang: string): string {
  if (!code) return '';
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Python关键字
  const pyKw = /\b(def|class|import|from|as|return|if|elif|else|for|while|try|except|finally|raise|with|pass|break|continue|yield|lambda|and|or|not|in|is|None|True|False|async|await|self|global|nonlocal|assert|del)\b/g;
  const jsKw = /\b(const|let|var|function|return|if|else|for|while|class|extends|new|this|import|from|export|default|async|await|try|catch|finally|throw|typeof|instanceof|void|null|undefined|true|false|switch|case|break|continue|interface|type|enum|public|private|protected|static|readonly|implements|as)\b/g;
  const kw = lang === 'python' ? pyKw : (lang === 'typescript' || lang === 'tsx' || lang === 'javascript' || lang === 'jsx') ? jsKw : null;

  // 注释
  let html = esc(code);

  // 字符串（先处理，避免内部内容被后续规则匹配）
  html = html.replace(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)/g, '<span class="tok-str">$1</span>');

  // 注释（Python # , TS //, CSS/JS /* */）
  html = html.replace(/(#[^\n]*)/g, '<span class="tok-com">$1</span>');
  html = html.replace(/(\/\/[^\n]*)/g, '<span class="tok-com">$1</span>');

  // 数字
  html = html.replace(/\b(\d+\.?\d*)\b/g, '<span class="tok-num">$1</span>');

  // 关键字
  if (kw) {
    html = html.replace(kw, '<span class="tok-kw">$1</span>');
  }

  // 函数名 def xxx( 或 function xxx(
  html = html.replace(/\b(def|function)\s+([a-zA-Z_][a-zA-Z0-9_]*)/g,
    '<span class="tok-kw">$1</span> <span class="tok-fn">$2</span>');

  // 装饰器 @xxx
  html = html.replace(/^(\s*@[a-zA-Z_][a-zA-Z0-9_.]*)/gm, '<span class="tok-dec">$1</span>');

  return html;
}

// 递归渲染文件树
function FileTree({ nodes, depth, activePath, onSelect, openDirs, toggleDir }: {
  nodes: FileNode[];
  depth: number;
  activePath: string | null;
  onSelect: (node: FileNode) => void;
  openDirs: Set<string>;
  toggleDir: (path: string) => void;
}) {
  return (
    <>
      {nodes.map(node => {
        const isOpen = openDirs.has(node.path);
        return (
          <div key={node.path}>
            <div
              className={node.is_dir ? 'svc-file-item dir' : `svc-file-item ${activePath === node.path ? 'active' : ''}`}
              style={{ paddingLeft: `${8 + depth * 14}px` }}
              onClick={() => node.is_dir ? toggleDir(node.path) : onSelect(node)}
            >
              {node.is_dir ? <FolderIcon open={isOpen} /> : <FileIcon name={node.name} />}
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {node.name}
              </span>
            </div>
            {node.is_dir && isOpen && node.children && (
              <FileTree
                nodes={node.children}
                depth={depth + 1}
                activePath={activePath}
                onSelect={onSelect}
                openDirs={openDirs}
                toggleDir={toggleDir}
              />
            )}
          </div>
        );
      })}
    </>
  );
}

export default function ServiceViewer({ appCode, title = '项目预览', port, runCommand }: ServiceViewerProps) {
  // 解析文件
  const files: Record<string, string> = useMemo(() => {
    if (typeof appCode === 'string') {
      try {
        const parsed = JSON.parse(appCode);
        if (parsed && typeof parsed === 'object') return parsed;
        return { 'main.py': appCode };
      } catch {
        return { 'output.txt': appCode };
      }
    }
    return appCode || {};
  }, [appCode]);

  const tree = useMemo(() => buildFileTree(files), [files]);
  const filePaths = useMemo(() => Object.keys(files), [files]);

  // 默认打开的目录
  const defaultOpenDirs = useMemo(() => {
    const dirs = new Set<string>();
    filePaths.forEach(p => {
      const parts = p.split('/');
      parts.pop();
      let cur = '';
      parts.forEach(part => {
        cur = cur ? cur + '/' + part : part;
        dirs.add(cur);
      });
    });
    return dirs;
  }, [filePaths]);

  const [openDirs, setOpenDirs] = useState<Set<string>>(defaultOpenDirs);
  const [openTabs, setOpenTabs] = useState<string[]>(() => {
    // 默认打开main.py或第一个文件
    const preferred = ['app/main.py', 'main.py', 'README.md'];
    for (const p of preferred) {
      if (files[p]) return [p];
    }
    return filePaths.slice(0, 1);
  });
  const [activeTab, setActiveTab] = useState<string | null>(() => {
    const preferred = ['app/main.py', 'main.py', 'README.md'];
    for (const p of preferred) {
      if (files[p]) return p;
    }
    return filePaths[0] || null;
  });
  const [copied, setCopied] = useState<string | null>(null);

  const toggleDir = useCallback((path: string) => {
    setOpenDirs(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const openFile = useCallback((node: FileNode) => {
    setActiveTab(node.path);
    setOpenTabs(prev => prev.includes(node.path) ? prev : [...prev, node.path]);
  }, []);

  const closeTab = useCallback((path: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setOpenTabs(prev => {
      const next = prev.filter(p => p !== path);
      if (activeTab === path) {
        setActiveTab(next[next.length - 1] || null);
      }
      return next;
    });
  }, [activeTab]);

  const copyFile = useCallback((path: string) => {
    const content = files[path];
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(content).then(() => {
        setCopied(path);
        setTimeout(() => setCopied(null), 2000);
      });
    }
  }, [files]);

  const fileCount = filePaths.length;
  const totalLines = useMemo(() =>
    Object.values(files).reduce((sum, c) => sum + c.split('\n').length, 0)
  , [files]);

  return (
    <div className="svc-viewer">
      {/* 标题栏（仿macOS窗口） */}
      <div className="svc-viewer-header">
        <div className="svc-viewer-title">
          <span className="dot green" />
          <span className="dot yellow" />
          <span className="dot" style={{ background: '#ef4444' }} />
          <span style={{ marginLeft: '8px' }}>{title}</span>
          <span style={{ color: '#71717a' }}>·</span>
          <span>{fileCount} 文件</span>
          <span style={{ color: '#71717a' }}>·</span>
          <span>{totalLines} 行</span>
          {port && (
            <>
              <span style={{ color: '#71717a' }}>·</span>
              <span>:{port}</span>
            </>
          )}
        </div>
        <div className="svc-viewer-actions">
          {activeTab && (
            <button
              className={`sc-code-card-copy ${copied === activeTab ? 'copied' : ''}`}
              onClick={() => copyFile(activeTab)}
            >
              {copied === activeTab ? '已复制' : '复制'}
            </button>
          )}
        </div>
      </div>

      <div className="svc-viewer-body">
        {/* 文件资源管理器 */}
        <div className="svc-file-explorer">
          <div className="svc-file-explorer-title">资源管理器</div>
          <FileTree
            nodes={tree}
            depth={0}
            activePath={activeTab}
            onSelect={openFile}
            openDirs={openDirs}
            toggleDir={toggleDir}
          />
        </div>

        {/* 代码编辑区 */}
        <div className="svc-code-area">
          {/* 标签页 */}
          {openTabs.length > 0 && (
            <div className="svc-code-tabs">
              {openTabs.map(path => (
                <div
                  key={path}
                  className={`svc-code-tab ${activeTab === path ? 'active' : ''}`}
                  onClick={() => setActiveTab(path)}
                >
                  <FileIcon name={path.split('/').pop()!} />
                  <span>{path.split('/').pop()}</span>
                  <span className="svc-code-tab-close" onClick={(e) => closeTab(path, e)}>
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 代码内容 */}
          <div className="svc-code-content">
            {activeTab && files[activeTab] ? (
              <pre>
                <code
                  dangerouslySetInnerHTML={{
                    __html: highlightCode(files[activeTab], inferLang(activeTab))
                  }}
                />
              </pre>
            ) : (
              <div style={{ padding: '40px', textAlign: 'center', color: '#71717a', fontSize: '13px' }}>
                选择文件查看代码
              </div>
            )}
          </div>
        </div>
      </div>

      {runCommand && (
        <div style={{ padding: '8px 16px', background: '#111113', borderTop: '1px solid #27272a', fontFamily: 'var(--mono)', fontSize: '11px', color: '#71717a' }}>
          <span style={{ color: '#22c55e' }}>$</span> {runCommand}
        </div>
      )}
    </div>
  );
}
