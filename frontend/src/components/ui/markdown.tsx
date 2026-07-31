import * as React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

interface MarkdownProps {
  content: string;
  className?: string;
}

/**
 * 同步 Markdown 渲染器（直接导入 react-markdown）
 * 注意：react-markdown 已经通过 lazy-import 在外层处理
 */
export function Markdown({ content, className }: MarkdownProps) {
  return (
    <div className={cn('prose-conclave', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || ''}</ReactMarkdown>
    </div>
  );
}
