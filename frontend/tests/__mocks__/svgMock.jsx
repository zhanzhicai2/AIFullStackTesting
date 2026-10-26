// Jest 环境下的 svg 资源替身。
// umi 编译期把 svg 打包成:默认导出 = url 字符串,ReactComponent = React 组件。
// 这里保持同样的导出形状,避免测试里把 svg 当 js 源码解析报 SyntaxError。
const React = require('react');

const SvgStub = (props) => React.createElement('svg', props);

module.exports = {
  __esModule: true,
  default: 'test-file-stub.svg',
  ReactComponent: SvgStub,
};
