import '@testing-library/jest-dom/vitest';

// Radix UI 组件在 jsdom 中需要 pointer capture 支持
// 这些方法在浏览器中原生存在，但 jsdom 未实现
if (typeof Element !== 'undefined') {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture || (() => false);
  Element.prototype.releasePointerCapture = Element.prototype.releasePointerCapture || (() => {});
  Element.prototype.setPointerCapture = Element.prototype.setPointerCapture || (() => {});
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {});
}

// jsdom 不支持 navigation（window.location.href = '...' 会触发 "Not implemented" 警告）
// 用 spy 拦截 href setter，避免测试输出被警告噪音淹没
if (typeof window !== 'undefined') {
  const hrefDescriptor = Object.getOwnPropertyDescriptor(window, 'location');
  if (hrefDescriptor && hrefDescriptor.configurable !== false) {
    const originalLocation = window.location;
    const mockLocation = {
      ...originalLocation,
      set href(url: string) {
        // no-op: 测试中不执行真实导航
      },
      get href() {
        return originalLocation.href;
      },
      assign: () => {},
      replace: () => {},
      reload: () => {},
    };
    try {
      Object.defineProperty(window, 'location', {
        value: mockLocation,
        writable: true,
        configurable: true,
      });
    } catch {
      // 如果无法覆盖（部分 jsdom 版本 location 不可配置），静默跳过
    }
  }
}
