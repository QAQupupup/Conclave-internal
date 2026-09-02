import * as React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { cn } from '@/lib/utils';
import { normalizeMarkdown } from '@/lib/markdown-normalize';

interface MarkdownProps {
  content: string;
  className?: string;
}

/**
 * 同步 Markdown 渲染器（直接导入 react-markdown）
 * 注意：react-markdown 已经通过 lazy-import 在外层处理
 *
 * remark-breaks：单个换行渲染为 <br>（GFM hard break）。
 * LLM 流式输出常用单换行分行，CommonMark 默认会把它折叠成空格，
 * 导致用户看到的换行丢失——与"所见即所得"的会议记录预期不符。
 */
export function Markdown({ content, className }: MarkdownProps) {
  // 渲染前归一化：压缩多余空行、移除空列表项/空引用行（代码块内部不受影响）
  const normalized = React.useMemo(() => normalizeMarkdown(content || ''), [content]);
  return (
    <div className={cn('prose-conclave', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>{normalized}</ReactMarkdown>
    </div>
  );
}
