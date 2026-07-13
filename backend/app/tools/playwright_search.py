# 自建 Web Search：Playwright 无头浏览器方案
#
# 架构：
#   Bing 搜索 → Playwright 渲染 Top-K 页面 → 提取正文
#
# 反检测原理（v2 增强）：
#   1. CDP 注入 ≠ DevTools 面板：page.evaluate() 通过 Chrome DevTools Protocol
#      直接在 V8 引擎执行 JS，不经过 DevTools UI。基于 debugger 语句、
#      console 时差的反调试手段完全无效。
#   2. 指纹覆盖 v2：WebGL/Canvas 指纹随机化、WebRTC 防泄漏、硬件参数伪装、
#      媒体设备伪装、Battery API 伪装、chrome.runtime 完整模拟、CDP 特征清除。
#   3. Cookie 持久化：成功访问的页面 Cookie 保存到磁盘，下次访问复用，
#      模拟真实用户长期会话，大幅降低验证码触发率。
#   4. CAPTCHA 主动检测：识别 Cloudflare/reCAPTCHA/hCaptcha/极验/腾讯/百度等验证码，
#      快速跳过（5秒内）而非盲目等待15秒超时；被拦截域名5分钟冷却。
#   5. 拟人化行为：随机延迟、Accept/Sec-Fetch-* 真实请求头、模拟滚动、
#      device_scale_factor 匹配高分屏。
#   6. 行为反爬（Cloudflare/reCAPTCHA）：无法自动破解滑块/点选验证码，
#      检测到后快速跳过并标记域名冷却，不崩溃。
#   7. 异常隔离：每个页面在独立 context 中执行，单页失败不影响其他页面。
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


from .domain_registry import (
    match_entity,
    rank_by_tier,
    tag_url,
)

logger = logging.getLogger("app.tools.playwright_search")

# ---------- SSRF 防护 ----------
# P0-1: 完整 SSRF 校验（Claude 交叉评审指出 redirect-hop + DNS rebinding 风险）
_BLOCKED_SCHEMES = {"file", "data", "javascript", "vbscript", "about", "blob"}


def _is_safe_url(url: str) -> tuple[bool, str]:
    """校验 URL 安全性（初始 URL 检查）

    检查项：
    1. scheme 必须是 http/https（拒绝 file://、data: 等）
    2. 拒绝私网 IP / localhost / 元数据端点
    3. 检测 userinfo 绕过（http://allowed@evil.com）

    注意：此函数仅检查初始 URL，redirect-hop 验证在 goto 后用 response.url 再次调用。
    DNS rebinding 的完整防护需要 page.on("request") 钩子，此处先做基础防护。
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL 解析失败"

    if parsed.scheme not in ("http", "https"):
        return False, f"scheme '{parsed.scheme}' 不允许（仅 http/https）"

    if parsed.scheme in _BLOCKED_SCHEMES:
        return False, f"scheme '{parsed.scheme}' 被禁止"

    hostname = parsed.hostname or ""
    if not hostname:
        return False, "URL 缺少 hostname"

    # 私网 IP 拒绝
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, f"私网/保留地址 '{hostname}' 被拒绝"
    except ValueError:
        if hostname in ("localhost", "metadata.google.internal", "metadata"):
            return False, f"内网/元数据端点 '{hostname}' 被拒绝"

    # userinfo 绕过检测（http://safe.com@evil.com → hostname=evil.com 但 netloc 含 @）
    # 只要 URL 中存在 userinfo 部分，就拒绝（合法网页极少使用 userinfo）
    if "@" in (parsed.netloc or ""):
        userinfo_part = parsed.netloc.rsplit("@", 1)[0]
        if userinfo_part:  # @ 前有内容 = 存在 userinfo
            return False, "URL 包含 userinfo 部分，疑似绕过攻击"

    return True, "ok"


# ---------- 反检测脚本（增强版 v2） ----------
# 在页面任何 JS 执行前注入（addInitScript），覆盖自动化指纹
# v2 增强：WebGL/Canvas 指纹随机化、WebRTC 防泄漏、硬件参数伪装、
#          媒体设备枚举伪装、Battery API 伪装、Touch 事件支持
_STEALTH_JS = """
// ===== 0. 工具函数 =====
const randInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const randChoice = (arr) => arr[Math.floor(Math.random() * arr.length)];

// 稳定的"指纹"种子（同一 context 内一致，跨 context 随机）
const fpSeed = Math.floor(Math.random() * 100000);

// ===== 1. 覆盖 navigator.webdriver（Playwright 默认为 true）=====
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// ===== 2. 模拟真实浏览器插件列表 =====
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: '' },
        ];
        const pluginArray = Object.create(PluginArray.prototype);
        for (let i = 0; i < plugins.length; i++) {
            Object.defineProperty(pluginArray, i, { value: plugins[i] });
        }
        Object.defineProperty(pluginArray, 'length', { value: plugins.length });
        pluginArray.refresh = () => {};
        pluginArray.item = (i) => plugins[i] || null;
        pluginArray.namedItem = (name) => plugins.find(p => p.name === name) || null;
        return pluginArray;
    },
    configurable: true,
});

// ===== 3. 覆盖 navigator.languages =====
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
    configurable: true,
});

// ===== 4. 覆盖 navigator.platform（匹配 User-Agent）=====
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
    configurable: true,
});

// ===== 5. 覆盖 navigator.permissions.query =====
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission, onchange: null })
        : originalQuery(parameters)
);

// ===== 6. 遮挡 window.chrome =====
if (!window.chrome) {
    window.chrome = {
        runtime: {
            OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
            PlatformArch: { ARM: 'arm', ARM64: 'arm64', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
            PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
            PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
            RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
            connect: () => {},
            sendMessage: () => {},
        },
        loadTimes: function() {
            return { commitLoadTime: Date.now()/1000, connectionInfo: 'h2', finishDocumentLoadTime: Date.now()/1000, finishLoadTime: Date.now()/1000, firstPaintAfterLoadTime: 0, firstPaintTime: Date.now()/1000, navigationType: 'Other', npnNegotiatedProtocol: 'h2', requestTime: Date.now()/1000, startLoadTime: Date.now()/1000, wasAlternateProtocolAvailable: false, wasFetchedViaSpdy: true, wasNpnNegotiated: true };
        },
        csi: function() {
            return { onloadT: Date.now(), pageT: 50 + Math.random()*100, startE: Date.now(), tran: 15 };
        },
        app: {
            isInstalled: false,
            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
            getDetails: () => null,
            getIsInstalled: () => false,
            installState: () => 'not_installed',
            runningState: () => 'cannot_run',
        },
    };
}

// ===== 7. 覆盖 navigator.connection =====
if (navigator.connection) {
    Object.defineProperty(navigator.connection, 'effectiveType', { get: () => '4g', configurable: true });
    Object.defineProperty(navigator.connection, 'rtt', { get: () => 50, configurable: true });
    Object.defineProperty(navigator.connection, 'downlink', { get: () => 10, configurable: true });
    Object.defineProperty(navigator.connection, 'saveData', { get: () => false, configurable: true });
}

// ===== 8. WebGL 指纹随机化 =====
const getParameterProxy = (target, key) => {
    return new Proxy(WebGLRenderingContext.prototype.getParameter, {
        apply: function(target, thisArg, args) {
            const param = args[0];
            // UNMASKED_VENDOR_WEBGL = 0x9245, UNMASKED_RENDERER_WEBGL = 0x9246
            if (param === 0x9245) return 'Google Inc. (NVIDIA)';
            if (param === 0x9246) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            // VERSION = 0x1F02, SHADING_LANGUAGE_VERSION = 0x8B8C
            if (param === 0x1F02) return 'WebGL 1.0 (OpenGL ES 2.0 Chromium)';
            if (param === 0x8B8C) return 'WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)';
            if (param === 0x1F01) return 0x20003; // NUM_EXTENSIONS
            return target.apply(thisArg, args);
        }
    })(key);
};

// WebGL2
if (window.WebGL2RenderingContext) {
    const origGetParam2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {
        if (param === 0x9245) return 'Google Inc. (NVIDIA)';
        if (param === 0x9246) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return origGetParam2.apply(this, [param]);
    };
}
// WebGL1
if (window.WebGLRenderingContext) {
    const origGetParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 0x9245) return 'Google Inc. (NVIDIA)';
        if (param === 0x9246) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return origGetParam.apply(this, [param]);
    };
    const origGetExt = WebGLRenderingContext.prototype.getExtension;
    WebGLRenderingContext.prototype.getExtension = function(name) {
        if (name === 'WEBGL_debug_renderer_info') return null;
        return origGetExt.apply(this, [name]);
    };
}

// ===== 9. Canvas 指纹干扰（微小噪声，不影响渲染）=====
const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    if (type === 'image/png' && this.width > 16 && this.height > 16) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imgData = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imgData.data.length; i += 4) {
                // 极微小的噪声（±1），不影响视觉，改变 fingerprint hash
                imgData.data[i] = imgData.data[i] + (fpSeed % 3) - 1;
                imgData.data[i+1] = imgData.data[i+1] + (fpSeed % 2);
                imgData.data[i+2] = imgData.data[i+2] + ((fpSeed+1) % 3) - 1;
            }
            ctx.putImageData(imgData, 0, 0);
        }
    }
    return origToDataURL.apply(this, arguments);
};

// ===== 10. WebRTC 防泄漏（不暴露真实内网 IP）=====
delete window.RTCPeerConnection;
delete window.webkitRTCPeerConnection;
delete window.mozRTCPeerConnection;

// ===== 11. 硬件参数伪装 =====
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 16, configurable: true });
Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0, configurable: true });

// ===== 12. Battery API 伪装 =====
if (navigator.getBattery) {
    navigator.getBattery = () => Promise.resolve({
        charging: true,
        chargingTime: 0,
        dischargingTime: Infinity,
        level: 1.0,
        onchargingchange: null, onchargingtimechange: null,
        ondischargingtimechange: null, onlevelchange: null,
        addEventListener: () => {}, removeEventListener: () => {},
        dispatchEvent: () => true,
    });
}

// ===== 13. 媒体设备枚举伪装 =====
if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
    navigator.mediaDevices.enumerateDevices = () => Promise.resolve([
        { deviceId: 'default', kind: 'audioinput', label: 'Default - Microphone (Realtek Audio)', groupId: 'default' },
        { deviceId: 'communications', kind: 'audioinput', label: 'Communications - Microphone (Realtek Audio)', groupId: 'default' },
        { deviceId: 'default', kind: 'audiooutput', label: 'Default - Speakers (Realtek Audio)', groupId: 'default' },
        { deviceId: 'communications', kind: 'audiooutput', label: 'Communications - Speakers (Realtek Audio)', groupId: 'default' },
    ]);
}

// ===== 14. SpeechSynthesis 伪装（headless 下为空）=====
if (window.speechSynthesis) {
    const origGetVoices = window.speechSynthesis.getVoices;
    window.speechSynthesis.getVoices = () => {
        const voices = origGetVoices.call(window.speechSynthesis);
        if (voices.length === 0) {
            return [
                { voiceURI: 'Microsoft Huihui Desktop - Chinese (Simplified)', name: 'Microsoft Huihui Desktop - Chinese (Simplified)', lang: 'zh-CN', localService: true, default: true },
                { voiceURI: 'Microsoft Zira Desktop - English (United States)', name: 'Microsoft Zira Desktop - English (United States)', lang: 'en-US', localService: true, default: false },
            ];
        }
        return voices;
    };
}

// ===== 15. iframe contentWindow 检测 =====
const origAttachShadow = Element.prototype.attachShadow;
Element.prototype.attachShadow = function() { return origAttachShadow.apply(this, arguments); };

// ===== 16. 清除 CDP 特征（RuntimeEnabled 等）=====
// 某些站点检测 window.cdc_* 或 RuntimeEnabled 特征
Object.keys(window).forEach(key => {
    if (key.match(/^cdc_|^chrome-extension/)) {
        try { delete window[key]; } catch(e) {}
    }
});

// ===== 17. Notification 权限伪装 =====
if (window.Notification) {
    Object.defineProperty(Notification, 'permission', { get: () => 'default' });
}
"""

# 真实 User-Agent（避免 headless 标记）
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ---------- CAPTCHA 检测脚本 ----------
# 识别常见验证码/反爬页面特征，避免盲目等待超时
_CAPTCHA_DETECT_JS = """
() => {
    const url = window.location.href;
    const title = document.title || '';
    const bodyText = (document.body && document.body.innerText) ? document.body.innerText.substring(0, 2000) : '';
    const html = document.documentElement ? document.documentElement.outerHTML.substring(0, 5000) : '';

    const detect = [];

    // 1. Cloudflare 检测
    if (title.includes('Just a moment') || title.includes('Checking your browser') ||
        title.includes('Attention Required') || bodyText.includes('Checking your browser before') ||
        bodyText.includes('cf-browser-verification') || html.includes('cf-challenge') ||
        html.includes('turnstile') || html.includes('grecaptcha')) {
        detect.push('cloudflare');
    }

    // 2. reCAPTCHA 检测
    if (html.includes('google.com/recaptcha') || html.includes('g-recaptcha') ||
        html.includes('recaptcha_challenge') || document.querySelector('iframe[src*="recaptcha"]')) {
        detect.push('recaptcha');
    }

    // 3. hCaptcha 检测
    if (html.includes('hcaptcha.com') || html.includes('h-captcha') ||
        document.querySelector('iframe[src*="hcaptcha"]')) {
        detect.push('hcaptcha');
    }

    // 4. 极验(Geetest)滑块检测
    if (html.includes('gt_') && html.includes('challenge') ||
        html.includes('geetest') || html.includes('nc_1_n1z') ||
        html.includes('gee_') || document.querySelector('.geetest_holder, .gt_slider, [class*="geetest"]')) {
        detect.push('geetest_slider');
    }

    // 5. 腾讯防水墙检测
    if (html.includes('tcaptcha') || html.includes('captcha.qq.com') ||
        document.querySelector('#tcaptcha, iframe[src*="tcaptcha"]')) {
        detect.push('tencent_captcha');
    }

    // 6. Bing 人机验证
    if (url.includes('bing.com') && (
        bodyText.includes('verify you are human') ||
        bodyText.includes('我们需要验证') ||
        bodyText.includes('不是机器人') ||
        bodyText.includes('Help us protect') ||
        html.includes('captcha'))) {
        detect.push('bing_captcha');
    }

    // 7. 通用验证码关键词
    if (bodyText.match(/(captcha|verification|verify.{0,20}human|人机验证|验证码|滑块验证|安全验证)/i)) {
        // 排除误报（如页面正文提到"验证码"这个词但不是验证码页面）
        if (detect.length === 0) {
            // 额外检查：是否有 input 或 canvas 等验证码交互元素
            const hasCaptchaInput = document.querySelector('input[name*="captcha" i], img[src*="captcha" i], canvas[class*="captcha" i]');
            const shortBody = bodyText.length < 500; // 验证码页面通常内容很少
            if (hasCaptchaInput || shortBody) {
                detect.push('generic_captcha');
            }
        }
    }

    // 8. 百度安全验证
    if (url.includes('baidu.com') && (bodyText.includes('安全验证') || html.includes('wappass'))) {
        detect.push('baidu_verify');
    }

    return {
        detected: detect.length > 0,
        types: detect,
        title: title.substring(0, 100),
        url: url,
        body_length: bodyText.length,
    };
}
"""

# 页面内容提取 JS：移除噪声元素后提取正文
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

# schema.org JSON-LD 提取：从 <script type="application/ld+json"> 获取结构化元数据
# 官方/权威站点通常嵌入 JSON-LD（publisher, dateModified, author 等），
# 采集站/SEO 农场几乎不实现。比版权页脚启发式更可靠。
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

# Claim 粒度分块提取（Phase 1.5 — Claude Sonnet 5 建议 #4）
# 按 heading 结构分块，每块携带 heading_path 作为结构元数据。
# 处理两个失败模式（Claude 指出）：
#   - 无 heading 页面 → paragraph fallback（按段落聚类，保持 heading_path 元数据）
#   - heading 过多 → min-size merge（合并 < MIN_CHARS 的小段到前一段）
# UGC guard（Claude 建议 #5）：检测嵌入式评论/社区笔记，标记 is_ugc
# iframe 处理：不直接移除，而是递归提取 contentDocument 中的内容（同源 iframe）
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


class PlaywrightWebSearch:
    """自建 Web Search：Playwright 无头浏览器 + DuckDuckGo 搜索

    零 API 开销，页面动态渲染后提取正文。

    反检测策略：
    - CDP 注入 JS 不经过 DevTools 面板 → 反调试检测无效
    - addInitScript 在页面 JS 前覆盖自动化指纹
    - --disable-blink-features=AutomationControlled 禁用 Blink 自动化标记
    - 行为反爬站点（Cloudflare）超时跳过，不崩溃
    """

    name = "playwright_web_search"
    evidence_type = "web"

    def __init__(self) -> None:
        self._browser = None
        self._playwright = None
        self._browser_headed = False  # 标记浏览器当前是否以有头模式运行
        self._semaphore = asyncio.Semaphore(3)  # 并发页面数限制
        self._lock = asyncio.Lock()  # 浏览器初始化锁
        # Cookie/存储持久化：保存到数据目录，跨重启复用
        self._storage_state_path = os.path.join(
            os.environ.get("CONCLAVE_DATA_DIR", "/app/data"),
            "browser_storage_state.json"
        )
        self._captcha_blocked_domains: dict[str, float] = {}  # 域名 → 被阻时间，避免重复尝试
        logger.info("PlaywrightWebSearch 初始化: storage_state=%s", self._storage_state_path)

    async def _ensure_browser(self) -> None:
        """延迟初始化浏览器（首次搜索时启动，后续复用）

        值守模式下（guard.guard_mode=True）：
        - Chromium 以有头模式（headless=False）启动
        - 输出到 Xvfb 虚拟显示器（DISPLAY=:99）
        - 同时启动 x11vnc + websockify/noVNC 供用户通过 Web 介入
        非值守模式：headless=True，不启动 VNC。

        如果值守模式动态切换（headless ↔ headed），会自动重启浏览器。
        """
        # 检查当前需要的模式
        from app.tools.captcha_guard import get_captcha_guard
        guard = await get_captcha_guard()
        need_headed = guard.guard_mode

        # 如果浏览器已启动，检查模式是否匹配
        if self._browser is not None:
            if self._browser_headed == need_headed:
                return  # 模式匹配，复用现有浏览器
            # 模式不匹配，关闭旧浏览器，重新启动
            logger.info("CAPTCHA 值守模式切换（%s → %s），重启浏览器...",
                        "有头" if self._browser_headed else "无头",
                        "有头" if need_headed else "无头")
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        async with self._lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            headless = True
            launch_env: dict[str, str] = {}
            vnc_started = False

            if need_headed:
                # 尝试启动 VNC 环境
                try:
                    vnc_started = await guard.start_vnc()
                    if vnc_started:
                        headless = False
                        launch_env["DISPLAY"] = ":99"
                        logger.info("CAPTCHA 值守模式：以有头模式启动浏览器 (DISPLAY=:99)")
                    else:
                        logger.warning("CAPTCHA 值守模式开启但 VNC 环境不可用，仍使用 headless 模式")
                except Exception as e:
                    logger.warning("CAPTCHA 值守模式初始化失败: %s", str(e)[:100])

            mode_desc = "有头+VNC" if not headless else "headless"
            logger.info("启动 Playwright Chromium 浏览器 (%s)", mode_desc)
            self._playwright = await async_playwright().start()
            launch_args = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu" if headless else "",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--no-first-run",
                "--disable-default-apps",
                "--window-size=1280,800" if not headless else "--window-size=1920,1080",
            ]
            launch_args = [a for a in launch_args if a]

            if not headless:
                # 有头模式：添加远程调试端口
                launch_args.append("--remote-debugging-port=9222")

            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=launch_args,
                env=launch_env if launch_env else None,
            )
            self._browser_headed = not headless

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        """搜索流程：Bing 搜索 → Tier 重排 → Playwright 渲染 → Claim 粒度分块提取

        Phase 1.5 改进（Claude Sonnet 5 #4 + #5）：
        1. 每页从单 blob 改为 N 个 atomic claim（按 heading 分块）
        2. 每块携带 heading_path（h1 > h2 > h3）结构元数据
        3. UGC guard：嵌入评论/社区笔记降级为 C tier（不继承 S/A/B）
        4. 保留 Phase 1 的全部增强：Bing 排除、tier 重排、JSON-LD、signals 袋、staleness
        5. 新增：支持 language（zh-CN/en-US）、time_range（day/week/month/year）、country 参数

        Args:
            query: 搜索查询
            top_k: 最大结果数
            **kwargs:
                language: 搜索语言 (zh-CN/en-US，默认 zh-CN)
                time_range: 时间过滤 (day/week/month/year)
                country: 国家/地区代码 (CN/US等)

        返回格式（chunk-level evidence）：
        [{
            "evidence_id": "web-0",
            "quote": "atomic claim text...",
            "source": "web:docs.python.org",
            "url": "https://...",
            "domain": "docs.python.org",
            "source_tier": "S",
            "signals": { ... }
        }]
        """
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            return await asyncio.wait_for(
                self._do_search(query, top_k, fetched_at, **kwargs),
                timeout=60.0,  # P0-3: 整体超时 60s（Bing 重试 32s + 渲染 28s）
            )
        except asyncio.TimeoutError:
            logger.warning("Web Search 整体超时 60s: query=%s", query[:50])
            return []

    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        """直接抓取指定URL的内容，无需搜索

        Args:
            url: 要抓取的URL
            max_chars: 最大返回字符数

        Returns:
            {"url", "title", "content", "chunks", "source_tier", "signals", "error"}
        """
        from .domain_registry import tag_url
        fetched_at = datetime.now(timezone.utc).isoformat()

        # SSRF 校验
        safe, reason = _is_safe_url(url)
        if not safe:
            logger.warning("fetch_url SSRF拦截: url=%s reason=%s", url[:80], reason)
            return {"url": url, "title": "", "content": "", "chunks": [],
                    "source_tier": "D", "signals": {}, "error": reason}

        await self._ensure_browser()
        tier_info = tag_url(url)
        hostname = urlparse(url).hostname or "unknown"

        try:
            result = await asyncio.wait_for(
                self._fetch_and_extract(url, locale="zh-CN"),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            return {"url": url, "title": "", "content": "", "chunks": [],
                    "source_tier": tier_info["source_tier"], "signals": {}, "error": "timeout"}
        except Exception as e:
            return {"url": url, "title": "", "content": "", "chunks": [],
                    "source_tier": tier_info["source_tier"], "signals": {}, "error": str(e)[:200]}

        chunks = result.get("chunks", [])
        title = result.get("title", "")
        jsonld = result.get("jsonld", {})

        if not chunks:
            return {"url": url, "title": title, "content": "", "chunks": [],
                    "source_tier": tier_info["source_tier"],
                    "signals": {"page_title": title, "fetched_at": fetched_at},
                    "error": "no_content"}

        # 组装 content（拼接前几个 chunk 的文本）和 chunks 列表
        content_parts = []
        chunk_list = []
        total_chars = 0
        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "")
            chunk_list.append({
                "text": text[:max_chars],
                "heading_path": chunk.get("heading_path", ""),
                "heading_level": chunk.get("heading_level", 0),
                "is_ugc": chunk.get("is_ugc", False),
            })
            if total_chars < max_chars:
                content_parts.append(text)
                total_chars += len(text)

        content = "\n\n".join(content_parts)[:max_chars]

        return {
            "url": url,
            "title": title,
            "content": content,
            "chunks": chunk_list,
            "source_tier": tier_info["source_tier"],
            "signals": {
                "domain": hostname,
                "page_title": title,
                "fetched_at": fetched_at,
                "jsonld_publisher": jsonld.get("publisher"),
                "chunk_count": len(chunks),
                "is_official": tier_info["is_official"],
            },
            "error": None,
        }

    async def _do_search(self, query: str, top_k: int, fetched_at: str, **kwargs: Any) -> list[dict[str, Any]]:
        """搜索核心逻辑（被 search() 的 wait_for 包裹）

        Args:
            **kwargs: language, time_range, country
        """
        # 解析参数
        language = kwargs.get("language", "zh-CN")
        time_range = kwargs.get("time_range")
        country = kwargs.get("country", "CN" if language.startswith("zh") else "US")

        # locale 映射：zh-CN → 中文搜索，其他默认 en-US
        locale = language if language in ("zh-CN", "en-US", "zh-TW", "ja-JP") else "en-US"

        try:
            # 0. 实体匹配（零开销子串匹配，用于日志记录）
            entity = match_entity(query)
            if entity:
                logger.info("Web Search 实体匹配: query=%s → entity=%s", query[:50], entity)

            # 1. Bing 搜索获取 URL 列表（请求 3x 结果用于 tier 重排）
            fetch_count = min(top_k * 3, 15)
            urls = await self._search_ddg(query, fetch_count, locale=locale, time_range=time_range, country=country)
            if not urls:
                logger.warning("Bing 搜索无结果: query=%s", query[:50])
                return []

            # 2. 按 domain tier 重排（官方源优先）
            ranked_urls = rank_by_tier(urls)[:top_k]

            # 3. 确保浏览器已启动
            await self._ensure_browser()

            # 4. 并行渲染页面（并发限制）
            tasks = [self._fetch_and_extract(url, locale=locale) for url in ranked_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 5. 从 chunks 组装 evidence（每 chunk 一条 evidence）
            evidence: list[dict[str, Any]] = []
            ev_idx = 0
            for url, result in zip(ranked_urls, results):
                if isinstance(result, Exception):
                    logger.warning("页面提取失败: url=%s err=%s", url, str(result)[:100])
                    continue
                if not isinstance(result, dict):
                    continue

                chunks = result.get("chunks", [])
                if not chunks:
                    logger.debug("页面无有效分块，跳过: url=%s", url)
                    continue

                hostname = urlparse(url).hostname or "unknown"
                tier_info = tag_url(url)
                jsonld = result.get("jsonld", {})
                last_modified = result.get("last_modified")
                page_title = result.get("title", "")
                page_last_modified = last_modified or jsonld.get("dateModified")
                page_fallback = result.get("fallback", False)
                page_ugc_count = result.get("ugc_count", 0)

                # UGC tier downgrade（Claude #5）：
                # 嵌入评论/社区笔记的 chunk 不继承 S/A/B tier，降级为 C
                def _effective_tier(is_ugc: bool) -> str:
                    if is_ugc:
                        return "C"
                    return tier_info["source_tier"]

                # 限制每页最大 chunk 数，避免 evidence 爆炸（如 docs.python.org 85 chunks）
                max_chunks_per_page = 5
                for chunk_idx, chunk in enumerate(chunks[:max_chunks_per_page]):
                    chunk_ugc = chunk.get("is_ugc", False)
                    eff_tier = _effective_tier(chunk_ugc)

                    # P0-4: prompt injection 防御 — quote 用定界符包裹
                    # 让 LLM 能结构性区分"数据"与"指令"
                    raw_text = chunk.get("text", "")[:500]
                    quote_delimited = f"[EVIDENCE_DATA_BEGIN]{raw_text}[EVIDENCE_DATA_END]"

                    # A-4: content hash — 基于结构化 chunk 输出（heading_path + text），非 raw HTML
                    heading_path = chunk.get("heading_path", "")
                    content_hash = hashlib.sha256(
                        f"{heading_path}|{raw_text}".encode("utf-8")
                    ).hexdigest()[:16]

                    evidence.append({
                        "evidence_id": f"web-{ev_idx}",
                        "quote": quote_delimited,
                        "source": f"web:{hostname}",
                        "url": url,
                        "domain": hostname,
                        "content_hash": content_hash,
                        # 顶层 tier 向后兼容（用 effective_tier）
                        "source_tier": eff_tier,
                        # signals 袋 — 原始正交信号，agent 自行加权
                        "signals": {
                            # 页面级信号
                            "tier_static": tier_info["source_tier"],
                            "effective_tier": eff_tier,
                            "is_official": tier_info["is_official"],
                            "fetched_at": fetched_at,
                            "page_last_modified": page_last_modified,
                            "jsonld_publisher": jsonld.get("publisher"),
                            "jsonld_author": jsonld.get("author"),
                            "jsonld_date_published": jsonld.get("datePublished"),
                            "jsonld_type": jsonld.get("type"),
                            "structured_data_present": bool(jsonld.get("entry_count", 0) > 0),
                            "page_title": page_title,
                            "page_fallback": page_fallback,
                            "page_ugc_count": page_ugc_count,
                            "iframe_fallback": result.get("iframe_fallback", False),
                            # chunk 级信号（Phase 1.5 新增）
                            "heading_path": heading_path,
                            "heading_level": chunk.get("heading_level", 0),
                            "chunk_index": chunk_idx,
                            "total_chunks": min(len(chunks), max_chunks_per_page),
                            "is_ugc": chunk_ugc,
                            "content_hash": content_hash,
                        },
                    })
                    ev_idx += 1

            logger.info("Web Search 完成: query=%s, 获取 %d 条证据 / %d 页 (entity=%s)",
                        query[:50], len(evidence), len(ranked_urls), entity or "unknown")
            return evidence

        except Exception as e:
            logger.error("Web Search 异常: %s", str(e)[:200])
            return []

    async def _search_ddg(self, query: str, top_k: int, locale: str = "zh-CN",
                           time_range: str | None = None, country: str = "CN") -> list[str]:
        """Bing 搜索（含 MultiEngineSearch failover 到 DDG）

        Args:
            query: 搜索查询
            top_k: 最大结果数
            locale: 区域设置 (zh-CN/en-US)
            time_range: 时间过滤 (day/week/month/year)
            country: 国家代码

        Returns:
            list[str]: URL 列表
        """
        # Phase D: 优先使用 MultiEngineSearch（含自动 failover）
        try:
            from app.tools.search_engine import get_multi_engine_search
            multi = get_multi_engine_search()
            if multi._engines:  # 有可用引擎时
                search_kwargs: dict[str, Any] = {}
                if time_range:
                    search_kwargs["time_range"] = time_range
                if country:
                    search_kwargs["country"] = country
                result = await multi.search(query, max_results=top_k, **search_kwargs)
                if result["results"]:
                    urls = [r.url for r in result["results"]]
                    logger.info("MultiEngineSearch 成功: engine=%s, urls=%d",
                               result["engine_used"], len(urls))
                    return urls
                # MultiEngineSearch 所有引擎都失败，降级到直接 Bing 搜索
                logger.warning("MultiEngineSearch 全部失败 (%s)，降级到直接 Bing 搜索",
                              result["failed_engines"])
        except Exception as e:
            logger.warning("MultiEngineSearch 异常，降级到直接 Bing 搜索: %s", str(e)[:100])

        # 降级路径：直接 Bing 表单搜索（原有逻辑）
        match_entity(query)

        # 重试机制：Bing 表单搜索偶发返回空结果
        for attempt in range(2):
            try:
                raw_results = await self._do_bing_search(query, top_k, locale=locale,
                                                          time_range=time_range, country=country)
                if raw_results:
                    # _do_bing_search 返回 list[dict{url, title}]，提取 URL
                    return [r["url"] for r in raw_results if "url" in r]
                if attempt == 0:
                    logger.debug("Bing 搜索无结果，重试: query=%s", query[:50])
                    await asyncio.sleep(2)  # 重试前等待
            except Exception as e:
                if attempt == 0:
                    logger.warning("Bing 搜索异常，重试: %s", str(e)[:100])
                    await asyncio.sleep(2)
                else:
                    raise

        logger.warning("Bing 搜索 2 次均无结果: query=%s", query[:50])
        return []

    async def _do_bing_search(self, query: str, top_k: int, locale: str = "zh-CN",
                               time_range: str | None = None, country: str = "CN") -> list[dict[str, str]]:
        """执行单次 Bing 表单搜索

        流程：访问首页获取 cookie → 搜索框输入 → 从 cite 标签提取真实 URL
        支持 locale（zh-CN 中文搜索 / en-US 英文搜索）和时间过滤。

        Args:
            query: 搜索查询
            top_k: 最大结果数
            locale: 区域设置 (zh-CN/en-US)
            time_range: 时间过滤 (day/week/month/year)
            country: 国家代码

        Returns:
            list[dict]: 每项为 {"url": str, "title": str}
        """
        await self._ensure_browser()

        # Bing 时间过滤参数映射
        _BING_TIME_FILTERS = {
            "day": 'interval%3d"7"',
            "week": 'interval%3d"8"',
            "month": 'interval%3d"9"',
            "year": 'interval%3d"10"',
        }

        # 根据 locale 选择 Bing 域名和 Accept-Language
        if locale.startswith("zh"):
            bing_base = "https://cn.bing.com"
            accept_langs = ["zh-CN", "zh", "en-US", "en"]
        else:
            bing_base = "https://www.bing.com"
            accept_langs = ["en-US", "en"]

        # 加载持久化 Cookie
        bing_storage = self._storage_state_path if os.path.exists(self._storage_state_path) else None

        context = await self._browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale=locale,
            storage_state=bing_storage,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": ",".join(accept_langs),
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
            color_scheme="light",
            device_scale_factor=1.25,
            has_touch=False,
            is_mobile=False,
        )
        await context.add_init_script(_STEALTH_JS)
        page = await context.new_page()
        page.set_default_navigation_timeout(20000)
        page.set_default_timeout(10000)

        try:
            # Step 1: 访问 Bing 首页获取 cookie
            await page.goto(bing_base + "/", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1000 + int(500 * (hash(query) % 100) / 100))

            # Step 2: 在搜索框输入并提交（拟人化输入，而非瞬间 fill）
            search_input = page.locator("textarea[name='q'], input[name='q']").first
            await search_input.wait_for(state="visible", timeout=5000)
            # 使用 type 模拟人类逐字输入（比 fill 更难被检测为机器人）
            await search_input.click()
            await page.wait_for_timeout(200)
            await search_input.type(query, delay=50 + (hash(query) % 50))  # 每个字符50-100ms
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter")

            # Step 3: 等待结果页加载
            await page.wait_for_timeout(4000)

            # Step 3.25: 检测 Bing 验证码
            try:
                captcha_result = await page.evaluate(_CAPTCHA_DETECT_JS)
                if captcha_result and captcha_result.get("detected"):
                    logger.warning("Bing 搜索遇到 CAPTCHA: types=%s", captcha_result.get("types"))
                    return []  # Bing 被验证码拦截，返回空，让 failover 到 DDG
            except Exception:
                pass

            # Step 3.5: 如果需要时间过滤，导航到带过滤参数的 URL
            if time_range and time_range in _BING_TIME_FILTERS:
                current_url = page.url
                time_param = _BING_TIME_FILTERS[time_range]
                if "?" in current_url:
                    filtered_url = current_url + f"&qft={time_param}"
                else:
                    filtered_url = current_url + f"?qft={time_param}"
                try:
                    await page.goto(filtered_url, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(3000)
                except Exception:
                    pass  # 时间过滤失败不影响主流程

            # Step 4: 从 <cite> 标签提取真实 URL
            raw_results = await page.evaluate("""
                () => {
                    const items = [];
                    document.querySelectorAll('li.b_algo').forEach(li => {
                        const cite = li.querySelector('cite');
                        const h2a = li.querySelector('h2 a');
                        const title = h2a ? (h2a.textContent || '').trim() : '';
                        const citeText = cite ? (cite.textContent || '').trim() : '';
                        items.push({title: title, cite: citeText});
                    });
                    return items;
                }
            """)

            # 从 cite 文本重建完整 URL + 保留标题
            # cite 格式: "https://docs.python.org › library › asyncio"
            from .domain_registry import SPAM_DOMAINS
            results: list[dict[str, str]] = []  # {url, title}
            seen: set[str] = set()
            for item in raw_results[:top_k]:
                cite = item.get("cite", "")
                if not cite:
                    continue
                title = item.get("title", "")
                if cite.startswith("http"):
                    parts = cite.split(" › ")
                    if parts:
                        base = parts[0].rstrip("/")
                        path = "/".join(parts[1:]) if len(parts) > 1 else ""
                        url = f"{base}/{path}" if path else base
                        # 过滤 spam 域名
                        hostname = url.split("/")[2] if len(url.split("/")) > 2 else ""
                        if hostname in SPAM_DOMAINS:
                            continue
                        if url not in seen:
                            seen.add(url)
                            results.append({"url": url, "title": title})
                else:
                    first_part = cite.split(" › ")[0] if " › " in cite else cite.split(" ")[0]
                    if first_part and "." in first_part:
                        url = f"https://{first_part}"
                        if url not in seen:
                            seen.add(url)
                            results.append({"url": url, "title": title})

            logger.debug("Bing 搜索: query=%s, 获取 %d URLs",
                         query[:50], len(results))
            # 成功获取结果后保存 Cookie 状态
            if results:
                try:
                    await context.storage_state(path=self._storage_state_path)
                except Exception:
                    pass
            return results[:top_k]

        finally:
            await page.close()
            await context.close()

    async def _fetch_and_extract(self, url: str, locale: str = "zh-CN") -> dict[str, Any]:
        """Playwright 渲染页面并提取 claim 粒度分块 + 结构化元数据

        Phase 1.5 改进（Claude Sonnet 5 #4）：
        - 从整页 blob 改为 heading-based chunking
        - 每块携带 heading_path（h1 > h2 > h3）作为结构元数据
        - 无 heading 页面使用段落 fallback
        - 小段合并避免碎片化

        P0 安全修复（Claude 交叉评审）：
        - SSRF: 初始 URL 校验 + redirect-hop 后 response.url 校验
        - Response size: 超过 MAX_RESPONSE_BYTES 的页面跳过提取
        - Context cleanup: 使用 async with 保证资源释放

        Args:
            url: 要抓取的 URL
            locale: 浏览器区域设置 (zh-CN/en-US)

        返回：
        {
            "chunks": list[dict],    # [{heading_path, heading_level, text, is_ugc}]
            "title": str,            # 页面标题
            "jsonld": dict,          # schema.org JSON-LD 提取结果
            "last_modified": str|None,  # HTTP Last-Modified 头
            "fallback": bool,        # 是否使用了段落 fallback
            "ugc_count": int,        # 检测到的 UGC 元素数
        }

        异常处理：所有 Playwright 异常被捕获，返回空 chunks。
        """
        # P0-1: SSRF 初始 URL 校验
        safe, reason = _is_safe_url(url)
        if not safe:
            logger.warning("SSRF 拦截: url=%s reason=%s", url[:80], reason)
            return {"chunks": [], "title": "", "jsonld": {"entry_count": 0},
                    "last_modified": None, "fallback": True, "ugc_count": 0}

        # A-3: per-domain 限速（token-bucket）
        try:
            from app.tools.rate_limiter import get_rate_limiter
            acquired = await get_rate_limiter().acquire(url, max_wait=5.0)
            if not acquired:
                logger.warning("域名限速超时，跳过: url=%s", url[:80])
                return {"chunks": [], "title": "", "jsonld": {"entry_count": 0},
                        "last_modified": None, "fallback": True, "ugc_count": 0}
        except Exception:
            pass  # 限速器故障不阻断主流程

        async with self._semaphore:
            try:
                # 检查域名是否近期被验证码拦截
                hostname_check = urlparse(url).hostname or ""
                now = asyncio.get_event_loop().time()
                if hostname_check in self._captcha_blocked_domains:
                    blocked_at = self._captcha_blocked_domains[hostname_check]
                    if now - blocked_at < 300:  # 5分钟内不重试被验证码拦截的域名
                        logger.debug("域名近期被CAPTCHA拦截，跳过: %s", hostname_check)
                        return {"chunks": [], "title": "", "jsonld": {"entry_count": 0},
                                "last_modified": None, "fallback": True, "ugc_count": 0,
                                "captcha": True, "captcha_types": ["cooldown"]}

                # 加载持久化的 Cookie（如果存在）
                storage_state = None
                if os.path.exists(self._storage_state_path):
                    try:
                        storage_state = self._storage_state_path
                    except Exception:
                        storage_state = None

                async with await self._browser.new_context(
                    user_agent=_USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale=locale,
                    timezone_id="Asia/Shanghai",
                    java_script_enabled=True,
                    storage_state=storage_state,
                    # 更真实的浏览器参数
                    color_scheme="light",
                    reduced_motion="no-preference",
                    forced_colors="none",
                    has_touch=False,
                    is_mobile=False,
                    device_scale_factor=1.25,
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8" if locale.startswith("zh") else "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                        "Cache-Control": "max-age=0",
                    },
                ) as context:
                    await context.add_init_script(_STEALTH_JS)
                    async with await context.new_page() as page:
                        # 拟人化：设置默认导航超时
                        page.set_default_navigation_timeout(20000)
                        page.set_default_timeout(10000)

                        # goto 返回 Response 对象，含 HTTP 头
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                        # P0-1: redirect-hop SSRF 验证
                        if response:
                            final_url = response.url
                            safe_redirect, redirect_reason = _is_safe_url(final_url)
                            if not safe_redirect:
                                logger.warning("SSRF redirect 拦截: initial=%s final=%s reason=%s",
                                               url[:60], final_url[:60], redirect_reason)
                                return {"chunks": [], "title": "", "jsonld": {"entry_count": 0},
                                        "last_modified": None, "fallback": True, "ugc_count": 0}

                        # P0-5: response body 大小限制
                        MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5MB
                        content_length = None
                        if response:
                            cl = response.headers.get("content-length")
                            if cl:
                                try:
                                    content_length = int(cl)
                                except ValueError:
                                    pass
                        if content_length and content_length > MAX_RESPONSE_BYTES:
                            logger.warning("响应体过大，跳过: url=%s size=%d", url[:60], content_length)
                            return {"chunks": [], "title": "", "jsonld": {"entry_count": 0},
                                    "last_modified": None, "fallback": True, "ugc_count": 0}

                        # 拟人化等待：随机延迟 500-1500ms（模拟人类阅读页面开始加载）
                        await page.wait_for_timeout(500 + int(500 * (hash(url) % 100) / 100))

                        # ===== CAPTCHA 快速检测（在等待完整内容前先检测）=====
                        try:
                            captcha_result = await page.evaluate(_CAPTCHA_DETECT_JS)
                            if captcha_result and captcha_result.get("detected"):
                                captcha_types = captcha_result.get("types", [])
                                captcha_title = captcha_result.get("title", "")
                                logger.warning("CAPTCHA 检测: url=%s types=%s title=%s",
                                             url[:60], captcha_types, captcha_title[:50])
                                # 记录被拦截的域名
                                if hostname_check:
                                    self._captcha_blocked_domains[hostname_check] = now

                                # 值守模式：暂停等待人工介入
                                try:
                                    from app.tools.captcha_guard import (
                                        CaptchaStatus,
                                        get_captcha_guard,
                                    )
                                    guard = await get_captcha_guard()
                                    if guard.guard_mode:
                                        status = await guard.intercept_captcha(
                                            page=page,
                                            url=url,
                                            captcha_types=captcha_types,
                                            page_title=captcha_title,
                                        )
                                        if status == CaptchaStatus.RESOLVED:
                                            # 用户处理完验证码后，重新检测（可能还有第二层验证）
                                            # 先等页面加载，再重新检查
                                            await page.wait_for_timeout(2000)
                                            recheck = await page.evaluate(_CAPTCHA_DETECT_JS)
                                            if recheck and recheck.get("detected"):
                                                logger.warning("CAPTCHA 人工处理后仍然存在，跳过: %s",
                                                             recheck.get("types"))
                                            else:
                                                # CAPTCHA 已通过，继续正常提取流程
                                                pass  # 不 return，继续往下走提取内容
                                        else:
                                            # TIMEOUT/SKIPPED：返回空
                                            return {"chunks": [], "title": captcha_title,
                                                    "jsonld": {"entry_count": 0},
                                                    "last_modified": None, "fallback": True,
                                                    "ugc_count": 0, "captcha": True,
                                                    "captcha_types": captcha_types}
                                    else:
                                        # 非值守模式：直接返回空
                                        return {"chunks": [], "title": captcha_title,
                                                "jsonld": {"entry_count": 0},
                                                "last_modified": None, "fallback": True,
                                                "ugc_count": 0, "captcha": True,
                                                "captcha_types": captcha_types}
                                except ImportError:
                                    return {"chunks": [], "title": captcha_title,
                                            "jsonld": {"entry_count": 0},
                                            "last_modified": None, "fallback": True, "ugc_count": 0,
                                            "captcha": True, "captcha_types": captcha_types}
                        except Exception:
                            pass  # CAPTCHA 检测本身不应该阻断流程

                        # 拟人化：模拟页面滚动
                        try:
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 4)")
                            await page.wait_for_timeout(200)
                            await page.evaluate("window.scrollTo(0, 0)")
                        except Exception:
                            pass

                        await page.wait_for_timeout(1000)

                        # Claim 粒度分块提取（Phase 1.5）
                        chunk_result = await page.evaluate(_CHUNK_EXTRACT_JS)
                        chunks = chunk_result.get("chunks", []) if chunk_result else []
                        fallback = chunk_result.get("fallback", False) if chunk_result else True
                        ugc_count = chunk_result.get("ugc_count", 0) if chunk_result else 0

                        # 提取标题
                        try:
                            title = await page.title()
                        except Exception:
                            title = ""
                        # 提取 JSON-LD 结构化数据
                        try:
                            jsonld = await page.evaluate(_JSONLD_EXTRACT_JS)
                        except Exception:
                            jsonld = {"entry_count": 0}
                        # HTTP Last-Modified 头
                        last_modified = None
                        if response:
                            last_modified = response.headers.get("last-modified")

                        # 成功提取后，保存 Cookie 状态（用于下次访问）
                        if chunks and not fallback:
                            try:
                                await context.storage_state(path=self._storage_state_path)
                            except Exception:
                                pass

                        return {
                            "chunks": chunks or [],
                            "title": title or "",
                            "jsonld": jsonld or {"entry_count": 0},
                            "last_modified": last_modified,
                            "fallback": fallback,
                            "ugc_count": ugc_count,
                            "captcha": False,
                        }

            except Exception as e:
                logger.debug("页面渲染失败: url=%s err=%s", url, str(e)[:100])
                return {"chunks": [], "title": "", "jsonld": {"entry_count": 0},
                        "last_modified": None, "fallback": True, "ugc_count": 0}

    async def close(self) -> None:
        """关闭浏览器实例（应用关闭时调用）"""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Playwright 浏览器已关闭")


# 全局单例（延迟初始化）
_instance: PlaywrightWebSearch | None = None


def get_playwright_search() -> PlaywrightWebSearch:
    """获取全局 PlaywrightWebSearch 单例"""
    global _instance
    if _instance is None:
        _instance = PlaywrightWebSearch()
    return _instance


async def close_playwright_search() -> None:
    """关闭全局 PlaywrightWebSearch 实例（应用关闭时调用）"""
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
