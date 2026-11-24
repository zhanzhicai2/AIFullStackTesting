/**
 * `src/utils/cron.ts` 单元测试 —— Cron 解析器工具页的核心逻辑。
 *
 * 重点锁住三类**设计决策**(改了就该红灯):
 *  1. 刻意不支持 Quartz 的 L/W/# —— 遇到直接报错, 不静默降级
 *  2. 日 / 周是 POSIX 的 OR 语义(与 APScheduler 的 AND 不同, 页面要写清楚)
 *  3. 周字段的 7 与 0 等价, 归一到 0
 */
import { CRON_PRESETS, describeField, parseCron } from '@/utils/cron';

// 固定 now, 让 next 的断言可复现(2026-01-05 是周一)
const NOW = new Date(2026, 0, 5, 8, 30, 15);

describe('parseCron — 输入校验', () => {
  test('空输入返回错误而不是抛异常', () => {
    expect(parseCron('')).toEqual({ ok: false, error: '请输入 cron 表达式' });
    expect(parseCron('   ').ok).toBe(false);
  });

  test('段数必须是 5 或 6', () => {
    expect(parseCron('* * * *').ok).toBe(false);
    expect(parseCron('* * * * * * *').ok).toBe(false);
    expect(parseCron('* * * *').error).toContain('5 段');
    expect(parseCron('0 * * * *').segments).toBe(5);
    expect(parseCron('0 0 * * * *').segments).toBe(6);
  });

  test('Quartz 的 L / W / # 语法直接拒绝, 并说明原因', () => {
    // 这是刻意的设计: 半吊子支持会让用户以为解析成功了, 到调度器上却不是这个意思
    for (const expr of ['0 0 L * *', '0 0 1W * *', '0 0 ? * 5#3']) {
      const r = parseCron(expr);
      expect({ expr, ok: r.ok }).toEqual({ expr, ok: false });
      expect(r.error).toContain('Quartz');
    }
  });

  test('越界值报错并给出允许范围', () => {
    const r = parseCron('60 * * * *'); // 分钟最大 59
    expect(r.ok).toBe(false);
    expect(r.error).toContain('分');
    expect(r.error).toContain('0-59');
    expect(parseCron('0 24 * * *').error).toContain('0-23');
  });

  test('非法步长报错', () => {
    expect(parseCron('*/0 * * * *').ok).toBe(false);
    expect(parseCron('*/-1 * * * *').ok).toBe(false);
    expect(parseCron('*/abc * * * *').ok).toBe(false);
    expect(parseCron('1/2/3 * * * *').error).toContain('斜杠过多');
  });

  test('空取值段报错', () => {
    expect(parseCron('1,,2 * * * *').ok).toBe(false);
    expect(parseCron(' * * * * *'.replace('*', '')).ok).toBe(false);
  });
});

describe('parseCron — 字段展开', () => {
  test('通配符标记为 wildcard(决定日/周是否参与 OR 判定)', () => {
    const r = parseCron('* * * * *', 1, NOW);
    expect(r.ok).toBe(true);
    expect(r.fields!.every((f) => f.wildcard)).toBe(true);
  });

  test('范围与步长正确展开', () => {
    const r = parseCron('*/15 9-11 * * *', 1, NOW);
    expect(r.ok).toBe(true);
    expect(r.fields![0].values).toEqual([0, 15, 30, 45]);
    expect(r.fields![1].values).toEqual([9, 10, 11]);
  });

  test('周字段的 7 归一到 0(周日等价)', () => {
    const r = parseCron('0 9 * * 7', 1, NOW);
    expect(r.ok).toBe(true);
    expect(r.fields![4].values).toEqual([0]);
    expect(r.fields![4].values).not.toContain(7);
  });

  test('5 段与 6 段的字段名正确', () => {
    expect(parseCron('* * * * *', 1, NOW).fields!.map((f) => f.name)).toEqual([
      '分',
      '时',
      '日',
      '月',
      '周',
    ]);
    expect(parseCron('* * * * * *', 1, NOW).fields!.map((f) => f.name)).toEqual([
      '秒',
      '分',
      '时',
      '日',
      '月',
      '周',
    ]);
  });
});

describe('parseCron — next 触发时间', () => {
  test('返回指定次数', () => {
    expect(parseCron('* * * * *', 3, NOW).next).toHaveLength(3);
    expect(parseCron('* * * * *', 1, NOW).next).toHaveLength(1);
  });

  test('每分钟表达式从 now 的下一分钟开始递增', () => {
    const next = parseCron('* * * * *', 3, NOW).next!;
    expect(next[0]).toEqual(new Date(2026, 0, 5, 8, 31, 0));
    expect(next[1]).toEqual(new Date(2026, 0, 5, 8, 32, 0));
    expect(next[2]).toEqual(new Date(2026, 0, 5, 8, 33, 0));
  });

  test('每天 09:00 命中的是 9 点整', () => {
    const next = parseCron('0 9 * * *', 2, NOW).next!;
    expect(next[0]).toEqual(new Date(2026, 0, 5, 9, 0, 0));
    expect(next[1]).toEqual(new Date(2026, 0, 6, 9, 0, 0));
  });

  test('日 / 周双受限时是 POSIX 的 OR 语义(任一命中即触发)', () => {
    // 2026-01-05 是周一; 「1 号或周一」在 1 月 5 日(周一)就该命中
    const r = parseCron('0 9 1 * 1', 3, new Date(2026, 0, 5, 8, 0, 0));
    expect(r.ok).toBe(true);
    const days = r.next!.map((d) => d.getDate());
    // 周一 5 号命中(周字段), 而不是等到 1 号(日字段)
    expect(days[0]).toBe(5);
    expect(r.next![0].getDay()).toBe(1);
  });

  test('6 段表达式按秒推进', () => {
    const next = parseCron('*/10 * * * * *', 3, new Date(2026, 0, 5, 8, 0, 0)).next!;
    expect(next.map((d) => d.getSeconds())).toEqual([10, 20, 30]);
  });

  test('5 年内不触发的表达式返回空数组而不是死循环', () => {
    // 2 月 30 日不存在 —— 必须靠 deadline/guard 收敛
    const r = parseCron('0 0 30 2 *', 1, NOW);
    expect(r.ok).toBe(true);
    expect(r.next).toEqual([]);
  });
});

describe('describeField — 页面文案', () => {
  const fieldOf = (expr: string) => parseCron(expr, 1, NOW).fields!;

  test('通配符显示为「每X」', () => {
    expect(describeField(fieldOf('* * * * *')[0])).toBe('每分');
    expect(describeField(fieldOf('* * * * *')[4])).toBe('每周');
  });

  test('周字段显示中文星期', () => {
    expect(describeField(fieldOf('0 9 * * 1-5')[4])).toBe('星期一/二/三/四/五');
    expect(describeField(fieldOf('0 9 * * 0')[4])).toBe('星期日');
  });

  test('取值过多时截断并给出总数', () => {
    const f = parseCron('0-59 * * * *', 1, NOW).fields![0];
    const text = describeField(f);
    expect(text).toContain('…(共 60 个)');
    expect(text.split(',').length).toBeLessThan(15);
  });
});

describe('CRON_PRESETS — 速查表里的每个表达式都必须能解析', () => {
  test('全部 presets 解析成功', () => {
    const failed = CRON_PRESETS.filter((p) => !parseCron(p.expr, 1, NOW).ok);
    expect(failed.map((p) => `${p.label}(${p.expr})`)).toEqual([]);
  });

  test('presets 标签唯一且非空', () => {
    const labels = CRON_PRESETS.map((p) => p.label);
    expect(new Set(labels).size).toBe(labels.length);
    expect(labels.every((l) => l.trim().length > 0)).toBe(true);
  });
});
