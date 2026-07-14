_EXTRACT_JS = """
() => {
    // 移除噪声 DOM 元素
    const noiseSelectors = [
        'script', 'style', 'noscript', 'iframe', 'svg', 'canvas',
        'nav', 'footer', 'header', 'aside',
        '.ad', '.ads', '.advertisement', '.sidebar',
        '.cookie-notice', '.popup', '.modal',
        '.share', '.social', '.comment', '.comments',
        '#comments', '#sidebar', '#footer',
    ];
    noiseSelectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => el.remove());
    });

    // 优先提取 article / main / [role=main] 标签
    const main = document.querySelector('article, main, [role="main"], .article-body, .post-content, .entry-content, .content');
    const target = main || document.body;
    if (!target) return '';

    // 提取纯文本，保留段落结构
    const text = target.innerText || target.textContent || '';
    // 压缩多余空白，限制 3000 字符
    return text.replace(/\\n{3,}/g, '\\n\\n').trim().substring(0, 3000);
}
"""