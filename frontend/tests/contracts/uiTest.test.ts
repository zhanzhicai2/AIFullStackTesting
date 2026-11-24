/**
 * 跨端契约测试: 前端 `src/consts/uiTest.ts` ↔ 后端 `backend/app/core/ui_executor.py`
 *
 * backend/CLAUDE.md 与 specs/002-ui-automation/contracts/steps.md §8:
 * `UI_ACTIONS` / `UI_STRATEGIES` 是后端 `ACTIONS` / `STRATEGIES` 的镜像,
 * **改一处必须同时改另一处**; 后端是最终裁决者(不合规步骤会被丢弃)。
 *
 * 这里按字段级比对(target / value / fields / required), 不只比名字 ——
 * 只比名字的话, 两端各自改了语义却仍会绿灯。
 */
import * as fs from 'fs';
import * as path from 'path';

import { UI_ACTIONS, UI_STRATEGIES } from '@/consts/uiTest';

const PY_PATH = path.resolve(__dirname, '../../../backend/app/core/ui_executor.py');

interface PyAction {
  name: string;
  fields: string[];
  required: string[];
  target: boolean;
  value: string;
}

/** 把 Python 的 `set()` / `{"a", "b"}` 解析成字符串数组 */
function parsePyFieldSet(raw: string): string[] {
  const t = raw.trim();
  if (t === 'set()' || t === '{}') return [];
  const inner = t.replace(/^\{|\}$/g, '').trim();
  if (!inner) return [];
  return inner
    .split(',')
    .map((s) => s.trim().replace(/^["']|["']$/g, ''))
    .filter(Boolean);
}

/** 解析 `ACTIONS = { ... }` 块里每个动作的完整定义 */
function parsePyActions(source: string): PyAction[] {
  const start = source.indexOf('ACTIONS = {');
  if (start < 0) throw new Error('ui_executor.py 里找不到 ACTIONS 定义');
  const end = source.indexOf('\n}', start);
  const body = source.slice(start, end);

  const out: PyAction[] = [];
  const re =
    /"([a-z_]+)":\s*\{"fields":\s*(set\(\)|\{[^}]*\}),\s*"required":\s*\[([^\]]*)\],\s*"target":\s*(True|False),\s*"value":\s*"([a-z_]+)"\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body)) !== null) {
    out.push({
      name: m[1],
      fields: parsePyFieldSet(m[2]),
      required: m[3]
        .split(',')
        .map((s) => s.trim().replace(/^["']|["']$/g, ''))
        .filter(Boolean),
      target: m[4] === 'True',
      value: m[5],
    });
  }
  return out;
}

/** 解析 `STRATEGIES = { ... }` 块 */
function parsePyStrategies(source: string): Record<string, { label: string; semantic: boolean }> {
  const start = source.indexOf('STRATEGIES = {');
  if (start < 0) throw new Error('ui_executor.py 里找不到 STRATEGIES 定义');
  const end = source.indexOf('\n}', start);
  const body = source.slice(start, end);

  const out: Record<string, { label: string; semantic: boolean }> = {};
  const re = /"([a-z_]+)":\s*\{"label":\s*"([^"]*)",\s*"semantic":\s*(True|False)[^}]*\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body)) !== null) {
    out[m[1]] = { label: m[2], semantic: m[3] === 'True' };
  }
  return out;
}

const sorted = (xs: string[]) => [...xs].sort();

describe('UI 自动化契约: uiTest.ts ↔ ui_executor.py', () => {
  let py: string;
  let backendActions: PyAction[];
  let backendStrategies: Record<string, { label: string; semantic: boolean }>;

  beforeAll(() => {
    expect(fs.existsSync(PY_PATH)).toBe(true);
    py = fs.readFileSync(PY_PATH, 'utf8');
    backendActions = parsePyActions(py);
    backendStrategies = parsePyStrategies(py);
    // 解析器自身必须有效, 否则下面的断言会因两边都为空而假绿
    expect(backendActions.length).toBeGreaterThan(20);
    expect(Object.keys(backendStrategies).length).toBe(8);
  });

  test('动作白名单集合完全一致(后端有而前端漏 = 编辑器选不到; 前端有而后端没有 = 会被丢弃)', () => {
    const fe = sorted(UI_ACTIONS.map((a) => a.name));
    const be = sorted(backendActions.map((a) => a.name));
    expect(fe).toEqual(be);
  });

  test('每个动作的 target / value / fields / required 与后端逐项一致', () => {
    const beMap = new Map(backendActions.map((a) => [a.name, a]));
    for (const fe of UI_ACTIONS) {
      const be = beMap.get(fe.name);
      expect(be).toBeDefined();
      if (!be) continue;
      const ctx = `action=${fe.name}`;
      expect({ [ctx + '.target']: fe.target }).toEqual({ [ctx + '.target']: be.target });
      expect({ [ctx + '.value']: fe.value }).toEqual({ [ctx + '.value']: be.value });
      expect({ [ctx + '.fields']: sorted(fe.fields) }).toEqual({
        [ctx + '.fields']: sorted(be.fields),
      });
      expect({ [ctx + '.required']: sorted(fe.required) }).toEqual({
        [ctx + '.required']: sorted(be.required),
      });
    }
  });

  test('定位策略集合一致', () => {
    expect(sorted(Object.keys(UI_STRATEGIES))).toEqual(sorted(Object.keys(backendStrategies)));
  });

  test('定位策略的 label 与 semantic 标记一致(semantic 决定编辑器是否优先推荐)', () => {
    for (const [k, be] of Object.entries(backendStrategies)) {
      const fe = UI_STRATEGIES[k];
      expect(fe).toBeDefined();
      if (!fe) continue;
      expect({ [k + '.label']: fe.label }).toEqual({ [k + '.label']: be.label });
      expect({ [k + '.semantic']: fe.semantic }).toEqual({ [k + '.semantic']: be.semantic });
    }
  });

  test('断言类动作都带期望值语义(与后端 ASSERT_TYPE_MAPPING 对齐)', () => {
    // 后端把 expect_* 映射到接口用例的断言类型, 前端这些动作的 value 必须是 expected
    const expectActions = UI_ACTIONS.filter((a) => a.name.startsWith('expect_'));
    expect(expectActions.length).toBeGreaterThan(0);
    for (const a of expectActions) {
      // expect_visible / expect_hidden / expect_enabled 是布尔断言, 用 locator 定位目标
      if (['expect_visible', 'expect_hidden', 'expect_enabled'].includes(a.name)) continue;
      expect({ [a.name]: a.value }).toEqual({ [a.name]: 'expected' });
    }
  });

  test('需要目标的动作必须 target=true, 导航/截图类必须 target=false', () => {
    const noTarget = [
      'goto',
      'back',
      'reload',
      'wait_timeout',
      'expect_url',
      'screenshot',
      'set_viewport',
    ];
    for (const name of noTarget) {
      const a = UI_ACTIONS.find((x) => x.name === name);
      expect(a).toBeDefined();
      if (a) expect({ [name]: a.target }).toEqual({ [name]: false });
    }
    for (const name of ['click', 'fill', 'press', 'select', 'upload', 'drag', 'wait_for']) {
      const a = UI_ACTIONS.find((x) => x.name === name);
      expect(a).toBeDefined();
      if (a) expect({ [name]: a.target }).toEqual({ [name]: true });
    }
  });
});
