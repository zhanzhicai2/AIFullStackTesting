/**
 * Cron 表达式解析 —— 纯前端, 支持标准 5 字段与带秒的 6 字段。
 *
 * 字段顺序: `[秒] 分 时 日 月 周`
 *
 * **刻意不支持 Quartz 的 `L` / `W` / `#`** —— 它们的语义与标准 cron 不同,
 * 半吊子支持会让用户以为"解析成功了", 到了调度器上却不是这个意思。
 * 遇到直接报错并说明, 比静默降级安全。
 *
 * **日 / 周的 OR 语义**(POSIX): 两个字段都有限制时, 满足**任一**即命中 ——
 * 这是 cron 的标准行为, 与 APScheduler 的 `day_of_week` + `day` 组合不同,
 * 后者是 AND。平台用的是 APScheduler, 这里的差异必须在页面上写清楚。
 */

export interface CronField {
  name: string;
  raw: string;
  /** 该字段所有可取值(已展开) */
  values: number[];
  /** 是否为 `*` / `?` —— 决定日/周要不要参与 OR 判定 */
  wildcard: boolean;
  min: number;
  max: number;
}

export interface CronParseResult {
  ok: boolean;
  error?: string;
  fields?: CronField[];
  /** 5 还是 6 段 */
  segments?: number;
  /** 接下来 N 次触发时间(本地时间) */
  next?: Date[];
}

interface FieldSpec {
  name: string;
  min: number;
  max: number;
  /** 允许 7 代表周日 */
  allowSeven?: boolean;
}

const SPECS_5: FieldSpec[] = [
  { name: '分', min: 0, max: 59 },
  { name: '时', min: 0, max: 23 },
  { name: '日', min: 1, max: 31 },
  { name: '月', min: 1, max: 12 },
  { name: '周', min: 0, max: 7, allowSeven: true },
];

const SPECS_6: FieldSpec[] = [
  { name: '秒', min: 0, max: 59 },
  ...SPECS_5,
];

const WEEKDAY_CN = ['日', '一', '二', '三', '四', '五', '六'];

/** 解析单个字段 → 展开后的取值集合 */
function parseField(raw: string, spec: FieldSpec): { values: number[]; wildcard: boolean } {
  const text = (raw || '').trim().toUpperCase();
  if (!text) throw new Error(`${spec.name}字段为空`);
  if (/[LW#]/.test(text)) {
    throw new Error(
      `${spec.name}字段用了 ${text} —— 这是 Quartz 语法(L/W/#), 本工具只解析标准 cron`,
    );
  }
  const wildcard = text === '*' || text === '?';
  const values = new Set<number>();

  for (const part of text.split(',')) {
    if (!part) throw new Error(`${spec.name}字段有空的取值段`);
    const [rangePart, stepPart, ...rest] = part.split('/');
    if (rest.length) throw new Error(`${spec.name}字段「${part}」斜杠过多`);
    const step = stepPart === undefined ? 1 : Number(stepPart);
    if (!Number.isInteger(step) || step <= 0) {
      throw new Error(`${spec.name}字段「${part}」的步长必须是正整数`);
    }

    let lo: number;
    let hi: number;
    if (rangePart === '*' || rangePart === '?') {
      lo = spec.min;
      hi = spec.max;
    } else if (rangePart.includes('-')) {
      const [a, b] = rangePart.split('-');
      lo = Number(a);
      hi = Number(b);
    } else {
      lo = Number(rangePart);
      hi = lo;
    }
    if (!Number.isInteger(lo) || !Number.isInteger(hi)) {
      throw new Error(`${spec.name}字段「${part}」不是合法的数字范围`);
    }
    if (lo < spec.min || hi > spec.max || lo > hi) {
      const allow = spec.allowSeven ? `(${spec.min}-${spec.max}, 7 也接受)` : `(${spec.min}-${spec.max})`;
      throw new Error(`${spec.name}字段「${part}」超出范围${allow}`);
    }
    for (let v = lo; v <= hi; v += step) {
      // 周字段里 7 与 0 等价, 统一归一到 0, 免得集合里有两个"周日"
      values.add(spec.allowSeven && v === 7 ? 0 : v);
    }
  }
  if (values.size === 0) throw new Error(`${spec.name}字段没有可取值`);
  return { values: [...values].sort((a, b) => a - b), wildcard };
}

/**
 * 从 `now` 的下一分钟起逐分钟匹配, 取前 count 次。
 *
 * 上限 5 年 —— `0 0 29 2 *` 这类表达式在 5 年内至少命中一次(含闰年)。
 * 扫不满就返回已找到的, 页面提示"未来 5 年内不会触发"。
 */
function nextRuns(fields: CronField[], withSeconds: boolean, count: number, now: Date): Date[] {
  const [sec, min, hour, dom, mon, dow] = withSeconds
    ? [fields[0], fields[1], fields[2], fields[3], fields[4], fields[5]]
    : [null, fields[0], fields[1], fields[2], fields[3], fields[4]];

  const domRestricted = !dom!.wildcard;
  const dowRestricted = !dow!.wildcard;
  const hasDom = new Set(dom!.values);
  const hasDow = new Set(dow!.values);
  const hasMon = new Set(mon!.values);
  const hasHour = new Set(hour!.values);
  const hasMin = new Set(min!.values);
  const hasSec = sec ? new Set(sec.values) : null;

  const out: Date[] = [];
  const cursor = new Date(now.getTime());
  cursor.setSeconds(withSeconds ? cursor.getSeconds() + 1 : 0, 0);
  if (!withSeconds) cursor.setMinutes(cursor.getMinutes() + 1);

  const deadline = now.getTime() + 5 * 366 * 24 * 3600 * 1000;
  let guard = 0;

  while (out.length < count && cursor.getTime() <= deadline && guard < 5_000_000) {
    guard += 1;
    if (hasSec && !hasSec.has(cursor.getSeconds())) {
      cursor.setSeconds(cursor.getSeconds() + 1);
      continue;
    }
    if (!hasMin.has(cursor.getMinutes())) {
      cursor.setMinutes(cursor.getMinutes() + 1, 0, 0);
      continue;
    }
    if (!hasHour.has(cursor.getHours())) {
      cursor.setHours(cursor.getHours() + 1, 0, 0, 0);
      continue;
    }
    if (!hasMon.has(cursor.getMonth() + 1)) {
      cursor.setMonth(cursor.getMonth() + 1, 1);
      cursor.setHours(0, 0, 0, 0);
      continue;
    }
    // 日 / 周: 两个都受限时是 OR(POSIX), 只有一个受限时只看那一个
    const domOk = hasDom.has(cursor.getDate());
    const dowOk = hasDow.has(cursor.getDay());
    let dayOk: boolean;
    if (domRestricted && dowRestricted) dayOk = domOk || dowOk;
    else if (domRestricted) dayOk = domOk;
    else if (dowRestricted) dayOk = dowOk;
    else dayOk = true;

    if (!dayOk) {
      cursor.setDate(cursor.getDate() + 1);
      cursor.setHours(0, 0, 0, 0);
      continue;
    }
    out.push(new Date(cursor.getTime()));
    if (withSeconds) cursor.setSeconds(cursor.getSeconds() + 1);
    else cursor.setMinutes(cursor.getMinutes() + 1, 0, 0);
  }
  return out;
}

/**
 * 解析 cron 表达式。`now` 只用于生成 next, 不影响解析。
 */
export function parseCron(expr: string, count = 5, now: Date = new Date()): CronParseResult {
  const raw = (expr || '').trim();
  if (!raw) return { ok: false, error: '请输入 cron 表达式' };
  const segments = raw.split(/\s+/);
  if (segments.length !== 5 && segments.length !== 6) {
    return {
      ok: false,
      error: `应为 5 段(分 时 日 月 周)或 6 段(秒 分 时 日 月 周), 当前 ${segments.length} 段`,
    };
  }
  const specs = segments.length === 6 ? SPECS_6 : SPECS_5;
  const fields: CronField[] = [];
  try {
    segments.forEach((seg, i) => {
      const spec = specs[i];
      const { values, wildcard } = parseField(seg, spec);
      fields.push({ name: spec.name, raw: seg, values, wildcard, min: spec.min, max: spec.max });
    });
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }

  return {
    ok: true,
    fields,
    segments: segments.length,
    next: nextRuns(fields, segments.length === 6, count, now),
  };
}

/** 给人看的字段说明 —— 页面用它渲染「这个表达式在什么时候跑」 */
export function describeField(f: CronField): string {
  if (f.wildcard) return `每${f.name}`;
  const { values } = f;
  const compact = (list: number[]): string =>
    list.length > 8 ? `${list.slice(0, 8).join(', ')}…(共 ${list.length} 个)` : list.join(', ');
  if (f.name === '周') return `星期${values.map((v) => WEEKDAY_CN[v]).join('/')}`;
  if (f.name === '月') return `月 ${compact(values)}`;
  if (f.name === '日') return `日 ${compact(values)}`;
  if (f.name === '时') return `时 ${compact(values)}`;
  if (f.name === '分') return `分 ${compact(values)}`;
  if (f.name === '秒') return `秒 ${compact(values)}`;
  return compact(values);
}

/** 常用表达式速查 */
export const CRON_PRESETS: { label: string; expr: string }[] = [
  { label: '每分钟', expr: '* * * * *' },
  { label: '每 5 分钟', expr: '*/5 * * * *' },
  { label: '每小时整点', expr: '0 * * * *' },
  { label: '每天 09:00', expr: '0 9 * * *' },
  { label: '工作日 09:00', expr: '0 9 * * 1-5' },
  { label: '每天 09:00/18:00', expr: '0 9,18 * * *' },
  { label: '每周一 09:00', expr: '0 9 * * 1' },
  { label: '每月 1 日 00:00', expr: '0 0 1 * *' },
  { label: '每 10 秒(6 段)', expr: '*/10 * * * * *' },
];
