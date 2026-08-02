/**
 * 从 API 响应中安全提取数组。
 * 兼容两种格式：
 * - 裸数组: [item1, item2, ...]
 * - 包装对象: { key: [item1, item2, ...] }
 */
export function extractArray<T>(
  data: unknown,
  keys: string[] = []
): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    for (const key of keys) {
      if (Array.isArray(obj[key])) {
        return obj[key] as T[];
      }
    }
  }
  return [];
}
