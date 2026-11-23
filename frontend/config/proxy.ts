/**
 * @name 代理的配置
 * @see 在生产环境 代理是无法生效的，所以这里没有生产环境的配置
 * -------------------------------
 * The agent cannot take effect in the production environment
 * so there is no configuration of the production environment
 * For details, please see
 * https://pro.ant.design/docs/deploy
 *
 * @doc https://umijs.org/docs/guides/proxy
 */
export default {
  dev: {
    '/api/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
      pathRewrite: { '^': '' },
    },
    // 代理所有后端API请求
    '/auth/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/testcase/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/config/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/operation/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/workspace/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/oss/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/project/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/notification/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/online/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/request/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/ai/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/datafactory/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    // 002 UI 自动化 / 003 Mock 配置 —— 与 nginx.conf 的代理正则保持同一前缀集
    '/ui/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    '/mock/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    // 实用工具(/tool/* 的 JSON对比/网络判断/加解密/摘要)
    '/tool/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    // 持续集成 —— 此前两处(这里与 nginx.conf)都漏了, CI 页面的 API 全部落 SPA
    '/ci/': {
      target: 'http://0.0.0.0:7777',
      changeOrigin: true,
    },
    // WebSocket(IndexPage 连 /ws/{user_id} 收通知)。
    // **必须 ws: true** —— 否则 http-proxy 不处理 Upgrade 握手, 连接会挂到超时,
    // 表现是 console 里的 "WebSocket opening handshake timed out" 而不是 404,
    // 按 HTTP 状态码扫描根本查不到。nginx 侧早有 location /ws/, 只有这里漏了。
    '/ws/': {
      target: 'ws://0.0.0.0:7777',
      ws: true,
      changeOrigin: true,
    },
  },
  /**
   * @name 详细的代理配置
   * @doc https://github.com/chimurai/http-proxy-middleware
   */
  test: {
    // localhost:8000/api/** -> https://preview.pro.ant.design/api/**
    '/api/': {
      target: 'https://proapi.azurewebsites.net',
      changeOrigin: true,
      pathRewrite: { '^': '' },
    },
  },
  pre: {
    '/api/': {
      target: 'your pre url',
      changeOrigin: true,
      pathRewrite: { '^': '' },
    },
  },
};
