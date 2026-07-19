_JSONLD_EXTRACT_JS = """
() => {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    const entries = [];
    scripts.forEach(s => {
        try {
            const data = JSON.parse(s.textContent);
            if (Array.isArray(data)) {
                entries.push(...data.filter(d => d && typeof d === 'object'));
            } else if (data && typeof data === 'object') {
                // @graph 展开（多实体页面）
                if (Array.isArray(data['@graph'])) {
                    entries.push(...data['@graph'].filter(d => d && typeof d === 'object'));
                } else {
                    entries.push(data);
                }
            }
        } catch(e) {}
    });
    // 从所有条目中提取关键 provenance 字段
    let publisher = null, author = null, datePublished = null, dateModified = null, type = null;
    for (const e of entries) {
        if (!publisher) {
            publisher = (e.publisher && (e.publisher.name || e.publisher)) || null;
        }
        if (!author) {
            author = (e.author && (e.author.name || e.author)) || null;
        }
        if (!datePublished) datePublished = e.datePublished || null;
        if (!dateModified) dateModified = e.dateModified || null;
        if (!type) type = e['@type'] || null;
    }
    return {
        publisher: publisher,
        author: author,
        datePublished: datePublished,
        dateModified: dateModified,
        type: type,
        entry_count: entries.length,
    };
}
"""
