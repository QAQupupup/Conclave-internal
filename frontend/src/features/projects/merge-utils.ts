/**
 * 议题合入工具函数（ADR-017 D11）。
 *
 * 独立于视图层，供 MergeDialog 与测试复用
 * （react-refresh/only-export-components：组件文件不得混导非组件）。
 */
import { ApiError } from '@/lib/api';

/**
 * 从合入执行错误中提取冲突文件清单。
 *
 * 后端合入冲突 → 409，全局错误格式 `{"error": {code, message, details}}`，
 * 冲突清单在 `error.details.conflicts`；兜底兼容 FastAPI 原生 dict detail。
 * 非 ApiError 或结构不符 → 空清单。
 */
export function extractMergeConflicts(err: unknown): string[] {
  if (!(err instanceof ApiError)) return [];
  const body = err.detail as
    | { error?: { details?: { conflicts?: unknown } }; detail?: { conflicts?: unknown } }
    | undefined;
  const fromGlobal = body?.error?.details?.conflicts;
  if (Array.isArray(fromGlobal)) return fromGlobal.filter((f): f is string => typeof f === 'string');
  const fromDetail = body?.detail?.conflicts;
  if (Array.isArray(fromDetail)) return fromDetail.filter((f): f is string => typeof f === 'string');
  return [];
}
