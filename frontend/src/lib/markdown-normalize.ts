/**
 * Markdown 归一化：在渲染前清理 LLM 输出的格式噪声，
 * 使排版节奏（段落间距、空行）稳定可预期。
 *
 * 规则：
 * 0. 换行统一为 LF：CRLF / 孤立 CR → \n（Windows 换行在 Markdown
 *    解析与 <br> 断行中会产生不可见噪声，全链路含代码块内部一并归一）；
 * 1. 去除首尾空白；
 * 2. 三个及以上连续换行压缩为两个（保留段落分隔，消灭多余空段）；
 * 3. 移除空列表项与空引用行（无内容的 - / * / + / 1. / > 行）；
 * 4. 围栏代码块（``` / ~~~）内部除换行归一外原样保留，不做其他处理。
 *
 * 纯函数且幂等：normalizeMarkdown(normalizeMarkdown(x)) === normalizeMarkdown(x)。
 * 标题层级压平不由本函数负责，而由排版密度上下文（prose-stream）的 CSS 承担，
 * 避免双重机制漂移。
 */
export function normalizeMarkdown(content: string): string {
  if (!content) return '';
  // 换行归一：CRLF / 孤立 CR → LF（\r\n 必须先于孤立 \r 处理）
  const unified = content.replace(/\r\n?/g, '\n');
  // 按围栏代码块切分（捕获组保留代码块片段），仅处理代码块之外的文本
  const parts = unified.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/g);
  const normalized = parts
    .map((part) => {
      if (part.startsWith('```') || part.startsWith('~~~')) return part;
      let out = part.replace(/\n{3,}/g, '\n\n');
      // 空列表项：行内仅有 - / * / + / 1. 标记（排除 --- / *** 分隔线）；
      // 连同尾随换行一并移除，避免留下空行
      out = out.replace(/^[ \t]*(?:[-*+]|\d+\.)[ \t]*$\n?/gm, '');
      // 空引用行：移除后相邻引用行仍属同一引用块
      out = out.replace(/^[ \t]*>[ \t]*$\n?/gm, '');
      // 清理移除后可能叠加出的连续空行
      out = out.replace(/\n{3,}/g, '\n\n');
      return out;
    })
    .join('');
  return normalized.trim();
}
