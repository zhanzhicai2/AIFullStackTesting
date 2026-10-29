// AI 工作台常量
//
// ⚠️ 权威定义在 `backend/app/enums/AIWorkbenchEnum.py`(断言类型白名单 / 优先级 /
//    类别 / 测试类型 / 场景)与 `backend/app/core/ai_prompts/case_gen.py`(DSL 常量),
//    **改一处必须同时改另一处**(backend/CLAUDE.md 与 specs/001-ai-workbench/contracts/dsl.md §8)。
//    这里是镜像, 不是第二份定义。
//
// 后端是最终裁决者(不合规的字段被丢弃); 前端只做**提前提示**, 不在前端做最终判定 ——
// 前端放行、后端丢弃会造成「改了还是被丢弃」的困惑。

import { UI_ACTIONS, UI_ACTION_MAP } from '@/consts/uiTest';

// 断言类型白名单(14 种)—— 与后端 AIWorkbenchEnum.ASSERT_TYPES 一致
export const AI_ASSERT_TYPES: Record<string, string> = {
  equal: '等于',
  not_equal: '不等于',
  in: '包含于',
  text_in: '文本包含于',
  not_in: '不包含于',
  text_not_in: '文本不包含于',
  contain: '包含',
  not_contain: '不包含',
  length_eq: '长度等于',
  length_lt: '长度小于',
  length_gt: '长度大于',
  length_le: '长度小于等于',
  length_ge: '长度大于等于',
  json_equal: 'JSON等于',
};

export const AI_ASSERT_TYPE_KEYS = Object.keys(AI_ASSERT_TYPES);

export const AI_ASSERT_TYPE_OPTIONS = AI_ASSERT_TYPE_KEYS.map((key) => ({
  label: `${AI_ASSERT_TYPES[key]} (${key})`,
  value: key,
}));

// 优先级 —— 与后端 AIWorkbenchEnum.PRIORITIES 一致
export const AI_PRIORITIES = ['P0', 'P1', 'P2', 'P3', 'P4'];
export const AI_DEFAULT_PRIORITY = 'P1';

// 用例类别 —— 与后端 AIWorkbenchEnum.CASE_CATEGORIES 一致
export const AI_CASE_CATEGORIES = ['正向流程', '异常流程', '边界值', '权限', '并发', '其他'];
export const AI_DEFAULT_CATEGORY = '正向流程';

// 测试类型 —— 与后端 AIWorkbenchEnum.TEST_TYPES 一致
export const AI_TEST_TYPES = ['api', 'web', 'manual', 'mobile'];
export const AI_DEFAULT_TEST_TYPE = 'api';

export const AI_TEST_TYPE_OPTIONS = [
  { label: '接口用例 (api)', value: 'api' },
  { label: 'Web UI 用例 (web)', value: 'web' },
  { label: '手工用例 (manual)', value: 'manual' },
  { label: '移动端用例 (mobile)', value: 'mobile' },
];

// 来源类型
export const AI_SOURCE_TYPES = ['text', 'document'];

// AI 场景 —— 与后端 AIWorkbenchEnum.SCENES 一致
export const AI_SCENES = ['case_gen', 'bug', 'log', 'sql'];

export const AI_SCENE_LABELS: Record<string, string> = {
  case_gen: '用例生成',
  bug: 'Bug 分析',
  log: '日志分析',
  sql: 'SQL 分析',
};

// 请求方法 —— 与后端 AIWorkbenchEnum.REQUEST_METHODS 一致
export const AI_REQUEST_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];

// 请求体类型 —— 与后端 AIWorkbenchEnum.BODY_TYPES 一致
export const AI_BODY_TYPES = [0, 1, 2, 3, 4, 5];

export const AI_BODY_TYPE_LABELS: Record<number, string> = {
  0: 'none',
  1: 'json',
  2: 'form',
  3: 'x-form',
  4: 'binary',
  5: 'GraphQL',
};

// 出参来源 —— 与后端 AIWorkbenchEnum.OUT_PARAMETER_SOURCES 一致
export const AI_OUT_PARAMETER_SOURCES = [0, 1, 2, 3, 4];

export const AI_OUT_PARAMETER_SOURCE_LABELS: Record<number, string> = {
  0: 'Body(TEXT)',
  1: 'Body(JSON)',
  2: 'Header',
  3: 'Cookie',
  4: 'HTTP 状态码',
};

// 构造器类型 —— 与后端 AIWorkbenchEnum.CONSTRUCTOR_TYPES 一致
export const AI_CONSTRUCTOR_TYPES = [0, 1, 2, 3, 4];

export const AI_CONSTRUCTOR_TYPE_LABELS: Record<number, string> = {
  0: '测试场景',
  1: 'SQL 语句',
  2: 'Redis 命令',
  3: 'Python 脚本',
  4: 'HTTP 请求',
};

// 草稿状态 —— 与后端 AIWorkbenchEnum 的 DRAFT_STATUS_* 一致
export const AI_DRAFT_STATUS = {
  PENDING: 1,
  ACCEPTED: 2,
  REJECTED: 3,
} as const;

export const AI_DRAFT_STATUS_LABEL: Record<number, string> = {
  1: '待审核',
  2: '已采纳',
  3: '已驳回',
};

// 批次状态 —— 与后端 AIWorkbenchEnum 的 BATCH_STATUS_* 一致
export const AI_BATCH_STATUS = {
  RUNNING: 1,
  DONE: 2,
  ARCHIVED: 3,
} as const;

export const AI_BATCH_STATUS_LABEL: Record<number, string> = {
  1: '生成中',
  2: '已完成',
  3: '已归档',
};

// 历史规律判定 —— 与后端 AIWorkbenchEnum.HISTORY_PATTERNS 一致
export const AI_HISTORY_PATTERNS = ['consistent_failure', 'intermittent', 'recovered', 'first_run'];

export const AI_HISTORY_PATTERN_LABEL: Record<string, string> = {
  consistent_failure: '必现',
  intermittent: '偶发',
  recovered: '已恢复',
  first_run: '首次执行',
};

// DSL 的 UI 步骤动作集 —— **不在这里另写一份**:
// 后端的权威定义是 `app/core/ui_executor.py` 的 ACTIONS, 前端镜像在 `src/consts/uiTest.ts`,
// 本文件直接复用那份镜像。
export const AI_DSL_ACTIONS = UI_ACTIONS;

export const AI_DSL_ACTION_MAP = UI_ACTION_MAP;

// 需要定位的动作(规则 12: 必须给 element 或完整的内联定位)
export const AI_DSL_TARGET_ACTIONS = UI_ACTIONS.filter((item) => item.target).map((item) => item.name);

// DSL 字段长度上限 —— 与后端 case_gen.py 一致
export const AI_MAX_CASE_NAME = 32;
export const AI_MAX_ASSERT_NAME = 32;
export const AI_MAX_OUT_PARAMETER_NAME = 24;
export const AI_MAX_CONSTRUCTOR_NAME = 64;
export const AI_MAX_TAG = 64;
export const AI_MAX_CASES = 200;

// 变量名规则(断言 actually 的 ${变量} 与出参名都要满足)
export const AI_VARIABLE_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

// 提示词注入防护: 外部文本进 prompt 前会被标签包裹
export const AI_EXTERNAL_TAGS = {
  document: 'document',
  logs: 'logs',
  sql: 'sql',
} as const;

// 敏感上下文提示(research.md §3.13): 需求文档与日志会发给第三方厂商
export const AI_THIRD_PARTY_MODEL_NOTICE =
  '所选模型为第三方服务, 需求文档/日志内容将发送至该服务处理。如涉敏感数据, 请选择本地部署模型';
