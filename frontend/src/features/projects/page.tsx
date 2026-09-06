/**
 * 项目列表页（/projects，ADR-017 Phase 2 前端接线）。
 *
 * 设计要点：
 * - Notion 风软表格：中性灰表头、浅灰行线、中性灰标签（用户偏好）
 * - 列表倒序（最新在上，后端 ORDER BY created_at DESC）
 * - 创建/编辑共用一个 Dialog 表单；slug 前端预校验（与后端 SLUG_PATTERN 一致）
 * - 删除走 ConfirmDialog（议题级联删，破坏性操作显式确认）
 */
import * as React from 'react';
import { useNavigate } from 'react-router';
import { cn, formatRelativeTime } from '@/lib/utils';
import { toast } from '@/hooks/use-toast';
import { useProjects, useDeleteProject } from '@/hooks/use-projects';
import type { Project } from '@/types';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  PlusIcon,
  GitBranchIcon,
  MoreHorizontalIcon,
  EditIcon,
  TrashIcon,
  FolderIcon,
} from '@/components/ui/svg-icons';
import { ProjectFormDialog } from './project-form-dialog';

// ===== 表格行 =====

interface ProjectRowProps {
  project: Project;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

function ProjectRow({ project, onOpen, onEdit, onDelete }: ProjectRowProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      className="flex cursor-pointer items-center gap-4 px-4 py-3 transition-colors hover:bg-bg-secondary"
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      {/* 项目名 + 标识 */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-text-primary">{project.name}</span>
          <Badge variant="outline" className="flex-shrink-0 px-1.5 py-0 text-[10px] font-normal text-text-tertiary">
            {project.slug}
          </Badge>
        </div>
        {project.description && (
          <p className="mt-0.5 truncate text-xs text-text-tertiary">{project.description}</p>
        )}
      </div>

      {/* 仓库 */}
      <div className="hidden w-56 flex-shrink-0 items-center gap-1.5 md:flex">
        {project.repo_url ? (
          <>
            <GitBranchIcon size={13} className="flex-shrink-0 text-text-tertiary" />
            <span className="truncate text-xs text-text-secondary" title={project.repo_url}>
              {project.repo_url.replace(/^https?:\/\//, '')}
            </span>
            <span className="flex-shrink-0 text-[10px] text-text-tertiary">({project.default_branch})</span>
          </>
        ) : (
          <span className="text-xs text-text-tertiary">未绑定仓库</span>
        )}
      </div>

      {/* 议题数 */}
      <div className="w-16 flex-shrink-0 text-center">
        <span className="text-xs text-text-secondary">{project.issue_total ?? 0}</span>
      </div>

      {/* 创建时间 */}
      <div className="hidden w-24 flex-shrink-0 text-xs text-text-tertiary lg:block">
        {project.created_at ? formatRelativeTime(Date.parse(project.created_at)) : '—'}
      </div>

      {/* 行操作：stopPropagation 挂在触发按钮上（菜单内容走 portal，不会冒泡到行） */}
      <div className="flex-shrink-0">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              aria-label="项目操作"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontalIcon size={14} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-32">
            <DropdownMenuItem onClick={onEdit} className="cursor-pointer gap-2 text-xs">
              <EditIcon size={13} />
              编辑
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={onDelete}
              className="cursor-pointer gap-2 text-xs text-danger focus:text-danger"
            >
              <TrashIcon size={13} />
              删除
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

// ===== 空状态 =====

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-bg-tertiary text-text-tertiary">
        <FolderIcon size={22} />
      </div>
      <p className="mb-1 text-sm font-medium text-text-secondary">暂无项目</p>
      <p className="mb-4 text-xs text-text-tertiary">项目是议题池的命名空间，可绑定代码仓库</p>
      <Button variant="outline" size="sm" onClick={onCreate}>
        新建项目
      </Button>
    </div>
  );
}

// ===== 主页面 =====

export default function ProjectsPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useProjects();
  const deleteProject = useDeleteProject();

  const [formOpen, setFormOpen] = React.useState(false);
  const [editingProject, setEditingProject] = React.useState<Project | null>(null);
  const [deletingProject, setDeletingProject] = React.useState<Project | null>(null);

  React.useEffect(() => {
    if (isError && error) {
      toast({
        title: '加载项目列表失败',
        description: error instanceof Error ? error.message : '请稍后重试',
        variant: 'error',
      });
    }
  }, [isError, error]);

  const projects = data?.items ?? [];

  const handleCreate = () => {
    setEditingProject(null);
    setFormOpen(true);
  };

  const handleEdit = (project: Project) => {
    setEditingProject(project);
    setFormOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingProject) return;
    const target = deletingProject;
    setDeletingProject(null);
    try {
      await deleteProject.mutateAsync(target.id);
      toast({ title: '项目已删除', description: target.name });
    } catch (err: unknown) {
      toast({
        title: '删除失败',
        description: err instanceof Error ? err.message : '请稍后重试',
        variant: 'error',
      });
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-8 pb-8 pt-6">
      {/* 页头 */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">项目</h1>
          <p className="mt-1 text-sm text-text-tertiary">项目与议题池：议题入池、排期、发起会议、闭环追溯</p>
        </div>
        <Button size="sm" onClick={handleCreate} className="gap-1">
          <PlusIcon size={13} />
          新建项目
        </Button>
      </div>

      {/* 表格 */}
      <Card className="overflow-hidden">
        {/* 表头（中性灰） */}
        <div className="flex items-center gap-4 border-b border-border-soft bg-bg-secondary/60 px-4 py-2 text-[11px] font-medium text-text-tertiary">
          <span className="flex-1">项目</span>
          <span className="hidden w-56 md:block">仓库</span>
          <span className="w-16 text-center">议题</span>
          <span className="hidden w-24 lg:block">创建时间</span>
          <span className="w-7" />
        </div>

        {isLoading ? (
          <div className="divide-y divide-border-soft">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3.5">
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-4 w-2/5 rounded" />
                  <Skeleton className="h-3 w-3/5 rounded" />
                </div>
                <Skeleton className="hidden h-3 w-40 rounded md:block" />
                <Skeleton className="h-3 w-8 rounded" />
              </div>
            ))}
          </div>
        ) : projects.length === 0 ? (
          <EmptyState onCreate={handleCreate} />
        ) : (
          <div className="divide-y divide-border-soft">
            {projects.map((project) => (
              <ProjectRow
                key={project.id}
                project={project}
                onOpen={() => navigate(`/projects/${project.id}`)}
                onEdit={() => handleEdit(project)}
                onDelete={() => setDeletingProject(project)}
              />
            ))}
          </div>
        )}
      </Card>

      <p className={cn('mt-3 text-[11px] text-text-tertiary', projects.length === 0 && 'hidden')}>
        共 {data?.total ?? 0} 个项目 · 点击进入议题池
      </p>

      {/* 创建/编辑 Dialog */}
      <ProjectFormDialog open={formOpen} onOpenChange={setFormOpen} project={editingProject} />

      {/* 删除确认 */}
      <ConfirmDialog
        open={deletingProject !== null}
        title="删除项目"
        description={`「${deletingProject?.name ?? ''}」下的所有议题将一并删除，会议与产物的项目关联将解除。此操作不可恢复。`}
        confirmText="删除"
        destructive
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeletingProject(null)}
      />
    </div>
  );
}
