/**
 * 报告块渲染纯工具 —— 端点解析与溯源格式化。
 *
 * 从 report-block-renderer.tsx 抽出的原因：组件文件只允许导出组件
 * （react-refresh/only-export-components），纯函数必须独立成文件。
 */

export interface ApiEndpointDef {
  method: string;
  path: string;
  desc: string;
}

/**
 * trace 溯源安全格式化：后端可能给字符串或对象。
 * 对象优先取 stage/description/summary 字段，否则 JSON 化，避免 "[object Object]"。
 */
export function formatTrace(trace: unknown): string | null {
  if (trace == null) return null;
  if (typeof trace === 'string') return trace.trim() || null;
  if (typeof trace === 'object') {
    const t = trace as Record<string, unknown>;
    const parts = [t.stage, t.description, t.summary, t.message]
      .filter((v): v is string => typeof v === 'string' && v.trim() !== '');
    if (parts.length > 0) return parts.join(' · ');
    try {
      const s = JSON.stringify(trace);
      return s && s !== '{}' ? s : null;
    } catch {
      return null;
    }
  }
  return String(trace);
}

/** 解析 "GET /api/users - 获取用户列表" 形式的端点字符串 */
export function parseApiEndpoint(raw: string): ApiEndpointDef {
  const trimmed = raw.trim();
  const spaceIdx = trimmed.indexOf(' ');
  if (spaceIdx === -1) return { method: '', path: trimmed, desc: '' };
  const maybeMethod = trimmed.slice(0, spaceIdx);
  const isMethod = /^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$/i.test(maybeMethod);
  const rest = isMethod ? trimmed.slice(spaceIdx + 1) : trimmed;
  const method = isMethod ? maybeMethod.toUpperCase() : '';
  const dashIdx = rest.indexOf(' - ');
  if (dashIdx === -1) return { method, path: rest.trim(), desc: '' };
  return { method, path: rest.slice(0, dashIdx).trim(), desc: rest.slice(dashIdx + 3).trim() };
}
