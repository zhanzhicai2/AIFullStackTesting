/**
 * Mock 配置的前端镜像 —— 权威定义在后端 `backend/app/enums/MockEnum.py`
 *
 * constitution 原则 III: 前后端共享常量 MUST 单一出处, 两端 MUST 互相指认。
 * ⚠️ **改一处必须同时改另一处**, 契约见 `specs/003-mock-config/contracts/api.md` §4。
 */

/** 请求方法白名单(顺序即下拉框展示顺序) */
export const MOCK_METHODS: string[] = [
  'GET',
  'POST',
  'PUT',
  'DELETE',
  'PATCH',
  'HEAD',
  'OPTIONS',
  'ANY',
];

/** 路径类型: 0 精确 / 1 参数化 / 2 通配 */
export const MOCK_PATH_TYPE = {
  EXACT: 0,
  PARAM: 1,
  WILDCARD: 2,
} as const;

export const MOCK_PATH_TYPE_LABELS: Record<number, string> = {
  [MOCK_PATH_TYPE.EXACT]: '精确',
  [MOCK_PATH_TYPE.PARAM]: '参数化',
  [MOCK_PATH_TYPE.WILDCARD]: '通配',
};

/** 模拟延迟上限(毫秒) */
export const MOCK_MAX_DELAY = 5000;

/** 合法回显变量说明(表单就地提示, 与 data-model.md §4 一致) */
export const MOCK_VARIABLE_HINTS: string[] = [
  '$request.path',
  '$request.query.<name>',
  '$request.body.<key.path>',
  '$request.header.<name>',
];

/** 方法标签色(antd Tag color) */
export const MOCK_METHOD_COLORS: Record<string, string> = {
  GET: 'green',
  POST: 'blue',
  PUT: 'orange',
  DELETE: 'red',
  PATCH: 'purple',
  HEAD: 'cyan',
  OPTIONS: 'gold',
  ANY: 'default',
};
