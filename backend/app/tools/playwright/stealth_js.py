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

// ===== 18. 覆盖 navigator.vendor（headless 下为空字符串）=====
Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.',
    configurable: true,
});

// ===== 19. window.outerDimensions 与 innerDimensions 区分 =====
// headless 模式下 outerWidth == innerWidth，真实浏览器 outer > inner
Object.defineProperty(window, 'outerWidth', {
    get: () => window.innerWidth + randInt(16, 32),
    configurable: true,
});
Object.defineProperty(window, 'outerHeight', {
    get: () => window.innerHeight + randInt(80, 120),
    configurable: true,
});

// ===== 20. screen.availWidth/availHeight 与 screen.width/height 区分 =====
// 真实浏览器可用高度 < 总高度（任务栏占用），可用宽度 = 总宽度（无侧边栏）
Object.defineProperty(screen, 'availWidth', {
    get: () => screen.width,
    configurable: true,
});
Object.defineProperty(screen, 'availHeight', {
    get: () => screen.height - randInt(40, 60),
    configurable: true,
});

// ===== 21. 覆盖 navigator.productSub（headless 下为空）=====
Object.defineProperty(navigator, 'productSub', {
    get: () => '20030107',
    configurable: true,
});

// ===== 22. 覆盖 navigator.cookieEnabled（headless 下可能为 false）=====
Object.defineProperty(navigator, 'cookieEnabled', {
    get: () => true,
    configurable: true,
});

// ===== 23. document.hidden 应为 false（页面可见时）=====
// 某些检测会检查 document.hidden 是否始终为 true（headless 特征）
Object.defineProperty(document, 'hidden', {
    get: () => false,
    configurable: true,
});
Object.defineProperty(document, 'visibilityState', {
    get: () => 'visible',
    configurable: true,
});

// ===== 24. navigator.appVersion 应匹配 User-Agent ====
Object.defineProperty(navigator, 'appVersion', {
    get: () => '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    configurable: true,
});

// ===== 25. 覆盖 navigator.doNotTrack（国内用户通常为 null 或 "1"）=====
Object.defineProperty(navigator, 'doNotTrack', {
    get: () => '1',
    configurable: true,
});

// ===== 26. 覆盖 navigator.getGamepads（headless 下返回空数组）=====
if (navigator.getGamepads) {
    const origGetGamepads = navigator.getGamepads;
    navigator.getGamepads = function() {
        return [null, null, null, null];
    };
}

// ===== 27. 覆盖 navigator.keyboard（headless 下可能不存在）=====
if (!navigator.keyboard) {
    Object.defineProperty(navigator, 'keyboard', {
        get: () => ({
            getLayoutMap: () => Promise.resolve(new Map()),
            lock: () => Promise.reject(new Error('Not supported')),
            unlock: () => {},
        }),
        configurable: true,
    });
}

// ===== 28. 覆盖 navigator.userAgentData（新版 Chrome 特征）=====
if (navigator.userAgentData) {
    const originalGetHighEntropyValues = navigator.userAgentData.getHighEntropyValues;
    if (originalGetHighEntropyValues) {
        navigator.userAgentData.getHighEntropyValues = function(hints) {
            return Promise.resolve({
                architecture: 'x86',
                bitness: '64',
                brands: [
                    { brand: 'Chromium', version: '125' },
                    { brand: 'Google Chrome', version: '125' },
                    { brand: 'Not;A=Brand', version: '99' },
                ],
                fullVersion: '125.0.6422.141',
                mobile: false,
                model: '',
                platform: 'Windows',
                platformVersion: '10.0.0',
                uaFullVersion: '125.0.6422.141',
            });
        };
    }
}

// ===== 29. iframe 检测防护 =====
// 某些检测通过创建 iframe 来检查 contentWindow 属性
const origCreateElement = Document.prototype.createElement;
Document.prototype.createElement = function(...args) {
    const el = origCreateElement.apply(this, args);
    if (args[0] && args[0].toLowerCase() === 'iframe') {
        const origContentWindow = Object.getOwnPropertyDescriptor(
            HTMLIFrameElement.prototype, 'contentWindow'
        );
        if (origContentWindow && origContentWindow.get) {
            const origGet = origContentWindow.get;
            Object.defineProperty(el, 'contentWindow', {
                get: function() {
                    try { return origGet.call(this); } catch(e) {
                        return null;
                    }
                },
                configurable: true,
            });
        }
    }
    return el;
};

// ===== 30. 覆盖 navigator.mediaCapabilities（headless 下可能为空）=====
if (!navigator.mediaCapabilities) {
    Object.defineProperty(navigator, 'mediaCapabilities', {
        get: () => ({
            decodingInfo: () => Promise.resolve({ supported: true, smooth: true, powerEfficient: true }),
            encodingInfo: () => Promise.resolve({ supported: true, smooth: true, powerEfficient: true }),
        }),
        configurable: true,
    });
}
"""
