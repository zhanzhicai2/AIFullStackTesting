import { configUmiAlias, createConfig } from '@umijs/max/test';

export default async () => {
  const config = await configUmiAlias({
    ...createConfig({
      target: 'browser',
    }),
  });

  console.log();
  return {
    ...config,
    testEnvironmentOptions: {
      ...(config?.testEnvironmentOptions || {}),
      url: 'http://localhost:8000',
    },
    setupFiles: [...(config.setupFiles || []), './tests/setupTests.jsx'],
    globals: {
      ...config.globals,
      localStorage: null,
    },
    // @umijs/max/test 只给 css/less 系列做了资源映射,svg 会被 Jest 当 js 源码解析报 SyntaxError。
    // 这里补上 svg 的替身(默认导出 url 字符串 + ReactComponent),对齐 umi 编译期的导出形状。
    //
    // 注意顺序:jest 的 moduleNameMapper 按 key 插入顺序匹配,首个命中即生效且不会递归重匹配。
    // configUmiAlias 会把 umi 的路径别名(如 ^@/(.*)$ -> src/$1)写进来,若 svg 规则排在后面,
    // '@/assets/NoSearch.svg' 会先被改写成绝对路径,svg 规则就再也匹配不上。所以必须放在别名规则前面。
    moduleNameMapper: {
      '\\.svg$': require.resolve('./tests/__mocks__/svgMock.jsx'),
      ...(config?.moduleNameMapper || {}),
    },
    // 当前仓库还没有真实用例,没有测试文件时不应让 CI 红灯。
    passWithNoTests: true,
  };
};
