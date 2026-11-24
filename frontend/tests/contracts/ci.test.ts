/**
 * 跨端契约测试: 前端 `src/consts/ci.ts` ↔ 后端 `backend/app/enums/CiEnum.py`
 *
 * CLAUDE.md: 两端常量 MUST 单一出处、互相指认, **改一处必须同时改另一处**。
 * 本测试直接读取后端源码做解析比对 —— 后端是权威, 前端只是镜像。
 * 任何一端单独改动都会让这里红灯。
 */
import * as fs from 'fs';
import * as path from 'path';

import {
  CI_ERROR_CODE,
  CI_RUN_STATUS,
  CI_RUN_STATUS_COLORS,
  CI_RUN_STATUS_LABELS,
} from '@/consts/ci';

const PY_PATH = path.resolve(__dirname, '../../../backend/app/enums/CiEnum.py');

/**
 * 解析 Python 类里的 `NAME = <int>` 常量(跳过元组/字符串等非整数字面量)。
 * 用 indexOf 切片而不是正则 lookahead —— JS 正则没有 `\Z`, 且类体边界更直观。
 */
function parsePyIntConstants(source: string, className: string): Record<string, number> {
  const marker = `class ${className}`;
  const idx = source.indexOf(marker);
  if (idx < 0) {
    throw new Error(`后端 CiEnum.py 里找不到 class ${className}`);
  }
  const nextClass = source.indexOf('\nclass ', idx + 1);
  const body = source.slice(idx, nextClass < 0 ? source.length : nextClass);
  const out: Record<string, number> = {};
  // 必须以缩进开头 —— RunStatus 是文件里最后一个 class, 类体切片会一路切到文件末尾,
  // 若不区分缩进, 后面的模块级常量(TOKEN_* / WAIT_TIMEOUT_* 等)会被误吞进来。
  const re = /^[ \t]+([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+)\s*(?:#.*)?$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body)) !== null) {
    out[m[1]] = Number(m[2]);
  }
  return out;
}

describe('CI 契约: ci.ts ↔ CiEnum.py', () => {
  let py: string;

  beforeAll(() => {
    expect(fs.existsSync(PY_PATH)).toBe(true);
    py = fs.readFileSync(PY_PATH, 'utf8');
  });

  test('CiErrorCode(CI 专属码) 被前端完整镜像', () => {
    // 后端 CiErrorCode 只定义 CI 专属的两档(111/112); 前端 CI_ERROR_CODE 还额外
    // 镜像了平台全局码 0/101/110/401/403 —— 那几个的权威散落在
    // backend/app/handler/fatcory.py 与 app/__init__.py, 没有单一定义文件,
    // 所以这里只对**后端定义了的**做严格双向比对。
    const backend = parsePyIntConstants(py, 'CiErrorCode');
    expect(Object.keys(backend).sort()).toEqual(['NOT_PASSED', 'WAIT_TIMEOUT']);
    for (const [k, v] of Object.entries(backend)) {
      expect({ [k]: (CI_ERROR_CODE as Record<string, number>)[k] }).toEqual({ [k]: v });
    }
    // 前端不得漏掉后端的任何一档
    expect(CI_ERROR_CODE.NOT_PASSED).toBe(111);
    expect(CI_ERROR_CODE.WAIT_TIMEOUT).toBe(112);
  });

  test('平台全局码落在既有区段(沿用平台定义, 不新建 200/300/500 段)', () => {
    // CLAUDE.md「响应协议」: 0 成功 / 101 参数错误 / 110 业务异常 / 401 未登录 / 403 无权限
    expect(CI_ERROR_CODE.OK).toBe(0);
    expect(CI_ERROR_CODE.INVALID).toBe(101);
    expect(CI_ERROR_CODE.BUSINESS).toBe(110);
    expect(CI_ERROR_CODE.UNAUTHORIZED).toBe(401);
    expect(CI_ERROR_CODE.FORBIDDEN).toBe(403);
    // CI 新增的两档必须与平台码不冲突
    expect(CI_ERROR_CODE.NOT_PASSED).not.toBe(CI_ERROR_CODE.BUSINESS);
    expect(CI_ERROR_CODE.WAIT_TIMEOUT).not.toBe(CI_ERROR_CODE.NOT_PASSED);
  });

  test('RunStatus 六态与 CI_RUN_STATUS 完全一致', () => {
    const backend = parsePyIntConstants(py, 'RunStatus');
    // 后端还有 ALL / IN_FLIGHT / TERMINAL 等元组常量, 解析时已被跳过
    expect(Object.keys(backend).sort()).toEqual(Object.keys(CI_RUN_STATUS).sort());
    for (const [k, v] of Object.entries(backend)) {
      expect({ [k]: (CI_RUN_STATUS as Record<string, number>)[k] }).toEqual({ [k]: v });
    }
  });

  test('FR-015: 3(测试未通过) 与 5(平台执行失败) 必须可区分', () => {
    // 一个是测试红了、一个是平台坏了 —— 文案与 Tag 颜色都不能混
    expect(CI_RUN_STATUS.FAILED).toBe(3);
    expect(CI_RUN_STATUS.ERROR).toBe(5);
    expect(CI_RUN_STATUS_LABELS[3]).not.toBe(CI_RUN_STATUS_LABELS[5]);
    expect(CI_RUN_STATUS_LABELS[3]).toBe('未通过');
    expect(CI_RUN_STATUS_LABELS[5]).toBe('执行失败');
    expect(CI_RUN_STATUS_COLORS[3]).not.toBe(CI_RUN_STATUS_COLORS[5]);
  });

  test('LABELS / COLORS 覆盖全部六态且无多余键', () => {
    const statuses = Object.values(CI_RUN_STATUS);
    expect(Object.keys(CI_RUN_STATUS_LABELS).map(Number).sort()).toEqual([...statuses].sort());
    expect(Object.keys(CI_RUN_STATUS_COLORS).map(Number).sort()).toEqual([...statuses].sort());
  });
});
