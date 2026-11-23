/**
 * 实用工具页共用的纯函数。
 *
 * 这里的函数**不碰 Web Crypto 的 `subtle`** —— `crypto.subtle` 只在安全上下文
 * (https / localhost)可用, 平台内网部署走 http 时它是 `undefined`。
 * `crypto.getRandomValues` 没有这个限制, 所以随机数走它。
 * 摘要计算(MD5/SHA*)一律走后端, 见 `pages/Tool/HashTool.tsx`。
 */

/** UTF-8 → Base64(正确处理中文, `btoa` 直接吃中文会抛 InvalidCharacterError) */
export function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

/** Base64 → UTF-8; 自动剥空白并补齐 padding(调用方常从别处粘来不规范的串) */
export function base64ToUtf8(b64: string): string {
  const cleaned = (b64 || '').replace(/\s+/g, '');
  if (!cleaned) return '';
  const padded = cleaned + '='.repeat((4 - (cleaned.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder('utf-8', { fatal: false }).decode(bytes);
}

/** Base64URL(JWT 的 payload 段)→ 标准 Base64 */
export function base64UrlToBase64(input: string): string {
  const s = (input || '').replace(/-/g, '+').replace(/_/g, '/');
  return s + '='.repeat((4 - (s.length % 4)) % 4);
}

/** 标准 Base64 → Base64URL(去掉 padding 与 `+`/`/`) */
export function base64ToBase64Url(input: string): string {
  return (input || '').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** URL 编码(encodeURIComponent 语义, 用于 query 值) */
export function urlEncode(text: string): string {
  return encodeURIComponent(text);
}

export function urlDecode(text: string): string {
  try {
    return decodeURIComponent((text || '').replace(/\+/g, ' '));
  } catch {
    return text;
  }
}

/** HTML 实体转义 —— 用于把用户输入安全地塞进标签字符串 */
export function htmlEscape(text: string): string {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function htmlUnescape(text: string): string {
  const map: Record<string, string> = {
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&quot;': '"',
    '&#39;': "'",
    '&#x27;': "'",
    '&nbsp;': ' ',
  };
  return (text || '').replace(
    /&(?:amp|lt|gt|quot|nbsp|#39|#x27);/gi,
    (m) => map[m.toLowerCase()] ?? m,
  );
}

/** UUID v4 —— 自己拼, 不依赖 `crypto.randomUUID()`(部分旧浏览器/非安全上下文没有) */
export function uuidV4(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant
  const hex: string[] = [];
  for (let i = 0; i < 16; i += 1) hex.push(bytes[i].toString(16).padStart(2, '0'));
  return (
    `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}` +
    `-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
  );
}

export const RANDOM_CHARSETS = {
  number: '0123456789',
  alphaNum: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
  lower: 'abcdefghijklmnopqrstuvwxyz',
  upper: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
  hex: '0123456789abcdef',
  symbol: '!@#$%^&*()-_=+[]{};:,.<>?',
} as const;

export type RandomCharsetName = keyof typeof RANDOM_CHARSETS;

/** 从字符集里等概率抽样 —— 用 `getRandomValues` 而非 `Math.random` */
export function randomString(length: number, charset: string): string {
  if (!charset) return '';
  const limit = 256 - (256 % charset.length); // 拒绝采样, 消除取模偏差
  const out: string[] = [];
  while (out.length < length) {
    const buf = new Uint8Array(Math.max(1, Math.ceil((length - out.length) * 2)));
    crypto.getRandomValues(buf);
    for (const b of buf) {
      if (b < limit) out.push(charset[b % charset.length]);
      if (out.length >= length) break;
    }
  }
  return out.join('');
}

/** [min, max] 闭区间整数 —— 用 32 位随机数做缩放, 避免 `Math.random` 的精度问题 */
export function randomInt(min: number, max: number): number {
  const lo = Math.ceil(Math.min(min, max));
  const hi = Math.floor(Math.max(min, max));
  if (hi < lo) return lo;
  const range = hi - lo + 1;
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  // range 不是 2 的幂时用拒绝采样, 保证均匀
  const limit = Math.floor(0x100000000 / range) * range;
  let v = buf[0];
  while (v >= limit) {
    crypto.getRandomValues(buf);
    v = buf[0];
  }
  return lo + (v % range);
}

// ---------------------------------------------------------------------------
// 时区(用浏览器原生 Intl, 不引 moment-timezone —— 仓库只装了 moment)
// ---------------------------------------------------------------------------

/** 本机时区名, 如 `Asia/Shanghai` */
export function localTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** 把一个 Date 按指定时区渲染成 `YYYY-MM-DD HH:mm:ss` */
export function formatInTimeZone(date: Date, timeZone: string): string {
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).formatToParts(date);
    const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
    // en-CA 的日期顺序是 YYYY-MM-DD, 直接拼即可
    const hour = get('hour') === '24' ? '00' : get('hour');
    return `${get('year')}-${get('month')}-${get('day')} ${hour}:${get('minute')}:${get('second')}`;
  } catch {
    return date.toISOString();
  }
}

/** 时区偏移字符串, 如 `GMT+08:00`; 拿不到就返回空串 */
export function timeZoneOffset(date: Date, timeZone: string): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      hour12: false,
      timeZoneName: 'longOffset',
    }).formatToParts(date);
    const name = parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
    // `GMT` 本身表示 UTC, 需要补 `+00:00`
    return name === 'GMT' ? 'GMT+00:00' : name;
  } catch {
    return '';
  }
}

// ---------------------------------------------------------------------------
// JSON 差异(纯前端版, 用于 JSON 工具页的即时对比)
// ---------------------------------------------------------------------------

export type JsonDiffKind = 'missing' | 'extra' | 'type' | 'value';

export interface JsonDiffItem {
  path: string;
  kind: JsonDiffKind;
  expected?: string;
  actual?: string;
}

const brief = (v: unknown): string => {
  if (v === undefined) return 'undefined';
  let s: string;
  try {
    s = JSON.stringify(v);
  } catch {
    s = String(v);
  }
  if (s === undefined) s = String(v);
  return s.length > 120 ? `${s.slice(0, 117)}...` : s;
};

export function jsonType(v: unknown): string {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  return typeof v; // object / string / number / boolean / undefined
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (a === null || b === null) return false;
  if (typeof a !== 'object') return Number.isNaN(a) && Number.isNaN(b);
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a as object);
  const kb = Object.keys(b as object);
  if (ka.length !== kb.length) return false;
  return ka.every((k) =>
    deepEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]),
  );
}

/**
 * 递归对比两个已解析的 JSON 值, 输出**路径 + 差异类型**。
 *
 * 刻意不折叠「顺序不同」的数组差异 —— 用例断言里数组顺序通常是有意义的,
 * 折叠掉会让工具说"相同"而断言引擎说"不同"。
 */
export function diffJson(expected: unknown, actual: unknown, path = '$'): JsonDiffItem[] {
  const out: JsonDiffItem[] = [];
  const t1 = jsonType(expected);
  const t2 = jsonType(actual);

  if (t1 !== t2) {
    out.push({ path, kind: 'type', expected: t1, actual: t2 });
    return out;
  }
  if (t1 === 'array') {
    const a = expected as unknown[];
    const b = actual as unknown[];
    const max = Math.max(a.length, b.length);
    for (let i = 0; i < max; i += 1) {
      if (i >= a.length) {
        out.push({ path: `${path}[${i}]`, kind: 'extra', actual: brief(b[i]) });
      } else if (i >= b.length) {
        out.push({ path: `${path}[${i}]`, kind: 'missing', expected: brief(a[i]) });
      } else {
        out.push(...diffJson(a[i], b[i], `${path}[${i}]`));
      }
    }
    return out;
  }
  if (t1 === 'object') {
    const a = expected as Record<string, unknown>;
    const b = actual as Record<string, unknown>;
    for (const k of Object.keys(a)) {
      if (!(k in b)) out.push({ path: `${path}.${k}`, kind: 'missing', expected: brief(a[k]) });
      else out.push(...diffJson(a[k], b[k], `${path}.${k}`));
    }
    for (const k of Object.keys(b)) {
      if (!(k in a)) out.push({ path: `${path}.${k}`, kind: 'extra', actual: brief(b[k]) });
    }
    return out;
  }
  if (!deepEqual(expected, actual)) {
    out.push({ path, kind: 'value', expected: brief(expected), actual: brief(actual) });
  }
  return out;
}

/** JSON 格式化 —— 顺带给出行数与字节数, 页面直接展示 */
export function formatJson(text: string, indent = 2): { ok: true; text: string } | { ok: false; error: string } {
  try {
    const parsed = JSON.parse(text);
    return { ok: true, text: JSON.stringify(parsed, null, indent) };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

/** JSON 压缩成单行(请求 body 里常用) */
export function minifyJson(text: string): { ok: true; text: string } | { ok: false; error: string } {
  try {
    return { ok: true, text: JSON.stringify(JSON.parse(text)) };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

// ---------------------------------------------------------------------------
// JWT
// ---------------------------------------------------------------------------

export interface JwtParts {
  header?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  signature?: string;
  /** 解析失败时的中文说明 —— 页面直接展示, 不抛异常 */
  error?: string;
}

const decodeSegment = (seg: string): Record<string, unknown> => JSON.parse(base64ToUtf8(base64UrlToBase64(seg)));

/**
 * 解 JWT(只解码, **不验签**)。
 * 三个段都要能解出来才算成功 —— 只解 payload 会让明显损坏的 token 显示"有效"。
 */
export function decodeJwt(token: string): JwtParts {
  const raw = (token || '').trim();
  if (!raw) return { error: '请输入 JWT' };
  const parts = raw.split('.');
  if (parts.length !== 3) return { error: `JWT 应为三段(以 . 分隔), 当前只有 ${parts.length} 段` };
  try {
    const header = decodeSegment(parts[0]);
    const payload = decodeSegment(parts[1]);
    return { header, payload, signature: parts[2] };
  } catch (err) {
    return { error: `解码失败: ${err instanceof Error ? err.message : String(err)}` };
  }
}

/** 解析 JWT 的 `exp` / `iat`, 给出是否过期 —— 排查 401 时最常看的两个字段 */
export function jwtExpiry(payload?: Record<string, unknown>): {
  exp?: number;
  iat?: number;
  expired?: boolean;
  expiresInSec?: number;
} {
  if (!payload) return {};
  const exp = typeof payload.exp === 'number' ? payload.exp : undefined;
  const iat = typeof payload.iat === 'number' ? payload.iat : undefined;
  if (exp === undefined) return { exp, iat };
  const now = Math.floor(Date.now() / 1000);
  return { exp, iat, expired: exp < now, expiresInSec: exp - now };
}
