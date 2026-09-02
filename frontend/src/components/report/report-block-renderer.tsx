/**
 * 报告布局渲染器 —— 按后端 report layout spec 通用渲染。
 *
 * 块类型与后端 backend/app/report_layout.py 的 SUPPORTED_BLOCK_TYPES 对齐
 * （共 16 种 + deployable_service 专用的 service_viewer + 前端保留的
 * heading/metric/table 兼容块）。此前前端仅覆盖 10 种，其余块走 default
 * 分支静默丢失内容（api_table/risks/conflicts 等章节整段空白）——本模块补齐。
 *
 * 渲染纪律（ui_design_system.yaml）：
 * - Notion 式软表格：中性灰表头、浅灰行线，无重阴影
 * - 语义色仅用于状态徽标（面积 < 5%）：高危=danger、中危=warning、低危=success
 * - 4-8px 圆角（rounded-md），颜色过渡用 --duration-hover
 * - paragraph/raw 块走 Markdown 渲染（后端约定 raw = 待前端处理的 Markdown）
 */
import * as React from 'react';
import { cn } from '@/lib/utils';
import { Markdown } from '@/components/ui/markdown';
import { FileIcon } from '@/components/ui/svg-icons';
import { api } from '@/lib/api';
import { formatTrace, parseApiEndpoint } from '@/components/report/report-block-utils';

// ===== 类型定义（与后端 layout spec 对齐） =====

/** 后端块数据形状宽泛，这里按已知字段声明，未知字段经索引签名透传 */
interface BlockData {
  [key: string]: unknown;
  text?: string;
  content?: string;
  items?: unknown[];
  ordered?: boolean;
  label?: string;
  value?: string | number;
  code?: string;
  lang?: string;
  count?: number;
  number?: number;
  headers?: string[];
  rows?: unknown[][];
  endpoints?: string[];
  entities?: ModelEntity[];
  tests?: TestItem[];
}

interface FindingItem {
  num?: number | string;
  topic?: string;
  detail?: string;
  sources?: string[];
  trace?: unknown;
}

interface AttachmentItem {
  filename?: string;
  name?: string;
  size?: number;
  path?: string;
}

interface KpiItem {
  label?: string;
  value?: string | number;
  unit?: string;
  trend?: string;
}

interface ConflictItem {
  summary?: string;
  sideA?: string;
  sideB?: string;
  verdict?: string;
  rationale?: string;
  trace?: unknown;
}

interface RiskItem {
  level?: string;
  desc?: string;
}

interface TimelineItem {
  date?: string;
  text?: string;
}

interface ModelEntity {
  entity?: string;
  fields?: string[];
}

interface TestItem {
  name?: string;
  result?: string;
  time?: string;
}

interface FileTreeNode {
  name?: string;
  type?: string;
  indent?: number;
}

interface TeamMember {
  role?: string;
  stance?: string;
}

interface ServiceViewerData {
  title?: string;
  port?: number | string;
  run_command?: string;
  app_code?: string;
  file_count?: number;
  complexity?: string;
}

export interface LayoutBlock {
  type: string;
  data: BlockData;
}

export interface LayoutSection {
  id: string;
  title: string;
  blocks: LayoutBlock[];
}

export interface LayoutSpec {
  title?: string;
  subtitle?: string;
  type?: string;
  sections?: LayoutSection[];
}

// ===== 小工具 =====

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** HTTP 方法徽标配色（语义色点缀，面积 < 5%） */
function methodBadgeClass(method: string): string {
  switch (method) {
    case 'GET':
      return 'bg-info-bg text-info';
    case 'POST':
      return 'bg-success-bg text-success';
    case 'PUT':
    case 'PATCH':
      return 'bg-warning-bg text-warning';
    case 'DELETE':
      return 'bg-danger-bg text-danger';
    default:
      return 'bg-bg-tertiary text-text-tertiary';
  }
}

/** 风险等级徽标配色 */
function riskLevelMeta(level: string | undefined): { label: string; className: string } {
  switch ((level ?? '').toLowerCase()) {
    case 'high':
      return { label: '高', className: 'bg-danger-bg text-danger' };
    case 'low':
      return { label: '低', className: 'bg-success-bg text-success' };
    default:
      return { label: '中', className: 'bg-warning-bg text-warning' };
  }
}

/** 裁决结果文案 */
function verdictLabel(verdict: string | undefined): string {
  switch ((verdict ?? '').toLowerCase()) {
    case 'a':
      return '采纳 A';
    case 'b':
      return '采纳 B';
    default:
      return '折中';
  }
}

// ===== 块渲染器 =====

interface BlockRendererProps {
  block: LayoutBlock;
  meetingId?: string;
}

export function ReportBlockRenderer({ block, meetingId }: BlockRendererProps) {
  const { type, data } = block;
  switch (type) {
    case 'paragraph':
      // 走 Markdown：承接 LLM 文本中的换行与行内格式（问题 3 修复 4）
      return data.text ? <Markdown content={data.text} className="prose-report text-sm" /> : null;
    case 'heading':
      return <h4 className="text-sm font-semibold text-text-primary">{data.text}</h4>;
    case 'list': {
      const items: string[] = Array.isArray(data.items)
        ? (data.items as unknown[]).map((v) => String(v))
        : [];
      if (items.length === 0) return null;
      const ListTag = data.ordered ? 'ol' : 'ul';
      return (
        <ListTag
          className={cn(
            'space-y-1 text-sm text-text-secondary',
            data.ordered ? 'list-decimal pl-5' : 'list-disc pl-4',
          )}
        >
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ListTag>
      );
    }
    case 'field':
      return (
        <div className="flex gap-2 text-sm">
          <span className="flex-shrink-0 text-text-tertiary">{data.label}:</span>
          <span className="text-text-secondary">{String(data.value ?? '')}</span>
        </div>
      );
    case 'code':
      return (
        <pre className="overflow-x-auto rounded-md bg-bg-tertiary p-3 text-[11px] leading-relaxed text-text-secondary">
          <code>{data.code}</code>
        </pre>
      );
    case 'metric': {
      const value = data.value ?? data.count ?? data.number ?? '';
      return (
        <div className="inline-flex flex-col rounded-md bg-bg-secondary px-3 py-2">
          <span className="text-lg font-semibold text-text-primary">{String(value)}</span>
          <span className="text-[10px] text-text-tertiary">{data.label ?? ''}</span>
        </div>
      );
    }
    case 'table': {
      const headers: string[] = Array.isArray(data.headers) ? data.headers : [];
      const rows: unknown[][] = Array.isArray(data.rows) ? data.rows : [];
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            {headers.length > 0 && (
              <thead>
                <tr className="border-b border-border-default">
                  {headers.map((h, i) => (
                    <th key={i} className="px-2 py-1.5 text-left font-medium text-text-tertiary">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri} className="border-b border-border-soft">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-2 py-1.5 text-text-secondary">
                      {String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    case 'raw':
      // 后端约定：raw = 待前端处理的 Markdown（report_layout.py 文档）
      return data.text ? <Markdown content={data.text} className="prose-report text-sm" /> : null;
    case 'api_table': {
      const endpoints: string[] = Array.isArray(data.endpoints)
        ? (data.endpoints as unknown[]).map((v) => String(v))
        : [];
      if (endpoints.length === 0) return null;
      return (
        <div className="overflow-x-auto rounded-md border border-border-soft">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-default bg-bg-secondary">
                <th className="w-20 px-2 py-1.5 text-left font-medium text-text-tertiary">方法</th>
                <th className="px-2 py-1.5 text-left font-medium text-text-tertiary">路径</th>
                <th className="px-2 py-1.5 text-left font-medium text-text-tertiary">说明</th>
              </tr>
            </thead>
            <tbody>
              {endpoints.map((raw, i) => {
                const ep = parseApiEndpoint(raw);
                return (
                  <tr key={i} className="border-b border-border-soft last:border-b-0">
                    <td className="px-2 py-1.5">
                      {ep.method ? (
                        <span
                          className={cn(
                            'inline-block rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold',
                            methodBadgeClass(ep.method),
                          )}
                        >
                          {ep.method}
                        </span>
                      ) : (
                        <span className="text-text-tertiary">—</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-text-secondary">{ep.path}</td>
                    <td className="px-2 py-1.5 text-text-secondary">{ep.desc}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      );
    }
    case 'kpi_grid': {
      const items: KpiItem[] = Array.isArray(data.items) ? (data.items as KpiItem[]) : [];
      if (items.length === 0) return null;
      return (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {items.map((item, i) => (
            <div key={i} className="rounded-md border border-border-soft bg-bg-secondary/40 px-3 py-2">
              <div className="flex items-baseline gap-1">
                <span className="text-lg font-semibold text-text-primary">{String(item.value ?? '—')}</span>
                {item.unit && <span className="text-[10px] text-text-tertiary">{item.unit}</span>}
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2">
                <span className="truncate text-[10px] text-text-tertiary">{item.label ?? ''}</span>
                {item.trend && <span className="flex-shrink-0 text-[10px] text-text-tertiary">{item.trend}</span>}
              </div>
            </div>
          ))}
        </div>
      );
    }
    case 'conflicts': {
      const items: ConflictItem[] = Array.isArray(data.items) ? (data.items as ConflictItem[]) : [];
      if (items.length === 0) return null;
      return (
        <div className="space-y-2">
          {items.map((item, i) => {
            const trace = formatTrace(item.trace);
            return (
              <div key={i} className="rounded-md border border-border-soft bg-bg-secondary/40 p-3">
                <div className="flex items-start justify-between gap-2">
                  {item.summary && (
                    <div className="min-w-0 flex-1 text-sm font-medium text-text-primary">{item.summary}</div>
                  )}
                  <span className="flex-shrink-0 rounded bg-brand-soft px-1.5 py-0.5 text-[10px] font-medium text-brand-600">
                    {verdictLabel(item.verdict)}
                  </span>
                </div>
                {(item.sideA || item.sideB) && (
                  <div className="mt-2 space-y-1 text-xs text-text-secondary">
                    {item.sideA && (
                      <div className="flex gap-2">
                        <span className="flex-shrink-0 font-medium text-text-tertiary">A:</span>
                        <span>{item.sideA}</span>
                      </div>
                    )}
                    {item.sideB && (
                      <div className="flex gap-2">
                        <span className="flex-shrink-0 font-medium text-text-tertiary">B:</span>
                        <span>{item.sideB}</span>
                      </div>
                    )}
                  </div>
                )}
                {item.rationale && (
                  <p className="mt-2 text-xs leading-relaxed text-text-secondary">裁决理由: {item.rationale}</p>
                )}
                {trace && <p className="mt-1 text-[10px] text-text-tertiary">溯源: {trace}</p>}
              </div>
            );
          })}
        </div>
      );
    }
    case 'risks': {
      const items: RiskItem[] = Array.isArray(data.items) ? (data.items as RiskItem[]) : [];
      if (items.length === 0) return null;
      return (
        <div className="space-y-1.5">
          {items.map((item, i) => {
            const meta = riskLevelMeta(item.level);
            return (
              <div key={i} className="flex items-start gap-2 text-sm">
                <span
                  className={cn(
                    'mt-0.5 flex h-4 w-8 flex-shrink-0 items-center justify-center rounded text-[10px] font-medium',
                    meta.className,
                  )}
                >
                  {meta.label}
                </span>
                <span className="min-w-0 flex-1 text-text-secondary">{item.desc}</span>
              </div>
            );
          })}
        </div>
      );
    }
    case 'timeline': {
      const items: TimelineItem[] = Array.isArray(data.items) ? (data.items as TimelineItem[]) : [];
      if (items.length === 0) return null;
      return (
        <div className="space-y-0 border-l border-border-default pl-4">
          {items.map((item, i) => (
            <div key={i} className="relative pb-3 last:pb-0">
              {/* 时间节点圆点：对齐左侧竖线 */}
              <span
                aria-hidden="true"
                className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full border border-border-emphasis bg-bg-primary"
              />
              {item.date && <div className="text-[10px] text-text-tertiary">{item.date}</div>}
              <div className="text-sm text-text-secondary">{item.text}</div>
            </div>
          ))}
        </div>
      );
    }
    case 'data_model': {
      const entities: ModelEntity[] = Array.isArray(data.entities) ? data.entities : [];
      if (entities.length === 0) return null;
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          {entities.map((ent, i) => (
            <div key={i} className="rounded-md border border-border-soft">
              <div className="border-b border-border-soft bg-bg-secondary px-3 py-1.5 text-xs font-semibold text-text-primary">
                {ent.entity}
              </div>
              <ul className="space-y-0.5 px-3 py-2">
                {(ent.fields ?? []).map((f, fi) => (
                  <li key={fi} className="font-mono text-[11px] text-text-secondary">
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      );
    }
    case 'test_groups': {
      const tests: TestItem[] = Array.isArray(data.tests) ? data.tests : [];
      if (tests.length === 0) return null;
      const passed = tests.filter((t) => (t.result ?? '').toLowerCase() === 'pass').length;
      return (
        <div className="rounded-md border border-border-soft">
          <div className="flex items-center justify-between border-b border-border-soft bg-bg-secondary px-3 py-1.5">
            <span className="text-[10px] text-text-tertiary">共 {tests.length} 项</span>
            <span className="text-[10px] text-text-tertiary">
              通过 <span className="font-medium text-success">{passed}</span> · 失败{' '}
              <span className={cn('font-medium', tests.length - passed > 0 ? 'text-danger' : 'text-text-tertiary')}>
                {tests.length - passed}
              </span>
            </span>
          </div>
          <div className="divide-y divide-border-soft">
            {tests.map((t, i) => {
              const isPass = (t.result ?? '').toLowerCase() === 'pass';
              return (
                <div key={i} className="flex items-center gap-2 px-3 py-1.5">
                  <span
                    className={cn(
                      'flex h-4 w-8 flex-shrink-0 items-center justify-center rounded text-[10px] font-medium',
                      isPass ? 'bg-success-bg text-success' : 'bg-danger-bg text-danger',
                    )}
                  >
                    {isPass ? '通过' : '失败'}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-secondary">{t.name}</span>
                  {t.time && <span className="flex-shrink-0 text-[10px] text-text-tertiary">{t.time}</span>}
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    case 'file_tree': {
      const items: FileTreeNode[] = Array.isArray(data.items) ? (data.items as FileTreeNode[]) : [];
      if (items.length === 0) return null;
      return (
        <div className="rounded-md bg-bg-tertiary p-3 font-mono text-[11px] leading-relaxed">
          {items.map((item, i) => {
            const isDir = item.type === 'dir';
            return (
              <div
                key={i}
                className={cn('whitespace-pre', isDir ? 'font-semibold text-text-primary' : 'text-text-secondary')}
                style={{ paddingLeft: `${(item.indent ?? 0) * 1}rem` }}
              >
                {isDir ? `${item.name}/` : item.name}
              </div>
            );
          })}
        </div>
      );
    }
    case 'team_config': {
      const items: TeamMember[] = Array.isArray(data.items) ? (data.items as TeamMember[]) : [];
      if (items.length === 0) return null;
      return (
        <div className="space-y-1">
          {items.map((m, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <span className="flex-shrink-0 rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-medium text-text-secondary">
                {m.role}
              </span>
              {m.stance && <span className="min-w-0 flex-1 text-xs leading-relaxed text-text-secondary">{m.stance}</span>}
            </div>
          ))}
        </div>
      );
    }
    case 'service_viewer': {
      const sv = data as unknown as ServiceViewerData;
      return (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs text-text-tertiary">
            {sv.port != null && (
              <span className="rounded bg-bg-tertiary px-1.5 py-0.5 font-mono text-[10px]">端口 {String(sv.port)}</span>
            )}
            {sv.file_count != null && Number(sv.file_count) > 0 && (
              <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px]">{String(sv.file_count)} 个文件</span>
            )}
            {sv.complexity && (
              <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px]">复杂度: {sv.complexity}</span>
            )}
          </div>
          {sv.run_command && (
            <div className="flex gap-2 text-xs">
              <span className="flex-shrink-0 text-text-tertiary">启动命令:</span>
              <code className="font-mono text-text-secondary">{sv.run_command}</code>
            </div>
          )}
          {sv.app_code && (
            <pre className="max-h-96 overflow-auto rounded-md bg-bg-tertiary p-3 text-[11px] leading-relaxed text-text-secondary">
              <code>{sv.app_code}</code>
            </pre>
          )}
        </div>
      );
    }
    case 'findings': {
      const items: FindingItem[] = Array.isArray(data.items) ? (data.items as FindingItem[]) : [];
      if (items.length === 0) return null;
      return (
        <div className="space-y-2">
          {items.map((item, i) => {
            const trace = formatTrace(item.trace);
            return (
              <div key={i} className="rounded-md border border-border-soft bg-bg-secondary/40 p-3">
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded bg-brand-500/10 text-[10px] font-semibold text-brand-600">
                    {item.num ?? String(i + 1).padStart(2, '0')}
                  </span>
                  <div className="min-w-0 flex-1">
                    {item.topic && <div className="text-sm font-medium text-text-primary">{item.topic}</div>}
                    {item.detail && (
                      <p className="mt-0.5 text-xs leading-relaxed text-text-secondary">{item.detail}</p>
                    )}
                    {Array.isArray(item.sources) && item.sources.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {item.sources.map((s: string, si: number) => (
                          <span key={si} className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] text-text-tertiary">
                            {s}
                          </span>
                        ))}
                      </div>
                    )}
                    {trace && <p className="mt-1 text-[10px] text-text-tertiary">溯源: {trace}</p>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      );
    }
    case 'attachments': {
      const items: AttachmentItem[] = Array.isArray(data.items) ? (data.items as AttachmentItem[]) : [];
      if (items.length === 0) return <p className="text-xs text-text-tertiary">暂无附件</p>;
      return (
        <div className="space-y-1">
          {items.map((item, i) => {
            const filename: string = item.filename ?? item.name ?? '';
            const size = item.size;
            return (
              <div
                key={item.path ?? filename ?? i}
                className="flex items-center gap-2 rounded-md border border-border-soft bg-bg-secondary/40 px-3 py-2"
              >
                <FileIcon size={14} className="flex-shrink-0 text-text-tertiary" />
                <span className="min-w-0 flex-1 truncate text-xs text-text-secondary">{filename}</span>
                {size != null && (
                  <span className="text-[10px] text-text-tertiary">{formatFileSize(Number(size))}</span>
                )}
                {meetingId && filename && (
                  <button
                    type="button"
                    onClick={() =>
                      api.download(`/meetings/${meetingId}/attachments/${encodeURIComponent(filename)}`, filename)
                    }
                    className="flex-shrink-0 text-xs text-brand-500 hover:underline"
                  >
                    下载
                  </button>
                )}
              </div>
            );
          })}
        </div>
      );
    }
    default:
      // 未知类型兜底：有文本就渲染，避免静默丢失；无任何可展示内容才返回 null
      if (data.text || data.content) {
        return <p className="text-sm text-text-secondary">{data.text || data.content}</p>;
      }
      return null;
  }
}

export function ReportLayoutRenderer({ layout, meetingId }: { layout: LayoutSpec | null; meetingId?: string }) {
  if (!layout) return null;
  const sections = Array.isArray(layout.sections) ? layout.sections : [];
  if (sections.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border-default p-4 text-center text-xs text-text-tertiary">
        暂无结构化报告内容
      </div>
    );
  }
  return (
    <div className="space-y-(--rhythm-section)">
      {sections.map((section) => (
        <div key={section.id}>
          <h4 className="mb-2 border-b border-border-soft pb-1 text-sm font-semibold text-text-primary">
            {section.title}
          </h4>
          <div className="space-y-(--rhythm-block)">
            {(section.blocks ?? []).map((block, i) => (
              <ReportBlockRenderer key={i} block={block} meetingId={meetingId} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
