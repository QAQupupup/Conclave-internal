/**
 * normalizeMarkdown 单元测试
 *
 * 覆盖场景：
 * 1. 干净内容原样通过（不引入回归）
 * 2. 三个及以上连续换行压缩为两个
 * 3. 首尾空白去除
 * 4. 空列表项移除（- / * / + / 1.），非空列表项保留
 * 5. 空引用行移除，带内容的引用保留
 * 6. 围栏代码块内部原样保留（不误删代码中形似空列表项的行）
 * 7. 空字符串 / 纯空白输入返回空字符串
 * 8. 幂等性：二次归一化结果不变
 * 9. 边界：--- / *** 水平分隔线不被误删
 * 10. 换行归一：CRLF / 孤立 CR → LF（含围栏代码块内部）
 */
import { describe, it, expect } from 'vitest';
import { normalizeMarkdown } from '@/lib/markdown-normalize';

describe('normalizeMarkdown', () => {
  it('干净内容原样通过', () => {
    const input = '# 标题\n\n第一段。\n\n第二段。';
    expect(normalizeMarkdown(input)).toBe(input);
  });

  it('三个及以上连续换行压缩为两个', () => {
    expect(normalizeMarkdown('a\n\n\n\nb')).toBe('a\n\nb');
    expect(normalizeMarkdown('a\n\n\nb')).toBe('a\n\nb');
    // 两个换行（一个空行）是合法段落分隔，保留
    expect(normalizeMarkdown('a\n\nb')).toBe('a\n\nb');
  });

  it('去除首尾空白', () => {
    expect(normalizeMarkdown('  \n hello \n\n  ')).toBe('hello');
  });

  it('移除空无序列表项，保留非空项', () => {
    const input = '- 甲\n-\n- 乙\n*  \n+ 丙';
    expect(normalizeMarkdown(input)).toBe('- 甲\n- 乙\n+ 丙');
  });

  it('移除空有序列表项，保留非空项', () => {
    const input = '1. 甲\n2.\n3. 乙';
    expect(normalizeMarkdown(input)).toBe('1. 甲\n3. 乙');
  });

  it('移除空引用行，保留带内容的引用', () => {
    const input = '> 有内容\n>\n>  \n> 还有内容';
    expect(normalizeMarkdown(input)).toBe('> 有内容\n> 还有内容');
  });

  it('围栏代码块内部原样保留', () => {
    const code = '```\n-\n1.\n>\n```';
    const input = `前文\n\n${code}\n\n后文`;
    expect(normalizeMarkdown(input)).toBe(input);
  });

  it('空字符串与纯空白输入返回空字符串', () => {
    expect(normalizeMarkdown('')).toBe('');
    expect(normalizeMarkdown('   \n\n  ')).toBe('');
  });

  it('幂等：二次归一化结果不变', () => {
    const input = '\n\n# 标题\n\n\n\n- 甲\n-\n\n> \n正文\n\n\n';
    const once = normalizeMarkdown(input);
    expect(normalizeMarkdown(once)).toBe(once);
  });

  it('水平分隔线 --- 与 *** 不被误删', () => {
    const input = '上段\n\n---\n\n下段';
    expect(normalizeMarkdown(input)).toBe(input);
    const input2 = '上段\n\n***\n\n下段';
    expect(normalizeMarkdown(input2)).toBe(input2);
  });

  it('移除空列表项后不叠加出多余空行', () => {
    const input = '段落一\n\n-\n\n段落二';
    expect(normalizeMarkdown(input)).toBe('段落一\n\n段落二');
  });

  it('CRLF 换行归一为 LF', () => {
    expect(normalizeMarkdown('甲\r\n乙')).toBe('甲\n乙');
    // CRLF 段落分隔归一后仍是单个空行
    expect(normalizeMarkdown('甲\r\n\r\n乙')).toBe('甲\n\n乙');
  });

  it('孤立 CR 归一为 LF', () => {
    expect(normalizeMarkdown('甲\r乙')).toBe('甲\n乙');
  });

  it('CRLF 归一在围栏代码块内部同样生效', () => {
    const input = '前文\r\n\r\n```\r\nline1\r\nline2\r\n```\r\n\r\n后文';
    expect(normalizeMarkdown(input)).toBe('前文\n\n```\nline1\nline2\n```\n\n后文');
  });

  it('CRLF 输入幂等：二次归一化结果不变', () => {
    const input = '甲\r\n\r\n\r\n乙\r\n-\r\n- 丙';
    const once = normalizeMarkdown(input);
    expect(normalizeMarkdown(once)).toBe(once);
  });
});
