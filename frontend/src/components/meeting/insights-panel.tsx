import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useMeetingDetailRaw } from '@/hooks/use-meetings';
import { cn } from '@/lib/utils';
import type { CanvasKind } from '@/stores/ui-slice';
import { SpinnerIcon, LinkIcon, AlertCircleIcon, CheckIcon, GitBranchIcon } from '@/components/ui/svg-icons';

/** 洞察画布的三个 tab（画布类别的子集，tab 即画布焦点） */
export type InsightsTab = Extract<CanvasKind, 'conflicts' | 'related' | 'observability'>;

interface RelatedMeeting {
  meeting_id: string;
  topic: string;
  status: string;
  deliverable_type?: string;
  score?: number;
}

interface ConflictItem {
  summary?: string;
  conflict_type?: string;
  side_a?: string;
  side_b?: string;
}

interface EvidenceSetItem {
  assessments?: unknown[];
}

interface ObservabilityDetail {
  topic?: string;
  stage?: string;
  status?: string;
  artifact?: { title?: string };
  decision_record?: { quality_score?: number };
  quality_score?: number;
  key_questions?: string[];
}

const TABS: { key: InsightsTab; label: string }[] = [
  { key: 'conflicts', label: '冲突与证据' },
  { key: 'related', label: '相关会议' },
  { key: 'observability', label: '可观测' },
];

interface InsightsCanvasProps {
  meetingId: string;
  /** 受控 tab：由画布状态层（ui-slice.activeCanvas）驱动 */
  tab: InsightsTab;
  onTabChange: (tab: InsightsTab) => void;
}

/**
 * 洞察画布内容：冲突/证据、相关会议、可观测指标。
 * 由悬浮画布体系（FloatingPanel M 档）承载，不再作为右栏内嵌面板。
 */
export function InsightsCanvas({ meetingId, tab, onTabChange }: InsightsCanvasProps) {
  const detail = useMeetingDetailRaw(meetingId);
  const graph = useQuery({
    queryKey: ['graph', 'overview', meetingId],
    queryFn: () => api.graphOverview(meetingId),
    enabled: !!meetingId,
  });
  const related = useQuery({
    queryKey: ['meeting', 'related', meetingId],
    queryFn: () => api.meetingRelated(meetingId, 5),
    enabled: !!meetingId,
  });

  const conflicts = (Array.isArray(detail.data?.conflicts) ? detail.data!.conflicts : []) as ConflictItem[];
  const evidenceSet = (Array.isArray(detail.data?.evidence_set) ? detail.data!.evidence_set : []) as EvidenceSetItem[];
  const edges = Array.isArray(graph.data?.edges) ? graph.data!.edges : [];
  const supportsCount = edges.filter((e) => e.type === 'supports').length;
  const contradictsCount = edges.filter((e) => e.type === 'contradicts').length;

  return (
    <div className="flex flex-col">
      {/* Tabs（sticky：画布内容区滚动时 tab 栏保持可见） */}
      <div className="sticky top-0 z-10 flex items-center border-b border-border-soft bg-bg-elevated">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => onTabChange(t.key)}
            className={cn(
              'relative flex-1 px-2 py-2 text-xs font-medium transition-colors',
              tab === t.key
                ? 'text-brand-600'
                : 'text-text-tertiary hover:text-text-secondary',
            )}
          >
            {t.label}
            {t.key === 'conflicts' && (conflicts.length > 0 || supportsCount > 0) && (
              <span className="ml-1 rounded-full bg-brand-soft px-1.5 text-[10px] text-brand-600">
                {conflicts.length + supportsCount}
              </span>
            )}
            {tab === t.key && (
              <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-brand-500" />
            )}
          </button>
        ))}
      </div>

      {/* 内容区不另设滚动：画布内容容器（FloatingPanel）是唯一滚动条 */}
      <div className="p-3">
        {tab === 'conflicts' && (
          <ConflictsTab
            conflicts={conflicts}
            evidenceSet={evidenceSet}
            supportsCount={supportsCount}
            contradictsCount={contradictsCount}
            loading={detail.isLoading && graph.isLoading}
          />
        )}
        {tab === 'related' && <RelatedTab related={related.data?.meetings as RelatedMeeting[]} loading={related.isLoading} />}
        {tab === 'observability' && <ObservabilityTab detail={detail.data as unknown as ObservabilityDetail | undefined} loading={detail.isLoading} />}
      </div>
    </div>
  );
}

function ConflictsTab({
  conflicts,
  evidenceSet,
  supportsCount,
  contradictsCount,
  loading,
}: {
  conflicts: ConflictItem[];
  evidenceSet: EvidenceSetItem[];
  supportsCount: number;
  contradictsCount: number;
  loading: boolean;
}) {
  if (loading) {
    return <CenterSpinner />;
  }
  if (conflicts.length === 0 && supportsCount === 0 && contradictsCount === 0) {
    return (
      <EmptyHint icon={<GitBranchIcon size={18} />} text="本轮讨论未识别到冲突，或会议尚未完成物化。" />
    );
  }
  const totalEvidence = evidenceSet.reduce(
    (acc, es) => acc + (Array.isArray(es?.assessments) ? es.assessments.length : 0),
    0,
  );
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <StatChip label="冲突" value={conflicts.length} tone="danger" />
        <StatChip label="矛盾边" value={contradictsCount} tone="danger" />
        <StatChip label="支撑边" value={supportsCount} tone="success" />
      </div>
      {totalEvidence > 0 && (
        <div className="rounded-md border border-border-soft bg-bg-secondary px-2.5 py-1.5 text-[11px] text-text-tertiary">
          证据条目 {totalEvidence} 条已物化到图谱
        </div>
      )}
      <div className="space-y-2">
        {conflicts.map((c, i) => (
          <div key={i} className="rounded-md border border-border-soft bg-bg-secondary p-2.5">
            <div className="mb-1 flex items-start gap-1.5">
              <AlertCircleIcon size={13} className="mt-0.5 flex-shrink-0 text-danger" />
              <span className="text-xs leading-snug text-text-primary">
                {(c.summary || c.conflict_type || '未命名冲突').toString().slice(0, 160)}
              </span>
            </div>
            {(c.side_a || c.side_b) && (
              <div className="space-y-1 border-l-2 border-border-soft pl-2">
                {c.side_a && <SideLine label="A" text={c.side_a} />}
                {c.side_b && <SideLine label="B" text={c.side_b} />}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SideLine({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex gap-1.5 text-[11px] text-text-secondary">
      <span className="font-medium text-text-tertiary">{label}</span>
      <span className="line-clamp-2">{text.toString().slice(0, 120)}</span>
    </div>
  );
}

function RelatedTab({ related, loading }: { related?: RelatedMeeting[]; loading: boolean }) {
  if (loading) return <CenterSpinner />;
  if (!related || related.length === 0) {
    return <EmptyHint icon={<LinkIcon size={18} />} text="暂无语义相似的历史会议。" />;
  }
  return (
    <ul className="space-y-1.5">
      {related.map((m) => (
        <li key={m.meeting_id}>
          <a
            href={`/meeting/${m.meeting_id}`}
            className="block rounded-md border border-border-soft bg-bg-secondary px-2.5 py-2 transition-colors hover:border-brand-500/40"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="line-clamp-1 text-xs text-text-primary">{m.topic}</span>
              {typeof m.score === 'number' && (
                <span className="flex-shrink-0 rounded bg-brand-soft px-1.5 text-[10px] text-brand-600">
                  {(m.score * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <div className="mt-0.5 text-[10px] text-text-tertiary">{m.status}</div>
          </a>
        </li>
      ))}
    </ul>
  );
}

function ObservabilityTab({ detail, loading }: { detail?: ObservabilityDetail; loading: boolean }) {
  if (loading) return <CenterSpinner />;
  if (!detail) return <EmptyHint icon={<CheckIcon size={18} />} text="暂无可观测数据。" />;
  const artifact = detail.artifact || {};
  const decision = detail.decision_record || {};
  const quality = decision.quality_score ?? detail.quality_score;
  const rows: { label: string; value: string }[] = [
    { label: '议题', value: detail.topic || '—' },
    { label: '阶段', value: detail.stage || '—' },
    { label: '状态', value: detail.status || '—' },
    { label: '产出标题', value: artifact.title || '—' },
  ];
  if (quality != null) rows.push({ label: '质量评分', value: `${Math.round(quality)}` });
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="flex items-start justify-between gap-3 border-b border-border-soft py-1.5 last:border-0">
          <span className="flex-shrink-0 text-[11px] text-text-tertiary">{r.label}</span>
          <span className="min-w-0 text-right text-xs text-text-primary">{r.value}</span>
        </div>
      ))}
      {detail.key_questions && Array.isArray(detail.key_questions) && detail.key_questions.length > 0 && (
        <div className="pt-2">
          <div className="mb-1 text-[11px] font-medium text-text-tertiary">关键问题</div>
          <ul className="list-inside list-disc space-y-0.5 text-[11px] text-text-secondary">
            {detail.key_questions.slice(0, 5).map((q: string, i: number) => (
              <li key={i} className="line-clamp-2">{q}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StatChip({ label, value, tone }: { label: string; value: number; tone: 'danger' | 'success' }) {
  return (
    <div className="rounded-md border border-border-soft bg-bg-secondary px-2 py-1.5 text-center">
      <div className={cn('text-base font-semibold', tone === 'danger' ? 'text-danger' : 'text-success')}>{value}</div>
      <div className="text-[10px] text-text-tertiary">{label}</div>
    </div>
  );
}

function CenterSpinner() {
  return (
    <div className="flex h-24 items-center justify-center">
      <SpinnerIcon size={18} className="animate-spin text-text-tertiary" />
    </div>
  );
}

function EmptyHint({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center text-text-tertiary">
      <div className="opacity-60">{icon}</div>
      <span className="text-xs">{text}</span>
    </div>
  );
}
