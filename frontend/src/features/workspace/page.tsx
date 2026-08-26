import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from '@/components/ui/dialog';
import {
  FolderIcon,
  FileIcon,
  PlusIcon,
  UploadIcon,
  TrashIcon,
  ChevronRightIcon,
  ChevronLeftIcon,
  SpinnerIcon,
} from '@/components/ui/svg-icons';
import { api } from '@/lib/api';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';

// ===== Types =====
interface FileItem {
  name: string;
  display_name?: string;
  type: 'file' | 'directory';
  size?: number;
  modified?: string | number;
  children_count?: number;
  child_count?: number;
}

interface FileListResponse {
  path: string;
  items: FileItem[];
}

interface FileContentResponse {
  path: string;
  content: string;
  language?: string;
  truncated?: boolean;
}

interface WorkspaceInfo {
  root_path: string;
  timeout?: number;
  python_version?: string;
  sandbox_status?: string;
}

// ===== Utility functions =====
function formatFileSize(bytes?: number): string {
  if (bytes == null) return '--';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateVal?: string | number): string {
  if (!dateVal) return '--';
  try {
    let d: Date;
    if (typeof dateVal === 'number') {
      // 后端返回 ISO 字符串，兼容旧版秒级时间戳
      d = dateVal < 1e12 ? new Date(dateVal * 1000) : new Date(dateVal);
    } else {
      // 纯数字字符串（秒级时间戳）
      if (/^\d+(\.\d+)?$/.test(dateVal)) {
        const n = Number(dateVal);
        d = n < 1e12 ? new Date(n * 1000) : new Date(n);
      } else {
        d = new Date(dateVal);
      }
    }
    if (isNaN(d.getTime())) return '--';
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch {
    return '--';
  }
}

function normalizePath(rawPath: string | null): string {
  if (!rawPath || rawPath === '/') return '';
  // Ensure leading slash, remove trailing slash
  let p = rawPath;
  if (!p.startsWith('/')) p = '/' + p;
  if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1);
  return p;
}

function joinPath(base: string, name: string): string {
  if (!base) return '/' + name;
  return base + '/' + name;
}

function getParentPath(path: string): string {
  if (!path || path === '/') return '';
  const idx = path.lastIndexOf('/');
  if (idx <= 0) return '';
  return path.slice(0, idx);
}

function getPathSegments(path: string): Array<{ name: string; path: string }> {
  const segments: Array<{ name: string; path: string }> = [{ name: '根目录', path: '' }];
  if (!path) return segments;
  const parts = path.split('/').filter(Boolean);
  let current = '';
  for (const part of parts) {
    current = current ? current + '/' + part : '/' + part;
    segments.push({ name: part, path: current });
  }
  return segments;
}

// ===== API helpers =====
function filesQueryKey(path: string) {
  return ['workspace', 'files', path];
}

function fileContentQueryKey(filePath: string) {
  return ['workspace', 'file-content', filePath];
}

function workspaceInfoKey() {
  return ['workspace', 'info'];
}

// ===== Main Component =====
export default function WorkspacePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const currentPath = normalizePath(searchParams.get('path'));
  const [selectedFile, setSelectedFile] = React.useState<string | null>(null);

  // Dialog states
  const [newDialogOpen, setNewDialogOpen] = React.useState(false);
  const [newDialogType, setNewDialogType] = React.useState<'file' | 'directory'>('file');
  const [newName, setNewName] = React.useState('');
  const [newContent, setNewContent] = React.useState('');

  const [deleteDialogOpen, setDeleteDialogOpen] = React.useState(false);
  const [deleteTarget, setDeleteTarget] = React.useState<{ name: string; path: string; type: string } | null>(null);
  const [deleteCascade, setDeleteCascade] = React.useState(true);

  const uploadInputRef = React.useRef<HTMLInputElement>(null);

  // Navigate helper
  const navigateTo = React.useCallback(
    (path: string) => {
      setSelectedFile(null);
      if (path) {
        setSearchParams({ path });
      } else {
        setSearchParams({});
      }
    },
    [setSearchParams]
  );

  // ===== Queries =====
  const {
    data: fileList,
    isLoading: listLoading,
    error: listError,
  } = useQuery<FileListResponse>({
    queryKey: filesQueryKey(currentPath),
    queryFn: () => {
      const encoded = encodeURIComponent(currentPath || '/');
      return api.get<FileListResponse>(`/workspace/files?path=${encoded}`);
    },
  });

  const { data: workspaceInfo } = useQuery<WorkspaceInfo>({
    queryKey: workspaceInfoKey(),
    queryFn: () => api.get<WorkspaceInfo>('/workspace/info'),
  });

  const {
    data: fileContent,
    isLoading: contentLoading,
    error: contentError,
  } = useQuery<FileContentResponse>({
    queryKey: fileContentQueryKey(selectedFile || ''),
    queryFn: () => {
      const encoded = encodeURIComponent(selectedFile || '');
      return api.get<FileContentResponse>(`/workspace/files/${encoded}`);
    },
    enabled: !!selectedFile,
  });

  // ===== Mutations =====
  const createMutation = useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      api.post('/workspace/files', { path, content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', 'files'] });
      toast({ title: '创建成功', description: newName });
      setNewDialogOpen(false);
      setNewName('');
      setNewContent('');
    },
    onError: (err: Error) => {
      toast({ title: '创建失败', description: err.message, variant: 'error' });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ filePath, cascade }: { filePath: string; cascade: boolean }) => {
      const encoded = encodeURIComponent(filePath);
      return api.delete(`/workspace/files/${encoded}`, { cascade });
    },
    onSuccess: (_data, _variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', 'files'] });
      if (selectedFile === deleteTarget?.path) {
        setSelectedFile(null);
      }
      toast({ title: '删除成功', description: deleteTarget?.name });
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
    },
    onError: (err: Error) => {
      toast({
        title: '删除失败',
        description: err.message || '未知错误',
        variant: 'error',
      });
    },
  });

  // ===== Handlers =====
  const handleItemClick = (item: FileItem) => {
    const fullPath = joinPath(currentPath, item.name);
    if (item.type === 'directory') {
      navigateTo(fullPath);
    } else {
      setSelectedFile(fullPath);
    }
  };

  const handleCreate = () => {
    if (!newName.trim()) {
      toast({ title: '请输入名称', variant: 'error' });
      return;
    }
    const fullPath = joinPath(currentPath, newName.trim());
    const content = newDialogType === 'file' ? newContent : '';
    createMutation.mutate({ path: fullPath, content });
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate({ filePath: deleteTarget.path, cascade: deleteTarget.type === 'directory' ? deleteCascade : false });
  };

  const handleUploadClick = () => {
    uploadInputRef.current?.click();
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    for (const file of Array.from(files)) {
      try {
        const text = await file.text();
        const fullPath = joinPath(currentPath, file.name);
        await api.post('/workspace/files', { path: fullPath, content: text });
        toast({ title: '上传成功', description: file.name });
      } catch (err) {
        toast({
          title: '上传失败',
          description: `${file.name}: ${err instanceof Error ? err.message : '未知错误'}`,
          variant: 'error',
        });
      }
    }

    queryClient.invalidateQueries({ queryKey: ['workspace', 'files'] });
    // Reset input
    if (uploadInputRef.current) uploadInputRef.current.value = '';
  };

  const openNewFileDialog = () => {
    setNewDialogType('file');
    setNewName('');
    setNewContent('');
    setNewDialogOpen(true);
  };

  const openNewFolderDialog = () => {
    setNewDialogType('directory');
    setNewName('');
    setNewContent('');
    setNewDialogOpen(true);
  };

  const confirmDelete = (item: FileItem) => {
    setDeleteTarget({
      name: item.name,
      path: joinPath(currentPath, item.name),
      type: item.type,
    });
    // 目录默认勾选级联删除，文件不需要
    setDeleteCascade(item.type === 'directory');
    setDeleteDialogOpen(true);
  };

  // Sort items: directories first, then files, both alphabetically
  const sortedItems = React.useMemo(() => {
    if (!fileList?.items) return [];
    return [...fileList.items].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'directory' ? -1 : 1;
      return a.name.localeCompare(b.name, 'zh');
    });
  }, [fileList]);

  const breadcrumbs = getPathSegments(currentPath);

  return (
    <div className="flex h-full flex-col pt-6 px-8 pb-8">
      {/* Header with breadcrumb */}
      <div className="mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-text-primary">沙箱工作区</h1>
            {workspaceInfo?.sandbox_status && (
              <span className="rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-medium text-success">
                {workspaceInfo.sandbox_status}
              </span>
            )}
          </div>
          {workspaceInfo?.python_version && (
            <span className="text-xs text-text-tertiary">Python {workspaceInfo.python_version}</span>
          )}
        </div>

        {/* Breadcrumb */}
        <nav className="mt-2 flex items-center gap-1 text-sm">
          {breadcrumbs.map((seg, idx) => (
            <React.Fragment key={seg.path}>
              {idx > 0 && (
                <ChevronRightIcon size={14} className="text-text-tertiary" />
              )}
              <button
                onClick={() => navigateTo(seg.path)}
                className={cn(
                  'rounded px-1.5 py-0.5 transition-colors hover:bg-bg-tertiary',
                  idx === breadcrumbs.length - 1
                    ? 'font-medium text-text-primary'
                    : 'text-text-secondary hover:text-text-primary'
                )}
              >
                {seg.name}
              </button>
            </React.Fragment>
          ))}
        </nav>
      </div>

      {/* Toolbar */}
      <div className="mb-3 flex items-center justify-between rounded-lg border border-border-default bg-bg-elevated px-3 py-2">
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={openNewFileDialog}>
            <PlusIcon size={14} />
            <FileIcon size={14} />
            新建文件
          </Button>
          <Button size="sm" variant="outline" onClick={openNewFolderDialog}>
            <PlusIcon size={14} />
            <FolderIcon size={14} />
            新建文件夹
          </Button>
          <Button size="sm" variant="outline" onClick={handleUploadClick}>
            <UploadIcon size={14} />
            上传
          </Button>
          <input
            ref={uploadInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFileUpload}
          />
        </div>
        <div className="flex items-center gap-2">
          {currentPath && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => navigateTo(getParentPath(currentPath))}
            >
              <ChevronLeftIcon size={14} />
              返回上级
            </Button>
          )}
          <span className="font-mono text-xs text-text-tertiary">
            {currentPath || '/'}
          </span>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex flex-1 flex-col gap-3 overflow-hidden">
        {/* File listing */}
        <Card className="flex-shrink-0">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              文件列表
              {sortedItems.length > 0 && (
                <span className="ml-2 text-xs font-normal text-text-tertiary">
                  {sortedItems.length} 项
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {listLoading ? (
              <div className="flex items-center justify-center py-12">
                <SpinnerIcon size={20} className="animate-spin text-brand-500" />
                <span className="ml-2 text-sm text-text-secondary">加载中...</span>
              </div>
            ) : listError ? (
              <div className="py-12 text-center">
                <p className="text-sm text-danger">加载失败: {(listError as Error).message}</p>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-2"
                  onClick={() => queryClient.invalidateQueries({ queryKey: filesQueryKey(currentPath) })}
                >
                  重试
                </Button>
              </div>
            ) : sortedItems.length === 0 ? (
              <div className="py-12 text-center">
                <FolderIcon size={32} className="mx-auto text-text-tertiary/50" />
                <p className="mt-2 text-sm text-text-tertiary">此目录为空</p>
                <p className="mt-1 text-xs text-text-tertiary">使用上方按钮创建文件或文件夹</p>
              </div>
            ) : (
              <ScrollArea className="max-h-[400px]">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border-soft text-left text-xs text-text-tertiary">
                      <th className="px-4 py-2 font-medium">名称</th>
                      <th className="px-4 py-2 font-medium w-24">大小</th>
                      <th className="px-4 py-2 font-medium w-36">修改时间</th>
                      <th className="px-4 py-2 font-medium w-16 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedItems.map((item) => {
                      const fullPath = joinPath(currentPath, item.name);
                      const isSelected = selectedFile === fullPath;
                      return (
                        <tr
                          key={item.name}
                          className={cn(
                            'border-b border-border-soft/50 transition-colors cursor-pointer',
                            isSelected
                              ? 'bg-brand-500/5'
                              : 'hover:bg-bg-tertiary/50'
                          )}
                          onClick={() => handleItemClick(item)}
                        >
                          <td className="px-4 py-2">
                            <div className="flex items-center gap-2">
                              {item.type === 'directory' ? (
                                <FolderIcon size={16} className="text-warning" />
                              ) : (
                                <FileIcon size={16} className="text-text-tertiary" />
                              )}
                              <span
                                className="text-sm text-text-primary truncate max-w-[300px]"
                                title={item.display_name ? `${item.display_name} (${item.name})` : item.name}
                              >
                                {item.display_name || item.name}
                              </span>
                              {item.display_name && (
                                <span className="font-mono text-[10px] text-text-tertiary hidden lg:inline">
                                  {item.name.slice(0, 12)}…
                                </span>
                              )}
                              {(item.children_count ?? item.child_count) != null && (
                                <span className="text-[11px] text-text-tertiary">
                                  ({item.children_count ?? item.child_count})
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-2 text-xs text-text-tertiary">
                            {item.type === 'directory' ? '--' : formatFileSize(item.size)}
                          </td>
                          <td className="px-4 py-2 text-xs text-text-tertiary">
                            {formatDate(item.modified)}
                          </td>
                          <td className="px-4 py-2 text-right">
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-7 w-7 text-text-tertiary hover:text-danger hover:bg-danger/10"
                              onClick={(e) => {
                                e.stopPropagation();
                                confirmDelete(item);
                              }}
                            >
                              <TrashIcon size={14} />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </ScrollArea>
            )}
          </CardContent>
        </Card>

        {/* File preview */}
        {selectedFile && (
          <Card className="min-h-0 flex-1">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <div className="flex items-center gap-2">
                <FileIcon size={16} className="text-text-tertiary" />
                <CardTitle className="text-sm font-mono">{selectedFile}</CardTitle>
                {fileContent?.language && (
                  <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] text-text-tertiary">
                    {fileContent.language}
                  </span>
                )}
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelectedFile(null)}
              >
                关闭预览
              </Button>
            </CardHeader>
            <CardContent>
              {contentLoading ? (
                <div className="flex items-center justify-center py-8">
                  <SpinnerIcon size={16} className="animate-spin text-brand-500" />
                  <span className="ml-2 text-sm text-text-secondary">读取文件中...</span>
                </div>
              ) : contentError ? (
                <p className="py-4 text-center text-sm text-danger">
                  读取失败: {(contentError as Error).message}
                </p>
              ) : fileContent ? (
                <div className="relative">
                  {fileContent.truncated && (
                    <p className="mb-2 text-xs text-warning">
                      文件过大，内容已截断显示
                    </p>
                  )}
                  <ScrollArea className="max-h-96 rounded bg-bg-tertiary">
                    <pre className="p-3 font-mono text-xs leading-relaxed text-text-primary overflow-auto">
                      {fileContent.content.split('\n').map((line, i) => (
                        <div key={i} className="flex">
                          <span className="mr-4 inline-block w-8 flex-shrink-0 select-none text-right text-text-tertiary/50">
                            {i + 1}
                          </span>
                          <span className="whitespace-pre-wrap break-all">{line}</span>
                        </div>
                      ))}
                    </pre>
                  </ScrollArea>
                </div>
              ) : null}
            </CardContent>
          </Card>
        )}
      </div>

      {/* ===== New File/Folder Dialog ===== */}
      <Dialog open={newDialogOpen} onOpenChange={setNewDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {newDialogType === 'file' ? '新建文件' : '新建文件夹'}
            </DialogTitle>
            <DialogDescription>
              在 {currentPath || '/'} 下创建{newDialogType === 'file' ? '文件' : '文件夹'}
            </DialogDescription>
          </DialogHeader>
          <div className="px-6 py-5 space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="new-entity-name" className="block text-sm font-medium text-text-secondary">
                名称
              </label>
              <Input
                id="new-entity-name"
                className="h-9 text-sm"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={newDialogType === 'file' ? 'example.txt' : 'new-folder'}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newDialogType === 'directory') handleCreate();
                }}
              />
            </div>
            {newDialogType === 'file' && (
              <div className="space-y-1.5">
                <label htmlFor="new-file-content" className="block text-sm font-medium text-text-secondary">
                  内容（可选）
                </label>
                <Textarea
                  id="new-file-content"
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                  placeholder="输入文件初始内容..."
                  className="min-h-[120px] border-border-default bg-bg-primary font-mono text-xs text-text-primary placeholder:text-text-tertiary focus-visible:border-brand-500/50 focus-visible:ring-2 focus-visible:ring-brand-500/10"
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">取消</Button>
            </DialogClose>
            <Button
              size="sm"
              onClick={handleCreate}
              disabled={createMutation.isPending || !newName.trim()}
            >
              {createMutation.isPending && (
                <SpinnerIcon size={14} className="animate-spin" />
              )}
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ===== Delete Confirmation Dialog ===== */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription asChild>
              <div>
                <p>
                  确定要删除 {deleteTarget?.type === 'directory' ? '文件夹' : '文件'}{' '}
                  <span className="font-mono font-medium text-text-primary">{deleteTarget?.name}</span> 吗？
                </p>
                {deleteTarget?.type === 'directory' && (
                  <label className="mt-3 flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={deleteCascade}
                      onChange={(e) => setDeleteCascade(e.target.checked)}
                      className="h-4 w-4 rounded border-border-default text-brand-600 focus:ring-brand-500"
                    />
                    <span className="text-sm text-text-secondary">
                      级联删除（删除文件夹及其所有子文件和子文件夹）
                    </span>
                  </label>
                )}
                {deleteTarget?.type === 'directory' && !deleteCascade && (
                  <p className="mt-1 text-xs text-warning">
                    未勾选级联删除时，只能删除空文件夹。
                  </p>
                )}
                <p className="mt-2 text-xs text-text-tertiary">此操作不可撤销。</p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">取消</Button>
            </DialogClose>
            <Button
              size="sm"
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && (
                <SpinnerIcon size={14} className="animate-spin" />
              )}
              <TrashIcon size={14} />
              删除{deleteTarget?.type === 'directory' && deleteCascade ? '（含子内容）' : ''}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
