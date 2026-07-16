import '@testing-library/jest-dom/vitest'

// jsdom 不实现 Element.scrollTo 的实际滚动行为，
// 提供一个 no-op polyfill，避免组件 effect 中调用 scrollTo 时抛错。
if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo() {}
}
