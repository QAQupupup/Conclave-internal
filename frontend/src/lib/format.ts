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
const RICH_ATTR_WHITELIST = new Set(['HREF']);

/**
 * 富文本白名单 sanitize：消息内容等本就含 <p>/<strong> 的场景。
 * 允许的标签仅保留，其余标签转义；危险属性（on*、style、javascript:）一律移除。
 * 返回可安全注入 innerHTML 的 HTML 字符串。
 */
export function sanitizeRich(html: string): string {
  if (!html) return '';
  const tmp = document.createElement('div');
  tmp.innerHTML = String(html);
  const walk = (node: Node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element;
      const tag = el.nodeName;
      if (!RICH_TAG_WHITELIST.has(tag)) {
        const text = document.createTextNode(el.textContent || '');
        el.replaceWith(text);
        return;
      }
      [...el.attributes].forEach((attr) => {
        const name = attr.name.toLowerCase();
        const val = attr.value || '';
        if (name.startsWith('on') || name === 'style' || name === 'srcset') {
          el.removeAttribute(attr.name);
        } else if ((name === 'href' || name === 'src') && /^\s*javascript:/i.test(val)) {
          el.removeAttribute(attr.name);
        } else if (!RICH_ATTR_WHITELIST.has(attr.name.toUpperCase())) {
          el.removeAttribute(attr.name);
        }
      });
    }
    if (node.childNodes && node.childNodes.length) {
      [...node.childNodes].forEach(walk);
    }
  };
  [...tmp.childNodes].forEach(walk);
  return tmp.innerHTML;
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
