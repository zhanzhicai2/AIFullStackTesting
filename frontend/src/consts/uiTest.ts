// UI 自动化常量
//
// ⚠️ 权威定义在 `backend/app/core/ui_executor.py` 的 `ACTIONS` / `STRATEGIES`,
//    **改一处必须同时改另一处**(backend/CLAUDE.md 与 specs/002-ui-automation/contracts/steps.md §8)。
//    这里是镜像, 不是第二份定义。

// 动作白名单(封闭集合) —— 与后端 ACTIONS 的 key 一一对应
// target: 是否需要目标(元素引用或内联定位)
// value: value 字段的语义 —— locator 可作内联定位值, expected 是期望值,
//        option 是选项值, target_selector 是拖拽目标选择器, filename 是截图文件名
export type UiActionValueRole =
  | 'locator'
  | 'expected'
  | 'option'
  | 'target_selector'
  | 'filename'
  | 'none';

export interface UiActionSpec {
  name: string;
  label: string;
  group: string;
  target: boolean;
  value: UiActionValueRole;
  fields: string[];
  required: string[];
}

// 动作白名单 —— 顺序与后端 ACTIONS 一致
export const UI_ACTIONS: UiActionSpec[] = [
  // 导航
  { name: 'goto', label: '打开页面', group: '导航', target: false, value: 'none', fields: ['url'], required: ['url'] },
  { name: 'back', label: '后退', group: '导航', target: false, value: 'none', fields: [], required: [] },
  { name: 'reload', label: '刷新', group: '导航', target: false, value: 'none', fields: [], required: [] },
  // 交互
  { name: 'click', label: '单击', group: '交互', target: true, value: 'locator', fields: [], required: [] },
  { name: 'dblclick', label: '双击', group: '交互', target: true, value: 'locator', fields: [], required: [] },
  { name: 'fill', label: '填入文本', group: '交互', target: true, value: 'locator', fields: ['text'], required: ['text'] },
  { name: 'clear', label: '清空', group: '交互', target: true, value: 'locator', fields: [], required: [] },
  { name: 'press', label: '按键', group: '交互', target: true, value: 'locator', fields: ['text'], required: ['text'] },
  { name: 'select', label: '下拉选值', group: '交互', target: true, value: 'option', fields: [], required: ['value'] },
  { name: 'check', label: '勾选', group: '交互', target: true, value: 'locator', fields: [], required: [] },
  { name: 'uncheck', label: '取消勾选', group: '交互', target: true, value: 'locator', fields: [], required: [] },
  { name: 'hover', label: '悬停', group: '交互', target: true, value: 'locator', fields: [], required: [] },
  { name: 'upload', label: '上传文件', group: '交互', target: true, value: 'locator', fields: ['files'], required: ['files'] },
  { name: 'drag', label: '拖拽', group: '交互', target: true, value: 'target_selector', fields: [], required: ['value'] },
  // 等待
  { name: 'wait_for', label: '等待元素', group: '等待', target: true, value: 'locator', fields: ['state'], required: ['state'] },
  { name: 'wait_timeout', label: '固定等待', group: '等待', target: false, value: 'none', fields: [], required: ['timeout'] },
  // 断言
  { name: 'expect_text', label: '断言文本', group: '断言', target: true, value: 'expected', fields: [], required: ['value'] },
  { name: 'expect_visible', label: '断言可见', group: '断言', target: true, value: 'locator', fields: [], required: [] },
  { name: 'expect_hidden', label: '断言不可见', group: '断言', target: true, value: 'locator', fields: [], required: [] },
  { name: 'expect_url', label: '断言地址', group: '断言', target: false, value: 'expected', fields: [], required: ['value'] },
  { name: 'expect_count', label: '断言数量', group: '断言', target: true, value: 'expected', fields: [], required: ['value'] },
  { name: 'expect_value', label: '断言输入值', group: '断言', target: true, value: 'expected', fields: [], required: ['value'] },
  { name: 'expect_enabled', label: '断言可用', group: '断言', target: true, value: 'locator', fields: [], required: [] },
  // 辅助
  { name: 'screenshot', label: '截图', group: '辅助', target: false, value: 'filename', fields: [], required: [] },
  { name: 'scroll', label: '滚动', group: '辅助', target: false, value: 'locator', fields: [], required: [] },
  { name: 'set_viewport', label: '设置视口', group: '辅助', target: false, value: 'expected', fields: [], required: ['value'] },
];

export const UI_ACTION_MAP: Record<string, UiActionSpec> = UI_ACTIONS.reduce<
  Record<string, UiActionSpec>
>((acc, item) => {
  acc[item.name] = item;
  return acc;
}, {});

// 动作分组 —— 编辑器下拉用
export const UI_ACTION_GROUPS = UI_ACTIONS.reduce<Record<string, UiActionSpec[]>>((acc, item) => {
  const list = acc[item.group] || [];
  list.push(item);
  acc[item.group] = list;
  return acc;
}, {});

// 8 种定位策略 —— 与后端 STRATEGIES 一致
export interface UiStrategy {
  label: string;
  // 语义定位比 CSS/XPath 更抗改版, 编辑器优先推荐
  semantic: boolean;
  hint?: string;
}

export const UI_STRATEGIES: Record<string, UiStrategy> = {
  css: { label: 'CSS 选择器', semantic: false },
  xpath: { label: 'XPath', semantic: false },
  id: { label: 'ID', semantic: false },
  text: { label: '文本', semantic: true },
  role: { label: 'Role', semantic: true, hint: 'ARIA role, 建议配合可访问名称一起用' },
  placeholder: { label: '占位符', semantic: true },
  label: { label: 'Label', semantic: true },
  testid: { label: 'testid', semantic: true, hint: 'data-testid 属性, 推荐的稳定定位方式' },
};

export const UI_STRATEGY_OPTIONS = Object.keys(UI_STRATEGIES).map((key) => ({
  label: UI_STRATEGIES[key].label,
  value: key,
}));

// 等待状态
export const UI_WAIT_STATES = [
  { label: '可见', value: 'visible' },
  { label: '不可见', value: 'hidden' },
  { label: '已附加', value: 'attached' },
  { label: '已分离', value: 'detached' },
];

// 失败原因分类 —— 与后端一致
export const UI_ERROR_REASONS: Record<string, string> = {
  element_not_found: '元素引用无效(不存在或已停用)',
  element_ambiguous: '定位到多个元素',
  timeout: '单步超时',
  assertion_failed: '断言不通过',
  navigation_blocked: '目标地址被安全策略拒绝',
  browser_error: '浏览器异常',
};

export const UI_STATUS_LABEL: Record<number, string> = {
  0: '成功',
  1: '失败',
  2: '出错',
};

// 优先用语义定位的提示文案
export const UI_SEMANTIC_HINT =
  '语义定位(role / label / text / placeholder / testid)比 CSS / XPath 更抗页面改版, 优先用语义定位';

export const uiStrategyLabel = (value?: string): string =>
  value && UI_STRATEGIES[value] ? UI_STRATEGIES[value].label : value || '未知';

export const uiStrategySemantic = (value?: string): boolean =>
  value ? !!UI_STRATEGIES[value]?.semantic : false;

export const uiErrorReasonLabel = (value?: string): string =>
  value ? UI_ERROR_REASONS[value] || value : '';
