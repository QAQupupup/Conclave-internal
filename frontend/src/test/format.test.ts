// 前端基础工具函数测试
// 后续可扩展为完整的组件/钩子测试集
import { describe, it, expect } from 'vitest';
import { escHtml, sanitizeRich, formatTime, formatMessageContent } from '../lib/format';

describe('escHtml', () => {
  it('应转义 HTML 特殊字符', () => {
    expect(escHtml('<script>alert(1)</script>')).toBe('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(escHtml('"quotes" & \'apostrophes\'')).toBe('&quot;quotes&quot; &amp; &#39;apostrophes&#39;');
  });

  it('应处理 null/undefined', () => {
    expect(escHtml(null)).toBe('');
    expect(escHtml(undefined)).toBe('');
  });
});

describe('sanitizeRich', () => {
  it('应保留白名单标签', () => {
    const html = '<p>Hello <strong>world</strong></p>';
    expect(sanitizeRich(html)).toContain('<p>');
    expect(sanitizeRich(html)).toContain('<strong>');
  });

  it('应移除非白名单标签但保留文本内容', () => {
    const html = '<p>safe</p><script>alert(1)</script>';
    const result = sanitizeRich(html);
    expect(result).not.toContain('<script>');
    expect(result).toContain('alert(1)');
  });

  it('应移除事件处理器属性', () => {
    const html = '<p onclick="alert(1)">click me</p>';
    const result = sanitizeRich(html);
    expect(result).not.toContain('onclick');
  });

  it('应阻止 javascript: 协议链接', () => {
    const html = '<a href="javascript:alert(1)">xss</a>';
    const result = sanitizeRich(html);
    expect(result).not.toContain('javascript:');
  });

  it('应阻止 data: 协议链接', () => {
    const html = '<a href="data:text/html,<script>alert(1)</script>">xss</a>';
    const result = sanitizeRich(html);
    expect(result).not.toContain('data:');
  });

  it('应允许 http/https/mailto 链接', () => {
    const html = '<a href="https://example.com">link</a>';
    expect(sanitizeRich(html)).toContain('href="https://example.com"');
  });

  it('应移除 style 属性', () => {
    const html = '<p style="color:red">text</p>';
    const result = sanitizeRich(html);
    expect(result).not.toContain('style=');
  });
});

describe('formatTime', () => {
  it('应格式化时间戳', () => {
    // 2026-01-01 12:34:56 UTC
    const ts = new Date('2026-01-01T12:34:56Z').getTime();
    const result = formatTime(ts);
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it('应处理空值', () => {
    expect(formatTime(undefined)).toBe('');
    expect(formatTime('')).toBe('');
  });
});

describe('formatMessageContent', () => {
  it('应转义 HTML 注入', () => {
    const result = formatMessageContent('<script>alert(1)</script>');
    expect(result).not.toContain('<script>');
    expect(result).toContain('&lt;script&gt;');
  });

  it('应转换 [fact] 标签', () => {
    const result = formatMessageContent('这是[fact]事实');
    expect(result).toContain('ck-tag-fact');
  });

  it('应转换 claim-xxxxxx 引用', () => {
    const result = formatMessageContent('引用 claim-abc123 内容');
    expect(result).toContain('ck-claim-ref');
    expect(result).toContain('data-claim-id="claim-abc123"');
  });

  it('应将换行转换为 <br>', () => {
    const result = formatMessageContent('line1\nline2');
    expect(result).toContain('line1<br>line2');
  });
});
