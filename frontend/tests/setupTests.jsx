const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};

global.localStorage = localStorageMock;

// jsdom 不提供 TextEncoder / TextDecoder, 但 src/utils/tool.ts 的 UTF-8 编解码依赖它们
// (浏览器里由 window 提供, jest 的 jsdom 环境没有)。从 node:util 补上。
// 缺了它会报 `ReferenceError: TextEncoder is not defined`。
if (typeof global.TextEncoder === 'undefined') {
  // eslint-disable-next-line global-require
  const { TextEncoder, TextDecoder } = require('util');
  global.TextEncoder = TextEncoder;
  global.TextDecoder = TextDecoder;
}

Object.defineProperty(URL, 'createObjectURL', {
  writable: true,
  value: jest.fn(),
});

class Worker {
  constructor(stringUrl) {
    this.url = stringUrl;
    this.onmessage = () => {};
  }

  postMessage(msg) {
    this.onmessage(msg);
  }
}
window.Worker = Worker;

/* eslint-disable global-require */
if (typeof window !== 'undefined') {
  // ref: https://github.com/ant-design/ant-design/issues/18774
  if (!window.matchMedia) {
    Object.defineProperty(global.window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: jest.fn(() => ({
        matches: false,
        addListener: jest.fn(),
        removeListener: jest.fn(),
      })),
    });
  }
  if (!window.matchMedia) {
    Object.defineProperty(global.window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: jest.fn((query) => ({
        matches: query.includes('max-width'),
        addListener: jest.fn(),
        removeListener: jest.fn(),
      })),
    });
  }
}
const errorLog = console.error;
Object.defineProperty(global.window.console, 'error', {
  writable: true,
  configurable: true,
  value: (...rest) => {
    const logStr = rest.join('');
    if (logStr.includes('Warning: An update to %s inside a test was not wrapped in act(...)')) {
      return;
    }
    errorLog(...rest);
  },
});
