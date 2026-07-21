/* Conclave 格式化与安全工具 — ported from app.html */

/** 转义纯文本（用于属性上下文或拼接 HTML 字符串） */
export function escHtml(s: unknown): string {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const RICH_TAG_WHITELIST = new Set([
  'P', 'STRONG', 'EM', 'B', 'I', 'BR', 'UL', 'OL', 'LI',
  'CODE', 'PRE', 'BLOCKQUOTE', 'H3', 'H4', 'SPAN', 'A',
]);
const RICH_ATTR_WHITELIST = new Set(['HREF', 'CLASS']);

/**
 * 富文本白名单 sanitize：消息内容等本就含 <p>/<strong> 的场景。
 * 允许的标签保留为真正的 HTML 元素（渲染生效），其余标签转义为纯文本；
 * 危险属性（on*、style、javascript:）一律移除。
 * 文本节点上应用 Conclave 语义标记（[fact]/claim-xxx 等）。
 * 返回可安全注入 innerHTML 的 HTML 字符串。
 */
export function sanitizeRich(html: string): string {
  if (!html) return '';
  // 用 DOM 解析原始 HTML，让 <p>/<strong> 等成为真正的元素节点
  const tmp = document.createElement('div');
  tmp.innerHTML = html;

  const walk = (node: Node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element;
      const tag = el.nodeName;
      if (!RICH_TAG_WHITELIST.has(tag)) {
        // 非白名单标签：提取纯文本内容替换（保持内容，去掉标签壳）
        const text = document.createTextNode(el.textContent || '');
        el.replaceWith(text);
        return;
      }
      // 白名单标签：过滤危险属性
      [...el.attributes].forEach((attr) => {
        const name = attr.name.toLowerCase();
        const val = (attr.value || '').trim();
        if (name.startsWith('on') || name === 'style' || name === 'srcset') {
          el.removeAttribute(attr.name);
        } else if (name === 'href' || name === 'src') {
          // [前端审查修复] 仅允许安全协议，阻止 javascript:/data:/vbscript:/blob: 等
          const lower = val.toLowerCase().replace(/\s+/g, '');
          const isSafe =
            val.startsWith('#') ||
            val.startsWith('/') ||
            /^https?:\/\//i.test(val) ||
            /^mailto:/i.test(val) ||
            /^tel:/i.test(val);
          // 空 href 允许（用于按钮样式的 <a>）
          if (val !== '' && !isSafe) {
            el.removeAttribute(attr.name);
          }
        } else if (!RICH_ATTR_WHITELIST.has(attr.name.toUpperCase())) {
          el.removeAttribute(attr.name);
        }
      });
    } else if (node.nodeType === Node.TEXT_NODE) {
      // 文本节点：应用 Conclave 语义标记（[fact]/claim-xxx/[risk:x] 等）
      // formatMessageContent 内部会 escHtml，安全无注入风险
      const text = node.textContent || '';
      if (text) {
        const formatted = formatMessageContent(text);
        // 若有 Conclave 标记被替换（结果与纯转义不同），用新节点替换
        if (formatted !== escHtml(text)) {
          const wrapper = document.createElement('span');
          wrapper.innerHTML = formatted;
          const parent = node.parentNode;
          if (parent) {
            while (wrapper.firstChild) {
              parent.insertBefore(wrapper.firstChild, node);
            }
            parent.removeChild(node);
          }
        }
      }
    }
    if (node.childNodes && node.childNodes.length) {
      [...node.childNodes].forEach(walk);
    }
  };
  [...tmp.childNodes].forEach(walk);
  return tmp.innerHTML;
}

/**
 * 解析 Conclave 语义标记为美观的 HTML 标签。
 * 处理的标记：
 *   [fact]        → 绿色"事实"标签
 *   [assumption]  → 蓝色"假设"标签
 *   [constraint]  → 橙色"约束"标签
 *   [meta]        → 灰色元信息（单独成行，缩小字号）
 *   [doc:xxx]     → 文档引用链接样式
 *   [risk:low/medium/high] → 风险等级标签
 *   claim-xxxxxx  → 等宽论断引用标签
 *   [主持人]       → 角色前缀高亮
 *   数字序号 "1. " → 有序列表样式
 */
const TAG_LABELS: Record<string, { label: string; cls: string }> = {
  fact: { label: '事实', cls: 'ck-tag-fact' },
  assumption: { label: '假设', cls: 'ck-tag-assumption' },
  constraint: { label: '约束', cls: 'ck-tag-constraint' },
};

export function formatMessageContent(text: string): string {
  if (!text) return '';
  // 先转义 HTML 防注入
  let s = escHtml(text);

  // [risk:low] / [risk:medium] / [risk:high] → 风险标签
  s = s.replace(/\[risk:(low|medium|high)\]/g, (_, level) => {
    const labels: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' };
    return `<span class="ck-tag ck-tag-risk ck-tag-risk-${level}">${labels[level]}</span>`;
  });

  // [doc:xxx] → 文档引用
  s = s.replace(/\[doc:([^\]]+)\]/g, (_, doc) => `<span class="ck-doc-ref">${escHtml(doc)}</span>`);

  // [meta] → 元信息标记（单独成行时缩小）
  s = s.replace(/\[meta\]/g, '<span class="ck-meta">元信息</span>');

  // [fact] / [assumption] / [constraint] → 语义标签
  s = s.replace(/\[(fact|assumption|constraint)\]/g, (_, tag) => {
    const info = TAG_LABELS[tag];
    return info ? `<span class="ck-tag ${info.cls}">${info.label}</span>` : '';
  });

  // [主持人] / [系统] 等方括号角色前缀 → 高亮
  s = s.replace(/^\[([^\]]{2,8})\]\s*/g, '<span class="ck-role-prefix">$1</span> ');

  // claim-xxxxxx → 论断引用标签（可点击溯源）
  s = s.replace(/(claim-[a-f0-9]{6,12})/g, '<span class="ck-claim-ref" data-claim-id="$1">$1</span>');

  // 换行处理
  s = s.replace(/\n/g, '<br>');

  return s;
}

/** 格式化时间戳为 HH:MM:SS */
export function formatTime(ts: number | string | undefined): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

/** Dockerfile 语法高亮（返回 HTML 字符串） */
export function highlightDockerfile(text: string): string {
  return text.split('\n').map((line) => {
    if (line.match(/^(FROM|WORKDIR|COPY|RUN|EXPOSE|CMD)/)) {
      const m = line.match(/^(\w+)(\s+)(.*)$/);
      if (m) return `<span class="ck-key">${m[1]}</span>${m[2]}<span class="ck-str">${escHtml(m[3])}</span>`;
    }
    return escHtml(line);
  }).join('\n');
}

/** YAML 语法高亮（返回 HTML 字符串） */
export function highlightYamlReport(text: string): string {
  return text.split('\n').map((line) => {
    if (line.match(/^\s*#/)) return `<span class="ck-com">${escHtml(line)}</span>`;
    const kv = line.match(/^(\s*)([\w.-]+):(.*)$/);
    if (kv) {
      const val = kv[3];
      const strMatch = val.match(/^(\s*)("[^"]*"|'[^']*')(.*)$/);
      const valHtml = strMatch
        ? `${strMatch[1]}<span class="ck-str">${escHtml(strMatch[2])}</span>${escHtml(strMatch[3])}`
        : escHtml(val);
      return `${kv[1]}<span class="ck-key">${kv[2]}</span>:${valHtml}`;
    }
    return escHtml(line);
  }).join('\n');
}

/** 中文章节序号 */
export function cnSectionTitle(title: string, i: number): string {
  const cn = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];
  return `${cn[i] || i + 1} ${title}`;
}
