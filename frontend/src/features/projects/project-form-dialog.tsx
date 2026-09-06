/**
 * 项目创建/编辑 Dialog（列表页与详情页共用）。
 *
 * - 创建模式：project=null，空表单
 * - 编辑模式：回填项目字段，只更新传入项
 * - slug 前端预校验与后端 SLUG_PATTERN 一致，减少 422 往返
 */
import * as React from 'react';
import { toast } from '@/hooks/use-toast';
import { useCreateProject, useUpdateProject } from '@/hooks/use-projects';
import type { Project } from '@/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FieldError } from '@/components/ui/form-feedback';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';

/** slug 规范（与后端 schemas/project.py SLUG_PATTERN 一致） */
export const SLUG_PATTERN = /^[a-z0-9][a-z0-9_-]{0,99}$/;

interface ProjectFormState {
  slug: string;
  name: string;
  repo_url: string;
  default_branch: string;
  description: string;
}

const EMPTY_FORM: ProjectFormState = {
  slug: '',
  name: '',
  repo_url: '',
  default_branch: 'main',
  description: '',
};

function projectToForm(p: Project): ProjectFormState {
  return {
    slug: p.slug,
    name: p.name,
    repo_url: p.repo_url ?? '',
    default_branch: p.default_branch,
    description: p.description ?? '',
  };
}

interface ProjectFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null → 创建模式；否则编辑该项目 */
  project: Project | null;
}

export function ProjectFormDialog({ open, onOpenChange, project }: ProjectFormDialogProps) {
  const [form, setForm] = React.useState<ProjectFormState>(EMPTY_FORM);
  const [errors, setErrors] = React.useState<{ slug?: string; name?: string }>({});
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const isEdit = project !== null;
  const submitting = createProject.isPending || updateProject.isPending;

  // 打开时初始化表单（创建 → 空表单；编辑 → 回填）
  React.useEffect(() => {
    if (open) {
      setForm(project ? projectToForm(project) : EMPTY_FORM);
      setErrors({});
    }
  }, [open, project]);

  const setField = (key: keyof ProjectFormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (key === 'slug' && errors.slug) setErrors((e) => ({ ...e, slug: undefined }));
    if (key === 'name' && errors.name) setErrors((e) => ({ ...e, name: undefined }));
  };

  const validate = (): boolean => {
    const next: { slug?: string; name?: string } = {};
    if (!form.slug.trim()) next.slug = '请输入项目标识';
    else if (!SLUG_PATTERN.test(form.slug.trim())) {
      next.slug = '标识仅支持小写字母、数字、- 和 _，且以字母或数字开头';
    }
    if (!form.name.trim()) next.name = '请输入项目名称';
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async () => {
    if (submitting || !validate()) return;
    const payload = {
      slug: form.slug.trim(),
      name: form.name.trim(),
      repo_url: form.repo_url.trim() || null,
      default_branch: form.default_branch.trim() || 'main',
      description: form.description.trim() || null,
    };
    try {
      if (isEdit && project) {
        await updateProject.mutateAsync({ id: project.id, data: payload });
        toast({ title: '项目已更新', description: payload.name });
      } else {
        await createProject.mutateAsync(payload);
        toast({ title: '项目已创建', description: payload.name });
      }
      onOpenChange(false);
    } catch (err: unknown) {
      toast({
        title: isEdit ? '更新失败' : '创建失败',
        description: err instanceof Error ? err.message : '请稍后重试',
        variant: 'error',
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" showClose>
        <DialogHeader className="pb-2">
          <DialogTitle>{isEdit ? '编辑项目' : '新建项目'}</DialogTitle>
          <DialogDescription>
            {isEdit ? '修改项目基础信息（标识可改名）' : '项目是议题池的命名空间，可绑定代码仓库'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 px-6 pb-2">
          <div>
            <label htmlFor="project-slug" className="mb-1 block text-xs font-medium text-text-secondary">
              项目标识 <span className="text-danger">*</span>
            </label>
            <Input
              id="project-slug"
              value={form.slug}
              onChange={(e) => setField('slug', e.target.value)}
              placeholder="例如 conclave（小写字母、数字、- _）"
              aria-invalid={!!errors.slug}
            />
            <FieldError>{errors.slug}</FieldError>
          </div>
          <div>
            <label htmlFor="project-name" className="mb-1 block text-xs font-medium text-text-secondary">
              项目名称 <span className="text-danger">*</span>
            </label>
            <Input
              id="project-name"
              value={form.name}
              onChange={(e) => setField('name', e.target.value)}
              placeholder="例如 Conclave 多智能体平台"
              aria-invalid={!!errors.name}
            />
            <FieldError>{errors.name}</FieldError>
          </div>
          <div>
            <label htmlFor="project-repo" className="mb-1 block text-xs font-medium text-text-secondary">
              绑定仓库
            </label>
            <Input
              id="project-repo"
              value={form.repo_url}
              onChange={(e) => setField('repo_url', e.target.value)}
              placeholder="可空（纯文档型项目）"
            />
          </div>
          <div>
            <label htmlFor="project-branch" className="mb-1 block text-xs font-medium text-text-secondary">
              默认分支
            </label>
            <Input
              id="project-branch"
              value={form.default_branch}
              onChange={(e) => setField('default_branch', e.target.value)}
              placeholder="main"
            />
          </div>
          <div>
            <label htmlFor="project-desc" className="mb-1 block text-xs font-medium text-text-secondary">
              描述
            </label>
            <Textarea
              id="project-desc"
              value={form.description}
              onChange={(e) => setField('description', e.target.value)}
              placeholder="项目背景与目标（可选）"
              rows={2}
              className="resize-none"
            />
          </div>
        </div>

        <DialogFooter className="px-6 pb-5">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {isEdit ? '保存' : '创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
