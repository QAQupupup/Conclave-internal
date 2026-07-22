// PhasedProgress - 分阶段生成管线进度可视化组件
// 监听 produce.progress 事件，展示7阶段进度
import { useState, useEffect } from 'react';

/** produce-progress 自定义事件的 detail 载荷 */
interface ProduceProgressDetail {
  meeting_id?: string;
  step?: string;
  message?: string;
  percent?: number;
}

interface PhaseInfo {
  key: string;
  name: string;
  desc: string;
}

const PHASES: PhaseInfo[] = [
  { key: 'plan',     name: '架构规划',  desc: '复杂度评估 · 模块划分 · 技术选型' },
  { key: 'specs',    name: '规格先行',  desc: 'PRD文档 · OpenAPI规范' },
  { key: 'tests',    name: '测试先行',  desc: '单元测试骨架' },
  { key: 'scaffold', name: '骨架搭建',  desc: '配置 · 入口 · 数据库基础' },
  { key: 'modules',  name: '模块填充',  desc: 'schemas → models → dao → services → routers' },
  { key: 'frontend', name: '前端生成',  desc: '页面 · 组件 · API对接' },
  { key: 'integrate',name: '整合部署',  desc: '路由注册 · Docker配置 · 集成测试' },
];

interface PhasedProgressProps {
  // 外部可传入当前状态（来自SSE/WebSocket事件）
  currentStage?: string | null;
  stageMessage?: string;
  percent?: number;
  error?: string | null;
  // 已完成的阶段列表
  completedStages?: string[];
}

export default function PhasedProgress({
  currentStage,
  stageMessage,
  percent = 0,
  error,
  completedStages = [],
}: PhasedProgressProps) {
  // 如果没有传入状态，根据percent推断阶段
  const activeKey = currentStage || (percent > 0 ? PHASES[Math.min(Math.floor(percent / 14), 6)]?.key : null);

  const getStageStatus = (phase: PhaseInfo): 'pending' | 'active' | 'done' | 'error' => {
    if (error && phase.key === activeKey) return 'error';
    if (completedStages.includes(phase.key)) return 'done';
    if (phase.key === activeKey) return 'active';
    return 'pending';
  };

  const getMarker = (status: string, idx: number) => {
    if (status === 'done') return (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
    if (status === 'error') return (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
        <path d="M18 6L6 18M6 6l12 12" />
      </svg>
    );
    return idx + 1;
  };

  const allDone = percent >= 100 || completedStages.length >= PHASES.length;

  return (
    <div className="phased-pipeline">
      <div className="phased-pipeline-title">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
        分阶段代码生成管线
        {allDone && (
          <span className="sc-badge sc-badge-success" style={{ marginLeft: 'auto' }}>
            生成完成
          </span>
        )}
        {error && (
          <span className="sc-badge sc-badge-error" style={{ marginLeft: 'auto' }}>
            异常，已回退
          </span>
        )}
      </div>

      {/* 进度条 */}
      {!allDone && !error && (
        <div style={{ marginBottom: '16px' }}>
          <div className="sc-progress">
            <div
              className="sc-progress-indicator"
              style={{
                width: `${percent}%`,
                transform: 'none',
                transition: 'width .4s ease',
              }}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '6px', fontSize: '11px', color: 'var(--sc-muted-foreground)', fontFamily: 'var(--mono)' }}>
            <span>{stageMessage || '准备中...'}</span>
            <span>{percent}%</span>
          </div>
        </div>
      )}

      {/* 阶段列表 */}
      <div className="phased-pipeline-stages">
        {PHASES.map((phase, idx) => {
          const status = getStageStatus(phase);
          return (
            <div key={phase.key} className={`phased-stage ${status}`}>
              <div className="phased-stage-marker">
                {getMarker(status, idx)}
              </div>
              <div className="phased-stage-content">
                <div className="phased-stage-name">{phase.name}</div>
                <div className="phased-stage-msg">
                  {status === 'active' && stageMessage
                    ? stageMessage
                    : phase.desc}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Hook：监听 produce.progress 事件（通过eventBus）
export function usePhasedProgress(meetingId?: string) {
  const [state, setState] = useState<{
    currentStage: string | null;
    stageMessage: string;
    percent: number;
    completedStages: string[];
    error: string | null;
  }>({
    currentStage: null,
    stageMessage: '',
    percent: 0,
    completedStages: [],
    error: null,
  });

  useEffect(() => {
    // 这里通过window自定义事件总线监听，具体绑定在集成时处理
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ProduceProgressDetail>).detail;
      const data: ProduceProgressDetail = detail ?? {};
      if (meetingId && data.meeting_id !== meetingId) return;
      const step: string = data.step || '';
      const msg: string = data.message || '';
      const pct: number = typeof data.percent === 'number' ? data.percent : 0;

      if (step.startsWith('phased_')) {
        const phaseKey = step.replace('phased_', '');
        setState(prev => {
          const completed = prev.currentStage && prev.currentStage !== phaseKey
            ? [...new Set([...prev.completedStages, prev.currentStage])]
            : prev.completedStages;
          return {
            currentStage: phaseKey,
            stageMessage: msg,
            percent: pct,
            completedStages: completed,
            error: null,
          };
        });
      } else if (step === 'phased_done') {
        setState(prev => ({
          ...prev,
          currentStage: null,
          percent: 100,
          completedStages: PHASES.map(p => p.key),
        }));
      }
    };

    window.addEventListener('produce-progress', handler);
    return () => window.removeEventListener('produce-progress', handler);
  }, [meetingId]);

  const reset = () => setState({
    currentStage: null, stageMessage: '', percent: 0, completedStages: [], error: null,
  });

  return { ...state, reset };
}
