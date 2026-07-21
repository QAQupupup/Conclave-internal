_CHUNK_EXTRACT_JS = """
() => {
    // 1. 移除噪声元素（注意：iframe 不移除，单独处理）
    const noiseSelectors = [
        'script', 'style', 'noscript', 'svg', 'canvas',
        'nav', 'footer', 'header', 'aside',
        '.ad', '.ads', '.advertisement', '.sidebar',
        '.cookie-notice', '.popup', '.modal',
        '.share', '.social',
    ];
    noiseSelectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => el.remove());
    });

    // 2. 定位主内容容器（优先级从高到低）
    //    修复 docs.python.org 侧边栏被当主内容的问题：
    //    article > main > [role=main] > ID/class 内容区 > body
    //    Python 文档用的是 div.body + div.section，不是 article/main
    const contentSelectors = [
        'article',
        'main',
        '[role="main"]',
        '.article-body', '.post-content', '.entry-content',
        '.content', '.document-body',
        'div[role="main"]',
        '#content', '#main-content', '#main',
        '.body', 'div.body',  // Python 文档 / Sphinx
        'div.section',
    ];
    let root = null;
    for (const sel of contentSelectors) {
        const el = document.querySelector(sel);
        // 候选元素必须包含足够文本（避免命中空容器或导航条）
        if (el && el.innerText && el.innerText.trim().length > 200) {
            root = el;
            break;
        }
    }
    root = root || document.body;
    if (!root) return { chunks: [], fallback: true, ugc_count: 0 };

    // 3. 标记 UGC 元素（Claude #5：chunk-level tier 继承冲突）
    const ugcSelectors = [
        '[class*="disqus"]', '[id*="disqus"]',
        '[class*="comment"]', '[id*="comment"]',
        '[class*="user-content"]', '[class*="community-note"]',
        '[class*="user_notes"]', '[class*="reader-feedback"]',
        '.feedback', '.discussion', '[class*="forum-post"]',
    ];
    let ugcCount = 0;
    ugcSelectors.forEach(sel => {
        root.querySelectorAll(sel).forEach(el => {
            el.setAttribute('data-ugc', 'true');
            ugcCount++;
        });
    });

    // 4. 配置
    const MIN_CHARS = 200;
    const MAX_CHARS = 2000;

    // 5. 递归遍历 DOM，按 heading 分块
    const chunks = [];
    let path = [];
    let currentText = '';
    let hasHeadings = false;

    function flush() {
        const t = currentText.trim();
        if (t.length >= MIN_CHARS) {
            chunks.push({
                heading_path: path.map(p => p.text).join(' > '),
                heading_level: path.length > 0 ? path[path.length - 1].level : 0,
                text: t.substring(0, MAX_CHARS),
                is_ugc: false,
            });
        }
        currentText = '';
    }

    function walk(node) {
        for (const child of node.childNodes) {
            if (child.nodeType === 3) {
                const t = child.textContent.trim();
                if (t) currentText += (currentText ? ' ' : '') + t;
            } else if (child.nodeType === 1) {
                if (child.getAttribute && child.getAttribute('data-ugc') === 'true') continue;

                const tag = child.tagName;

                // iframe 处理：尝试提取同源 iframe 内容
                if (tag === 'IFRAME') {
                    try {
                        const doc = child.contentDocument || child.contentWindow.document;
                        if (doc && doc.body) {
                            // 递归遍历 iframe 内部 DOM
                            walk(doc.body);
                        }
                    } catch(e) {
                        // 跨域 iframe 无法访问 contentDocument，跳过
                    }
                    continue;
                }

                const match = tag.match(/^H([1-6])$/);

                if (match) {
                    hasHeadings = true;
                    flush();
                    const level = parseInt(match[1]);
                    const hText = (child.textContent || '').trim();
                    while (path.length > 0 && path[path.length - 1].level >= level) {
                        path.pop();
                    }
                    path.push({ level, text: hText });
                } else {
                    walk(child);
                    if (currentText.length > MAX_CHARS) flush();
                }
            }
        }
    }

    walk(root);
    flush();

    // 6. 合并小段
    const merged = [];
    for (const chunk of chunks) {
        if (merged.length > 0 && chunk.text.length < MIN_CHARS) {
            merged[merged.length - 1].text += '\\n\\n' + chunk.text;
        } else {
            merged.push(chunk);
        }
    }

    // 7. 如果主内容区无有效分块，尝试遍历所有同源 iframe
    if (merged.length === 0) {
        const iframes = document.querySelectorAll('iframe');
        iframes.forEach(iframe => {
            try {
                const doc = iframe.contentDocument || iframe.contentWindow.document;
                if (doc && doc.body && doc.body.innerText && doc.body.innerText.trim().length > 200) {
                    walk(doc.body);
                    flush();
                }
            } catch(e) {}
        });
        // 再次合并
        const merged2 = [];
        for (const chunk of chunks) {
            if (merged2.length > 0 && chunk.text.length < MIN_CHARS) {
                merged2[merged2.length - 1].text += '\\n\\n' + chunk.text;
            } else {
                merged2.push(chunk);
            }
        }
        return {
            chunks: merged2,
            fallback: !hasHeadings,
            ugc_count: ugcCount,
            iframe_fallback: true,
        };
    }

    return {
        chunks: merged,
        fallback: !hasHeadings,
        ugc_count: ugcCount,
        iframe_fallback: false,
    };
}
"""
