/* Conclave — Report 视图（React + TypeScript）
 * 由 app.legacy.html 的 view-report / report-presentation 迁移而来。
 * 布局驱动渲染器 + 演示模式 + 导出（Markdown / HTML）。
 * className 与原 HTML / global.css 保持一致。 */

import { useEffect, useRef, useState, Fragment, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  getReportLayout,
  type ReportLayout,
  type ReportSection,
  type ReportBlock,
} from '../data/reportLayouts';
import {
  REPORT_TYPES,
  REPORT_DATA,
  REPORT_RESEARCH,
  REPORT_BUSINESS,
  REPORT_COMPREHENSIVE,
  REPORT_DEPLOYABLE,
} from '../data/reportData';
import {
  sanitizeRich,
  highlightDockerfile,
  highlightYamlReport,
  escHtml,
  cnSectionTitle,
} from '../lib/format';
import { useApp } from '../state/AppContext';
import { apiGetReportLayout } from '../lib/api';
import ServiceViewer from '../components/ServiceViewer';
import PhasedProgress from '../components/PhasedProgress';
import { useToast } from '../components/Toast';

/* ════════════════════════════════════════════════════════════════
 *  Block 渲染器（15 种 + raw/unknown 兜底）
 *  对照 BLOCK_RENDERERS（app.legacy.html 3063-3140）转为 JSX
 * ════════════════════════════════════════════════════════════════ */

/** 溯源标签 */
function TraceTag({ trace }: { trace?: string }) {
  const toast = useToast();
  if (!trace) return null;
  return (
    <span className="report-trace-tag" onClick={() => toast.show('来源: ' + trace, 'info')}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M9 6l6 6-6 6"/></svg>
      {trace}
    </span>
  );
}

function ParagraphBlock({ data }: { data: any }) {
  return <div className="report-p" dangerouslySetInnerHTML={{ __html: sanitizeRich(data?.text || '') }} />;
}

function ListBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  // 提取文本：处理三种情况
  // 1. 字符串且非 dict → 直接用
  // 2. 字符串但形如 Python dict（后端 str(claim_obj) 导致）→ 正则提取 claim 字段
  // 3. 对象 → 取 .claim 或 .text 字段
  const extractText = (it: any): string => {
    if (typeof it === 'string') {
      // 后端 bug：claim 对象被 str() 转成 "{'claim': '...', 'risk_level': None, ...}" 字符串
      // 前端兜底：正则提取 'claim' 字段的值
      const dictMatch = it.match(/^\{['"]claim['"]:\s*['"](.+?)['"],/s);
      if (dictMatch) return dictMatch[1];
      return it;
    }
    if (it && typeof it === 'object') return it.claim || it.text || it.content || it.summary || '';
    return String(it || '');
  };
  if (data?.ordered) {
    return (
      <ol className="report-num-list" style={{ counterReset: 'report-counter' }}>
        {items.map((it, i) => <li key={i} dangerouslySetInnerHTML={{ __html: sanitizeRich(extractText(it)) }} />)}
      </ol>
    );
  }
  return (
    <ul className="report-list">
      {items.map((it, i) => <li key={i} dangerouslySetInnerHTML={{ __html: sanitizeRich(extractText(it)) }} />)}
    </ul>
  );
}

function FindingsBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  // 提取文本：处理 dict 字符串（后端 str(claim_obj)）和对象两种情况
  const extractText = (it: any): string => {
    if (typeof it === 'string') {
      const dictMatch = it.match(/^\{['"]claim['"]:\s*['"](.+?)['"],/s);
      if (dictMatch) return dictMatch[1];
      return it;
    }
    if (it && typeof it === 'object') return it.claim || it.text || it.content || it.summary || it.detail || '';
    return String(it || '');
  };
  return (
    <div className="report-findings-list">
      {items.map((f, i) => {
        // 兼容后端返回的 claim 对象
        if (typeof f === 'object' && f.claim) {
          return (
            <div className="report-finding-card" key={i}>
              <div className="report-finding-topic">
                {f.agent_role ? `${f.agent_role}: ` : ''}
                <TraceTag trace={f.id} />
              </div>
              <div className="report-finding-detail" dangerouslySetInnerHTML={{ __html: sanitizeRich(f.claim) }} />
              {f.risk_level && <div className="report-finding-sources"><span style={{ color: 'var(--text-3)' }}>风险</span> <span className="report-finding-source">{f.risk_level}</span></div>}
            </div>
          );
        }
        return (
        <div className="report-finding-card" key={i}>
          {f.num ? <div className="report-finding-num">{f.num}</div> : null}
          <div className="report-finding-topic">{f.topic || ''} <TraceTag trace={f.trace} /></div>
          <div className="report-finding-detail" dangerouslySetInnerHTML={{ __html: sanitizeRich(f.detail || '') }} />
          {f.sources && f.sources.length ? (
            <div className="report-finding-sources">
              <span style={{ color: 'var(--text-3)' }}>来源</span>
              {' '}
              {f.sources.map((s: string, j: number) => <span className="report-finding-source" key={j}>{s}</span>)}
            </div>
          ) : null}
        </div>
        );
      })}
    </div>
  );
}

function CodeBlock({ data }: { data: any }) {
  const code: string = data?.code || '';
  const lang: string = data?.lang || 'TEXT';
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const collapsible = code.split('\n').length > 12;
  // 原码使用大写 DOCKER / YAML 判定高亮（数据中 lang 即为大写）
  const html = lang === 'DOCKER' ? highlightDockerfile(code)
    : lang === 'YAML' ? highlightYamlReport(code)
      : escHtml(code);

  const onCopy = (e: { stopPropagation: () => void }) => {
    e.stopPropagation();
    const clip = (navigator as any).clipboard;
    if (clip?.writeText) {
      clip.writeText(code).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  };

  const inner = (
    <div className="report-code-block">
      <span className="report-code-lang">{lang}</span>
      <span className={`report-copy-btn ${copied ? 'copied' : ''}`} onClick={onCopy}>{copied ? '已复制' : '复制'}</span>
      <span dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );

  if (!collapsible) return inner;
  return (
    <div className={`report-code-collapsible ${collapsed ? 'collapsed' : ''}`}>
      <span className="report-code-toggle" onClick={() => setCollapsed(c => !c)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path d="M6 9l6 6 6-6" /></svg>
        展开/折叠
      </span>
      {inner}
    </div>
  );
}

function ApiTableBlock({ data }: { data: any }) {
  const endpoints: string[] = data?.endpoints || [];
  return (
    <div className="sc-api-table">
      {endpoints.map((ep, i) => {
        const m = String(ep).match(/^(GET|POST|PUT|PATCH|DELETE)\s+(\S+)\s*[-—]?\s*(.*)$/);
        if (m) {
          return (
            <div className="sc-api-row" key={i}>
              <span className={`sc-api-method ${m[1]}`}>{m[1]}</span>
              <span className="sc-api-path">{m[2]}</span>
              {m[3] ? <span className="sc-api-desc">{m[3]}</span> : null}
            </div>
          );
        }
        return (
          <div className="sc-api-row" key={i}>
            <span className="sc-api-method GET">—</span>
            <span className="sc-api-path">{ep}</span>
          </div>
        );
      })}
    </div>
  );
}

function KpiGridBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  return (
    <div className="sc-kpi-grid">
      {items.map((k, i) => (
        <div className="sc-kpi" key={i}>
          <div className="sc-kpi-label">{k.label || ''}</div>
          <div className="sc-kpi-value">
            {k.value || ''}
            {k.unit ? <span className="sc-kpi-trend" style={{ fontSize: '13px', marginLeft: '4px' }}>{k.unit}</span> : null}
          </div>
          <div className={`sc-kpi-trend ${k.trend?.includes('↑') || k.trend?.includes('+') ? 'up' : k.trend?.includes('↓') || k.trend?.includes('-') ? 'down' : ''}`}>{k.trend || ''}</div>
        </div>
      ))}
    </div>
  );
}

function ConflictsBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  return (
    <div className="report-conflicts">
      {items.map((c, i) => (
        <div className="report-conflict" key={i}>
          <div className="report-conflict-summary">{i + 1}. {c.summary || ''} <TraceTag trace={c.trace} /></div>
          <div className="report-conflict-sides">
            <div className="report-conflict-side"><div className="report-conflict-side-label">A 方</div>{c.sideA || ''}</div>
            <div className="report-conflict-side"><div className="report-conflict-side-label">B 方</div>{c.sideB || ''}</div>
          </div>
          <div className="report-verdict">
            <span className={`report-verdict-badge ${c.verdict || 'compromise'}`}>{c.verdict === 'a' ? '采纳A方' : c.verdict === 'b' ? '采纳B方' : '折中'}</span>
            <span>{c.rationale || ''}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function RisksBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  return (
    <>
      {items.map((risk, i) => (
        <div className="report-risk-item" key={i}>
          <span className={`report-risk-level ${risk.level || 'mid'}`}>{risk.level === 'high' ? '高' : risk.level === 'mid' ? '中' : '低'}</span>
          <div className="report-risk-desc">{risk.desc || ''}</div>
        </div>
      ))}
    </>
  );
}

function TimelineBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  return (
    <>
      {items.map((t, i) => (
        <div className="report-timeline-item" key={i}>
          <span className="report-timeline-date">{t.date || ''}</span>
          <span className="report-timeline-text">{t.text || ''}</span>
        </div>
      ))}
    </>
  );
}

function DataModelBlock({ data }: { data: any }) {
  const entities: any[] = data?.entities || [];
  return (
    <div className="report-data-model">
      {entities.map((e, i) => (
        <div className="report-data-entity" key={i}>
          <span className="report-entity-name">{e.entity || ''}</span>
          <span className="report-entity-fields">
            {(e.fields || []).map((f: string, j: number) => {
              const pk = String(f).includes('[PK]'), fk = String(f).includes('[FK]');
              return <span className={`report-entity-field ${pk ? 'pk' : fk ? 'fk' : ''}`} key={j}>{f}</span>;
            })}
          </span>
        </div>
      ))}
    </div>
  );
}

function TestGroup({ group, items }: { group: string; items: any[] }) {
  const [collapsed, setCollapsed] = useState(false);
  const allPass = items.every(t => t.result === 'pass');
  return (
    <div className={`sc-test-group ${collapsed ? 'collapsed' : ''}`}>
      <div className="sc-test-group-header" onClick={() => setCollapsed(c => !c)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round"><path d="M6 9l6 6 6-6" /></svg>
        <span className="sc-test-group-name">{group}</span>
        <span className="sc-test-group-count">{items.length} 项</span>
        <span className={`sc-test-group-badge ${allPass ? 'pass' : 'fail'}`}>{allPass ? '全部通过' : '有失败'}</span>
      </div>
      {!collapsed && (
        <div className="sc-test-group-body">
          {items.map((t, i) => (
            <div className="sc-test-item" key={i}>
              <span className="sc-test-item-name">{t.name}</span>
              <span className={`sc-test-item-result ${t.result}`}>{String(t.result).toUpperCase()}</span>
              <span className="sc-test-item-time">{t.time || ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TestGroupsBlock({ data }: { data: any }) {
  const tests: any[] = data?.tests || [];
  const groups: Record<string, any[]> = {};
  tests.forEach(t => {
    const prefix = String(t.name).replace(/^test_/, '').split('_')[0];
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(t);
  });
  return (
    <>
      {Object.entries(groups).map(([group, items]) => <TestGroup key={group} group={group} items={items} />)}
    </>
  );
}

function FileTreeBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  return (
    <div className="sc-file-tree">
      <div className="sc-file-tree-header">项目结构</div>
      {items.map((f, i) => (
        <div
          className={f.type === 'dir' ? 'sc-file-tree-item dir' : 'sc-file-tree-item'}
          style={{ paddingLeft: `${14 + (f.indent || 0) * 14}px` }}
          key={i}
        >
          <svg className="ft-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            {f.type === 'dir' ? (
              <path d="M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
            ) : (
              <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></>
            )}
          </svg>
          {f.name || ''}
        </div>
      ))}
    </div>
  );
}

function FieldBlock({ data }: { data: any }) {
  return (
    <div className="report-field">
      <div className="report-field-label">{data?.label || ''}</div>
      <div className="report-field-value">{data?.value || ''}</div>
    </div>
  );
}

function TeamConfigBlock({ data }: { data: any }) {
  const items: any[] = data?.items || [];
  return (
    <div className="report-findings">
      {items.map((m, i) => (
        <div className="report-finding" key={i}>
          <div className="report-finding-topic">{m.role || ''}</div>
          <div className="report-finding-detail">{m.stance || ''}</div>
        </div>
      ))}
    </div>
  );
}

function AttachmentsBlock({ data }: { data: any }) {
  const toast = useToast();
  const items: any[] = data?.items || [];
  return (
    <div className="report-attachments">
      {items.map((att, i) => (
        <div className="report-attachment" key={i} onClick={() => toast.show('准备下载: ' + (att.filename || '附件'), 'info')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round"><path d="M12 4v12m0 0l-4-4m4 4l4-4M5 20h14" /></svg>
          <span>{att.filename || ''}</span>
          <span className="report-attachment-size">{((att.size || 0) / 1024).toFixed(1)}KB</span>
        </div>
      ))}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════
 *  专业化查看器（shadcn风格）
 * ════════════════════════════════════════════════════════════════ */

function ServiceViewerBlock({ data }: { data: any }) {
  const appCode = data?.app_code || '';
  const title = data?.title || '项目预览';
  const port = data?.port || undefined;
  const runCommand = data?.run_command || '';
  const fileCount = data?.file_count || 0;

  // 顶部信息条（shadcn card风格）
  return (
    <div style={{ margin: '12px 0' }}>
      {data?.complexity && (
        <div style={{ display: 'flex', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
          <span className="sc-badge sc-badge-outline">{title}</span>
          <span className="sc-badge sc-badge-secondary">{fileCount > 0 ? `${fileCount} 文件` : ''}</span>
          {data.complexity && (
            <span className={`sc-badge ${data.complexity === 'large' ? 'sc-badge-warning' : data.complexity === 'medium' ? 'sc-badge-info' : 'sc-badge-success'}`}>
              {data.complexity === 'large' ? '大型' : data.complexity === 'medium' ? '中型' : data.complexity === 'small' ? '小型' : '微服务'}
            </span>
          )}
        </div>
      )}
      <ServiceViewer appCode={appCode} title={title} port={port} runCommand={runCommand} />
    </div>
  );
}

function CodeCardBlock({ data }: { data: any }) {
  const code: string = data?.code || '';
  const lang: string = (data?.lang || 'TEXT').toUpperCase();
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    if ((navigator as any).clipboard?.writeText) {
      (navigator as any).clipboard.writeText(code).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  };

  // 简易语法高亮
  const html = lang === 'DOCKER' ? highlightDockerfile(code)
    : lang === 'YAML' ? highlightYamlReport(code)
      : escHtml(code);

  return (
    <div className="sc-code-card">
      <div className="sc-code-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div className="sc-code-card-chrome"><span /><span /><span /></div>
          <span className="sc-code-card-lang">{lang}</span>
        </div>
        <button className={`sc-code-card-copy ${copied ? 'copied' : ''}`} onClick={onCopy}>
          {copied ? '✓ 已复制' : '复制'}
        </button>
      </div>
      <pre><code dangerouslySetInnerHTML={{ __html: html }} /></pre>
    </div>
  );
}

function PhasedPipelineBlock({ data }: { data: any }) {
  return (
    <PhasedProgress
      percent={data?.percent || 0}
      currentStage={data?.current_stage || null}
      stageMessage={data?.message || ''}
      completedStages={data?.completed || []}
    />
  );
}

/** Block 分发器 */
function renderBlock(block: ReportBlock): JSX.Element {
  switch (block.type) {
    case 'paragraph': return <ParagraphBlock data={block.data} />;
    case 'list': return <ListBlock data={block.data} />;
    case 'findings': return <FindingsBlock data={block.data} />;
    case 'code': return <CodeBlock data={block.data} />;
    case 'code_card': return <CodeCardBlock data={block.data} />;
    case 'service_viewer': return <ServiceViewerBlock data={block.data} />;
    case 'api_table': return <ApiTableBlock data={block.data} />;
    case 'kpi_grid': return <KpiGridBlock data={block.data} />;
    case 'conflicts': return <ConflictsBlock data={block.data} />;
    case 'risks': return <RisksBlock data={block.data} />;
    case 'timeline': return <TimelineBlock data={block.data} />;
    case 'data_model': return <DataModelBlock data={block.data} />;
    case 'test_groups': return <TestGroupsBlock data={block.data} />;
    case 'file_tree': return <FileTreeBlock data={block.data} />;
    case 'field': return <FieldBlock data={block.data} />;
    case 'team_config': return <TeamConfigBlock data={block.data} />;
    case 'attachments': return <AttachmentsBlock data={block.data} />;
    case 'phased_pipeline': return <PhasedPipelineBlock data={block.data} />;
    case 'raw':
      return <div className="report-p" style={{ whiteSpace: 'pre-wrap' }} dangerouslySetInnerHTML={{ __html: sanitizeRich(block.data?.text || '') }} />;
    default:
      return <div className="report-p" style={{ color: 'var(--text-3)' }}>[未知块类型: {block.type}]</div>;
  }
}

/* ════════════════════════════════════════════════════════════════
 *  报告辅助组件（reportHeader / reportToc / reportAppendix / reportRating / reportActionsBar / Section）
 * ════════════════════════════════════════════════════════════════ */

const CONF_LABELS: Record<string, string> = {
  clarify: '澄清', intra_team: '讨论', cross_team: '辩论',
  evidence_check: '校验', arbitrate: '仲裁', produce: '产出',
};

function ReportHeader({ title, subtitle, meeting, confidence }: { title: string; subtitle: string; meeting: any; confidence?: Record<string, string> }) {
  const meetingId = meeting?.currentMeetingId || meeting?.id || '--';
  const meetingStatus = meeting?.status;
  const statusLabel = meetingStatus === 'done' ? '已完成' :
    meetingStatus === 'running' ? '进行中' :
    meetingStatus === 'failed' ? '失败' :
    meetingStatus === 'aborted' ? '已中止' :
    meetingStatus === 'paused' ? '已暂停' : '准备中';
  const generatedAt = meeting?.startTime
    ? new Date(meeting.startTime).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).replace(/\//g, '-')
    : '--';

  return (
    <>
      <div className="report-title">{title || '报告'}</div>
      <div className="report-subtitle">{subtitle || ''}</div>
      <div className="report-meta-line">
        <span>会议 {meetingId}</span>
        <span>状态 {statusLabel}</span>
        <span>生成于 {generatedAt}</span>
      </div>
      {confidence && Object.keys(confidence).length > 0 && (
        <div className="report-confidence">
          {Object.entries(confidence).map(([k, v]) => (
            <span className="conf-item" key={k}>
              <span className="conf-dot" style={{ background: v === 'high' ? 'var(--dot-done)' : 'var(--dot-paused)' }} />
              {CONF_LABELS[k] || k} {v}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

function ReportToc({ items, onJump }: { items: string[]; onJump?: (i: number) => void }) {
  return (
    <div className="report-toc" id="report-toc-box">
      <div className="report-toc-title">目录</div>
      <div className="report-toc-list">
        {items.map((it, i) => (
          <Fragment key={i}>
            {onJump ? (
              <a onClick={(e) => { e.preventDefault(); onJump(i); }}><span className="report-toc-num">{String(i + 1).padStart(2, '0')}</span>{it}</a>
            ) : (
              <a href={`#sec-${i + 1}`}><span className="report-toc-num">{String(i + 1).padStart(2, '0')}</span>{it}</a>
            )}
            <br />
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function ReportAppendix({ secNum, withId = true, trace }: { secNum?: number; withId?: boolean; trace?: Record<string, any> }) {
  const id = withId ? (secNum ? `sec-${secNum}` : 'report-appendix') : undefined;
  const t = trace || {};
  return (
    <div className="report-appendix" id={id}>
      <div className="report-appendix-title">附录 — 执行追踪</div>
      <div className="report-trace">
        <div className="report-trace-row"><span className="report-trace-label">LLM 调用次数</span><span className="report-trace-value">{t.totalCalls ?? '--'}</span></div>
        <div className="report-trace-row"><span className="report-trace-label">成功率</span><span className="report-trace-value">{t.successRate ?? '--'}</span></div>
        <div className="report-trace-row"><span className="report-trace-label">总 Token</span><span className="report-trace-value">{t.totalTokens ?? '--'}</span></div>
        <div className="report-trace-row"><span className="report-trace-label">输入 Token</span><span className="report-trace-value">{t.inputTokens ?? '--'}</span></div>
        <div className="report-trace-row"><span className="report-trace-label">输出 Token</span><span className="report-trace-value">{t.outputTokens ?? '--'}</span></div>
      </div>
    </div>
  );
}

function ReportRating() {
  const [rating, setRating] = useState(0);
  return (
    <div className="report-rating">
      <span className="report-rating-label">对本次产出评分</span>
      <div className="report-stars" id="report-stars">
        {[1, 2, 3, 4, 5].map(i => (
          <svg key={i} className={`report-star ${i <= rating ? 'active' : ''}`} onClick={() => setRating(i)} viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M12 2l3 7h7l-5.5 4.5L18 21l-6-4-6 4 1.5-7.5L2 9h7z" /></svg>
        ))}
      </div>
    </div>
  );
}

function ReportActionsBar({
  typeLabel, onPresent, onMarkdown, onHtml,
}: { typeLabel: string; onPresent: () => void; onMarkdown: () => void; onHtml: () => void }) {
  return (
    <div className="report-actions">
      <button className="ctrl-btn" onClick={onPresent}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M10 9l5 3-5 3z" fill="currentColor" /></svg>
        演示
      </button>
      <button className="ctrl-btn" onClick={onMarkdown}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round"><path d="M12 4v12m0 0l-4-4m4 4l4-4M5 20h14" /></svg>
        下载 Markdown
      </button>
      <button className="ctrl-btn html-export" onClick={onHtml}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round"><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5" /><line x1="9" y1="13" x2="16" y2="13" /><line x1="9" y1="17" x2="14" y2="17" /></svg>
        导出 HTML
      </button>
      <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--text-3)' }}>{typeLabel}</span>
    </div>
  );
}

/** 章节容器（含复制本节内容按钮） */
function Section({ index, section, withId = true }: { index: number; section: ReportSection; withId?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    const text = ref.current?.innerText.trim() || '';
    const clip = (navigator as any).clipboard;
    if (clip?.writeText) {
      clip.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  };

  return (
    <div className="report-section" id={withId ? `sec-${index + 1}` : undefined} ref={ref}>
      <div className="report-section-title-wrap">
        <div className="report-section-title">{cnSectionTitle(section.title, index)}</div>
        <span className={`report-block-copy ${copied ? 'copied' : ''}`} onClick={onCopy} title="复制本节内容">
          {copied ? (
            <><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M20 6L9 17l-5-5" /></svg>已复制</>
          ) : (
            <><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2}><rect x="9" y="9" width="11" height="11" rx="1" /><path d="M5 15V5a1 1 0 011-1h10" /></svg>复制</>
          )}
        </span>
      </div>
      {(section.blocks || []).map((b, i) => <Fragment key={i}>{renderBlock(b)}</Fragment>)}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════
 *  导出（Markdown / HTML）
 * ════════════════════════════════════════════════════════════════ */

function downloadBlob(content: string, filename: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function blockToMd(b: ReportBlock): string {
  const d = b.data || {};
  switch (b.type) {
    case 'paragraph':
    case 'raw':
      return d.text || '';
    case 'list': {
      const items: string[] = d.items || [];
      return d.ordered
        ? items.map((it, i) => `${i + 1}. ${it}`).join('\n')
        : items.map(it => `- ${it}`).join('\n');
    }
    case 'findings': {
      const items: any[] = d.items || [];
      return items.map(f => `**${f.num ? f.num + ' ' : ''}${f.topic || ''}**\n\n${f.detail || ''}${f.sources && f.sources.length ? `\n\n来源: ${f.sources.join(', ')}` : ''}`).join('\n\n');
    }
    case 'code': {
      const lang = d.lang ? String(d.lang).toLowerCase() : '';
      return '```' + lang + '\n' + (d.code || '') + '\n```';
    }
    case 'api_table': {
      const eps: string[] = d.endpoints || [];
      return eps.map(ep => `- \`${ep}\``).join('\n');
    }
    case 'kpi_grid': {
      const items: any[] = d.items || [];
      return '| 指标 | 值 | 趋势 |\n|---|---|---|\n' + items.map(k => `| ${k.label || ''} | ${k.value || ''}${k.unit || ''} | ${k.trend || ''} |`).join('\n');
    }
    case 'conflicts': {
      const items: any[] = d.items || [];
      return items.map((c, i) => `${i + 1}. ${c.summary || ''}\n   - A: ${c.sideA || ''}\n   - B: ${c.sideB || ''}\n   - 裁决: ${c.verdict || ''} — ${c.rationale || ''}${c.trace ? `\n   - 溯源: ${c.trace}` : ''}`).join('\n\n');
    }
    case 'risks': {
      const items: any[] = d.items || [];
      return items.map(r => `- [${r.level || 'mid'}] ${r.desc || ''}`).join('\n');
    }
    case 'timeline': {
      const items: any[] = d.items || [];
      return items.map(t => `- ${t.date || ''}: ${t.text || ''}`).join('\n');
    }
    case 'data_model': {
      const ents: any[] = d.entities || [];
      return ents.map(e => `**${e.entity || ''}**: ${(e.fields || []).join(', ')}`).join('\n');
    }
    case 'test_groups': {
      const tests: any[] = d.tests || [];
      return tests.map(t => `- [${t.result}] ${t.name} (${t.time})`).join('\n');
    }
    case 'file_tree': {
      const items: any[] = d.items || [];
      return '```\n' + items.map(f => `${'  '.repeat(f.indent || 0)}${f.name}`).join('\n') + '\n```';
    }
    case 'field':
      return `**${d.label || ''}**: ${d.value || ''}`;
    case 'team_config': {
      const items: any[] = d.items || [];
      return items.map(m => `- **${m.role || ''}**: ${m.stance || ''}`).join('\n');
    }
    case 'attachments': {
      const items: any[] = d.items || [];
      return items.map(a => `- ${a.filename || ''} (${((a.size || 0) / 1024).toFixed(1)}KB)`).join('\n');
    }
    default:
      return '';
  }
}

function layoutToMarkdown(layout: ReportLayout): string {
  const r = REPORT_DATA;
  const sections = layout.sections || [];
  let md = `# ${layout.title || ''}\n\n> ${layout.subtitle || ''}\n> 会议 ${r.meetingId} · 状态 ${r.status}\n\n---\n\n`;
  md += `## 目录\n${sections.map((s, i) => `${i + 1}. ${s.title}`).join('\n')}\n\n---\n\n`;
  md += sections
    .map((s, i) => `## ${cnSectionTitle(s.title, i)}\n\n${(s.blocks || []).map(blockToMd).join('\n\n')}`)
    .join('\n\n---\n\n');
  md += `\n\n---\n\n## 附录 — 执行追踪\n\n`;
  md += `- LLM 调用次数: ${r.llmTrace.totalCalls}\n`;
  md += `- 成功率: ${r.llmTrace.successRate}\n`;
  md += `- 总 Token: ${r.llmTrace.totalTokens}\n`;
  md += `- 输入 Token: ${r.llmTrace.inputTokens}\n`;
  md += `- 输出 Token: ${r.llmTrace.outputTokens}\n`;
  return md;
}

function exportReportMarkdown(layout: ReportLayout) {
  downloadBlob(layoutToMarkdown(layout), '报告.md', 'text/markdown');
}

function exportReportHtml(docEl: HTMLElement | null, layout: ReportLayout) {
  const content = docEl?.outerHTML || '';
  const styles = Array.from(document.querySelectorAll('style')).map(s => s.textContent || '').join('\n');
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>${escHtml(layout.title || 'Conclave 会议报告')}</title>
<style>${styles}
body{overflow:auto;margin:0;padding:40px 20px;background:#fff}
.report-type-bar,.report-back-top,.report-copy-btn,.report-block-copy,.report-code-toggle{display:none!important}
.report-code-collapsible .report-code-block{max-height:none!important}
.report-code-collapsible .report-code-block::after{display:none}
</style>
</head>
<body>
${content}
</body>
</html>`;
  downloadBlob(html, '报告.html', 'text/html');
}

/* ════════════════════════════════════════════════════════════════
 *  数据对象选择
 * ════════════════════════════════════════════════════════════════ */

function getDataForType(type: string): any {
  switch (type) {
    case 'prd_openapi': return REPORT_DATA;
    case 'research_report': return REPORT_RESEARCH;
    case 'business_report': return REPORT_BUSINESS;
    case 'comprehensive': return REPORT_COMPREHENSIVE;
    case 'deployable_service': return REPORT_DEPLOYABLE;
    default: return REPORT_DATA; // 其余类型用 REPORT_DATA 作 fallback
  }
}

/* ════════════════════════════════════════════════════════════════
 *  Report 主组件
 * ════════════════════════════════════════════════════════════════ */

export default function Report() {
  const { meeting, appendLog, openMeeting } = useApp();
  const { id: routeId } = useParams();
  const [currentReportType, setCurrentReportType] = useState<string>(meeting.type || 'prd_openapi');
  const [remoteLayout, setRemoteLayout] = useState<ReportLayout | null>(null);
  const [showBackTop, setShowBackTop] = useState(false);
  const [presentation, setPresentation] = useState(false);
  const [slideIndex, setSlideIndex] = useState(0);
  const docRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  /* 路由参数驱动：刷新 /report/:id 或直接进入该 URL 时，
   * 按 URL 中的 id 加载会议，使 currentMeetingId 与 URL 一致（刷新不丢失）。 */
  useEffect(() => {
    if (routeId && routeId !== meeting.currentMeetingId) {
      openMeeting(routeId);
    }
     
  }, [routeId]);

  /* 进入视图时尝试获取真实布局 */
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [layoutLoading, setLayoutLoading] = useState(false);

  const fetchLayout = useCallback(async (meetingId: string, reportType: string) => {
    setLayoutLoading(true);
    setLayoutError(null);
    try {
      const spec = await apiGetReportLayout(meetingId, reportType, false);
      if (spec && spec.sections) {
        setRemoteLayout(spec as ReportLayout);
      } else {
        setRemoteLayout(null);
      }
    } catch (e: any) {
      setRemoteLayout(null);
      setLayoutError(e.message || '报告加载失败');
    } finally {
      setLayoutLoading(false);
    }
  }, []);

  useEffect(() => {
    const id = meeting.currentMeetingId;
    if (!id) { setRemoteLayout(null); return; }
    fetchLayout(id, currentReportType);
     
  }, [meeting.currentMeetingId, currentReportType, fetchLayout]);

  const handleSwitchType = (id: string) => {
    setCurrentReportType(id);
    // 切换类型时触发重新请求，不清空为演示数据
  };

  // 布局选择：优先远程真实布局；否则基于会议快照渲染（如有产出）；否则显示空状态
  const dataObj = null; // 不再使用假数据填充
  const layout: ReportLayout | null = remoteLayout;
  const sections = layout?.sections || [];
  const tocItems = sections.map(s => s.title);
  const typeLabel = REPORT_TYPES.find(t => t.id === currentReportType)?.label || currentReportType;

  /* 返回顶部：滚动监听 */
  useEffect(() => {
    const content = document.querySelector('.content');
    if (!content) return;
    const onScroll = () => setShowBackTop(content.scrollTop > 300);
    content.addEventListener('scroll', onScroll, { passive: true });
    return () => content.removeEventListener('scroll', onScroll);
  }, []);

  /* 演示模式：键盘翻页 / 退出 */
  const totalSlides = sections.length + 3; // 封面 + 目录 + N 章节 + 附录
  useEffect(() => {
    if (!presentation) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === ' ') { e.preventDefault(); setSlideIndex(i => Math.min(i + 1, totalSlides - 1)); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); setSlideIndex(i => Math.max(i - 1, 0)); }
      else if (e.key === 'Escape') { setPresentation(false); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [presentation, totalSlides]);

  /* 切换幻灯片时重置画布滚动 */
  useEffect(() => {
    if (canvasRef.current) canvasRef.current.scrollTop = 0;
  }, [slideIndex, presentation]);

  const scrollToTop = () => document.querySelector('.content')?.scrollTo({ top: 0, behavior: 'smooth' });
  const openPresentation = () => { if (layout) { setSlideIndex(0); setPresentation(true); } };
  const exportMd = () => { if (layout) exportReportMarkdown(layout); };
  const exportHtml = () => { if (layout && docRef.current) exportReportHtml(docRef.current, layout); };

  return (
    <>
      {/* 报告类型栏：下拉选择器，紧凑不换行 */}
      <div className="report-type-bar" id="report-type-bar">
        <span className="report-type-label">产出类型</span>
        <div className="report-type-select-wrap">
          <select
            className="report-type-select"
            value={currentReportType}
            onChange={(e) => handleSwitchType(e.target.value)}
          >
            {REPORT_TYPES.map(t => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
          <svg className="report-type-select-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6"/></svg>
        </div>
        {meeting.currentMeetingId && (
          <span className="report-type-meeting">
            当前会议：{meeting.title || meeting.currentMeetingId}
          </span>
        )}
      </div>

      {/* 无会议选中时的提示 */}
      {!meeting.currentMeetingId && (
        <div className="board-empty" style={{ margin: '40px 0' }}>
          <div className="board-empty-title">未选择会议</div>
          <div className="board-empty-sub">请从会议看板选择一场会议后查看报告</div>
        </div>
      )}

      {/* 报告内容 */}
      {meeting.currentMeetingId && (
      <div id="report-content">
        {layoutLoading && !layout && (
          <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-3)' }}>
            加载报告中...
          </div>
        )}
        {!layoutLoading && layoutError && !layout && (
          <div className="board-empty" style={{ margin: '40px 0' }}>
            <div className="board-empty-title">报告加载失败</div>
            <div className="board-empty-sub">{layoutError}</div>
            <button className="btn btn-ghost" onClick={() => fetchLayout(meeting.currentMeetingId!, currentReportType)} style={{ marginTop: 16 }}>重试</button>
          </div>
        )}
        {!layoutLoading && !layoutError && !layout && (
          <div className="board-empty" style={{ margin: '40px 0' }}>
            <div className="board-empty-title">报告尚未生成</div>
            <div className="board-empty-sub">
              {meeting.status === 'running' || meeting.status === 'pending'
                ? '会议正在进行中，产出完成后可查看报告'
                : '该会议暂无报告产出'}
            </div>
          </div>
        )}
        {layout && (
        <div className="report-doc" ref={docRef}>
          <ReportActionsBar typeLabel={typeLabel} onPresent={openPresentation} onMarkdown={exportMd} onHtml={exportHtml} />
          <ReportHeader
            title={layout.title || meeting.title || ''}
            subtitle={layout.subtitle || ''}
            meeting={meeting}
            confidence={layout.confidence}
          />
          <ReportToc items={tocItems} />
          {sections.map((sec, i) => <Section key={i} index={i} section={sec} />)}
          <ReportAppendix secNum={sections.length + 1} trace={layout.trace} />
          <ReportRating />
        </div>
        )}
      </div>
      )}

      {/* 返回顶部 */}
      <div className={`report-back-top ${showBackTop ? 'show' : ''}`} id="report-back-top" onClick={scrollToTop} title="返回顶部">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"><path d="M12 20V8M6 14l6-6 6 6" /></svg>
      </div>

      {/* 演示模式覆盖层 */}
      {presentation && (
        <div className="report-presentation active">
          <div className="report-presentation-progress">
            <div className="report-presentation-progress-bar" style={{ width: `${((slideIndex + 1) / totalSlides) * 100}%` }} />
          </div>
          <div className="report-presentation-canvas" ref={canvasRef}>
            <div className="report-presentation-click-left" onClick={() => setSlideIndex(i => Math.max(i - 1, 0))} />
            <div className="report-presentation-click-right" onClick={() => setSlideIndex(i => Math.min(i + 1, totalSlides - 1))} />
            <div>
              {/* 封面 */}
              <div className={`report-presentation-slide ${slideIndex === 0 ? 'active' : ''}`}>
                {layout && (
                  <ReportHeader
                    title={layout.title || meeting.title || ''}
                    subtitle={layout.subtitle || ''}
                    meeting={meeting}
                    confidence={layout.confidence}
                  />
                )}
              </div>
              {/* 目录 */}
              <div className={`report-presentation-slide ${slideIndex === 1 ? 'active' : ''}`}>
                <ReportToc items={tocItems} onJump={(i) => setSlideIndex(2 + i)} />
              </div>
              {/* 各章节 */}
              {sections.map((sec, i) => (
                <div key={i} className={`report-presentation-slide ${slideIndex === 2 + i ? 'active' : ''}`}>
                  <Section index={i} section={sec} withId={false} />
                </div>
              ))}
              {/* 附录 + 评分 */}
              <div className={`report-presentation-slide ${slideIndex === 2 + sections.length ? 'active' : ''}`}>
                {layout && <ReportAppendix withId={false} trace={layout.trace} />}
                <ReportRating />
              </div>
            </div>
          </div>
          <div className="report-presentation-nav">
            <button className="report-presentation-nav-btn" disabled={slideIndex === 0} onClick={() => setSlideIndex(i => Math.max(i - 1, 0))}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round"><path d="M15 18l-6-6 6-6" /></svg>
            </button>
            <span className="report-presentation-counter">{slideIndex + 1} / {totalSlides}</span>
            <button className="report-presentation-nav-btn" disabled={slideIndex === totalSlides - 1} onClick={() => setSlideIndex(i => Math.min(i + 1, totalSlides - 1))}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round"><path d="M9 6l6 6-6 6" /></svg>
            </button>
            <span className="report-presentation-exit" onClick={() => setPresentation(false)}>退出演示 (Esc)</span>
          </div>
        </div>
      )}
    </>
  );
}
