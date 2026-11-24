/**
 * `src/utils/tool.ts` 单元测试 —— 工具页(编解码 / 随机 / JSON / JWT)的共用纯函数。
 *
 * 这些函数被 Codec / RandomGen / JsonDiff / JwtDecoder 等多个页面复用,
 * 一处改错会同时坏掉几个工具。
 */
import {
  base64ToBase64Url,
  base64ToUtf8,
  base64UrlToBase64,
  decodeJwt,
  deepEqual,
  diffJson,
  formatJson,
  htmlEscape,
  htmlUnescape,
  jwtExpiry,
  minifyJson,
  RANDOM_CHARSETS,
  randomInt,
  randomString,
  utf8ToBase64,
  uuidV4,
  urlDecode,
  urlEncode,
} from '@/utils/tool';

describe('Base64 编解码', () => {
  test('ASCII 往返', () => {
    expect(base64ToUtf8(utf8ToBase64('hello world'))).toBe('hello world');
  });

  test('中文与 emoji 往返(btoa 直接吃中文会抛错, 所以必须走 TextEncoder)', () => {
    for (const s of ['测试用例', 'Pity 平台 🎉', '混合abc中文123']) {
      expect(base64ToUtf8(utf8ToBase64(s))).toBe(s);
    }
  });

  test('空串与纯空白输入不抛异常', () => {
    expect(utf8ToBase64('')).toBe('');
    expect(base64ToUtf8('')).toBe('');
    expect(base64ToUtf8('   ')).toBe('');
  });

  test('自动剥空白并补齐 padding(调用方常粘来不规范的串)', () => {
    const encoded = utf8ToBase64('hello');
    expect(base64ToUtf8(`  ${encoded.slice(0, 3)} \n ${encoded.slice(3)}  `)).toBe('hello');
    expect(base64ToUtf8(encoded.replace(/=+$/, ''))).toBe('hello');
  });

  test('Base64URL ↔ 标准 Base64', () => {
    const std = utf8ToBase64('{"sub":"u1"}');
    const url = base64ToBase64Url(std);
    expect(url).not.toContain('=');
    expect(url).not.toContain('+');
    expect(url).not.toContain('/');
    expect(base64ToUtf8(base64UrlToBase64(url))).toBe('{"sub":"u1"}');
  });

  test('url 形式补齐 padding 后可直接解码', () => {
    const noPad = base64ToBase64Url(utf8ToBase64('中文payload'));
    expect(base64ToUtf8(base64UrlToBase64(noPad))).toBe('中文payload');
  });
});

describe('URL / HTML 转义', () => {
  test('urlEncode/urlDecode 往返', () => {
    for (const s of ['a b', '中 文', 'a&b=c', '100%']) {
      expect(urlDecode(urlEncode(s))).toBe(s);
    }
  });

  test('urlDecode 把 + 当空格(表单编码语义), 但坏输入返回原文而不是抛异常', () => {
    expect(urlDecode('a+b')).toBe('a b');
    expect(urlDecode('%E0%A4%A')).toBe('%E0%A4%A');
  });

  test('htmlEscape 覆盖五个敏感字符', () => {
    expect(htmlEscape(`<a href="x" onclick='y'>&</a>`)).toBe(
      '&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;&lt;/a&gt;',
    );
  });

  test('htmlEscape/htmlUnescape 往返', () => {
    for (const s of ['<b>粗体</b>', 'a & b', `"引号" '单引号'`]) {
      expect(htmlUnescape(htmlEscape(s))).toBe(s);
    }
  });

  test('未知实体原样保留', () => {
    expect(htmlUnescape('&copy;')).toBe('&copy;');
  });
});

describe('随机数(走 getRandomValues, 不用 Math.random)', () => {
  test('uuidV4 格式与版本位', () => {
    const id = uuidV4();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(new Set([uuidV4(), uuidV4(), uuidV4()]).size).toBe(3);
  });

  test('randomString 长度与字符集约束', () => {
    const s = randomString(24, RANDOM_CHARSETS.hex);
    expect(s).toHaveLength(24);
    expect(s).toMatch(/^[0-9a-f]{24}$/);
    expect(randomString(10, '')).toBe('');
    expect(randomString(0, RANDOM_CHARSETS.number)).toBe('');
  });

  test('randomString 长字符集不会死循环', () => {
    expect(randomString(5, RANDOM_CHARSETS.symbol)).toHaveLength(5);
  });

  test('randomInt 落在闭区间内', () => {
    for (let i = 0; i < 200; i += 1) {
      const v = randomInt(1, 6);
      expect(v).toBeGreaterThanOrEqual(1);
      expect(v).toBeLessThanOrEqual(6);
    }
  });

  test('randomInt 单点区间与反向参数', () => {
    expect(randomInt(5, 5)).toBe(5);
    expect(randomInt(10, 1)).toBeGreaterThanOrEqual(1);
    expect(randomInt(10, 1)).toBeLessThanOrEqual(10);
  });
});

describe('deepEqual', () => {
  test('基本类型与 null', () => {
    expect(deepEqual(1, 1)).toBe(true);
    expect(deepEqual('a', 'a')).toBe(true);
    expect(deepEqual(null, null)).toBe(true);
    expect(deepEqual(null, {})).toBe(false);
    expect(deepEqual(1, '1')).toBe(false);
  });

  test('NaN 与 NaN 视为相等(否则 JSON 对比永远报差异)', () => {
    expect(deepEqual(Number.NaN, Number.NaN)).toBe(true);
  });

  test('数组与对象不等价', () => {
    expect(deepEqual([1, 2], [1, 2])).toBe(true);
    expect(deepEqual([1, 2], { 0: 1, 1: 2 })).toBe(false);
  });

  test('嵌套结构与键顺序无关', () => {
    expect(deepEqual({ a: { b: [1, { c: 2 }] } }, { a: { b: [1, { c: 2 }] } })).toBe(true);
    expect(deepEqual({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(true);
    expect(deepEqual({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });
});

describe('diffJson — 输出路径 + 差异类型', () => {
  test('完全相同返回空数组', () => {
    expect(diffJson({ a: 1 }, { a: 1 })).toEqual([]);
    expect(diffJson([1, 2], [1, 2])).toEqual([]);
  });

  test('类型不同直接报 type 并短路', () => {
    expect(diffJson({ a: 1 }, { a: '1' })).toEqual([
      { path: '$.a', kind: 'type', expected: 'number', actual: 'string' },
    ]);
    expect(diffJson(null, {})).toEqual([
      { path: '$', kind: 'type', expected: 'null', actual: 'object' },
    ]);
  });

  test('对象缺字段为 missing, 多字段为 extra', () => {
    expect(diffJson({ a: 1, b: 2 }, { a: 1 })).toEqual([
      { path: '$.b', kind: 'missing', expected: '2' },
    ]);
    expect(diffJson({ a: 1 }, { a: 1, c: 3 })).toEqual([
      { path: '$.c', kind: 'extra', actual: '3' },
    ]);
  });

  test('值不同为 value', () => {
    expect(diffJson({ a: 1 }, { a: 2 })).toEqual([
      { path: '$.a', kind: 'value', expected: '1', actual: '2' },
    ]);
  });

  test('嵌套路径正确拼接', () => {
    expect(diffJson({ a: { b: { c: 1 } } }, { a: { b: { c: 2 } } })).toEqual([
      { path: '$.a.b.c', kind: 'value', expected: '1', actual: '2' },
    ]);
    expect(diffJson([{ x: 1 }], [{ x: 9 }])).toEqual([path0Value(1, 9)]);
  });

  test('数组长度不同按位报 missing/extra', () => {
    expect(diffJson([1, 2, 3], [1, 2])).toEqual([{ path: '$[2]', kind: 'missing', expected: '3' }]);
    expect(diffJson([1], [1, 2])).toEqual([{ path: '$[1]', kind: 'extra', actual: '2' }]);
  });

  test('数组顺序差异不折叠(断言引擎认顺序)', () => {
    expect(diffJson([1, 2], [2, 1])).toHaveLength(2);
  });
});

function path0Value(a: number, b: number) {
  return { path: '$[0].x', kind: 'value', expected: String(a), actual: String(b) };
}

describe('formatJson / minifyJson', () => {
  test('格式化带缩进', () => {
    const r = formatJson('{"a":1,"b":[1,2]}');
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.text).toBe('{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}');
  });

  test('非法 JSON 返回错误说明而不是抛异常', () => {
    const r = formatJson('{a:1}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.length).toBeGreaterThan(0);
  });

  test('压缩成单行', () => {
    const r = minifyJson('{\n  "a": 1\n}');
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.text).toBe('{"a":1}');
    expect(minifyJson('nope').ok).toBe(false);
  });
});

describe('decodeJwt — 只解码不验签', () => {
  const makeJwt = (payload: Record<string, unknown>) => {
    const h = base64ToBase64Url(utf8ToBase64(JSON.stringify({ alg: 'HS256', typ: 'JWT' })));
    const p = base64ToBase64Url(utf8ToBase64(JSON.stringify(payload)));
    return `${h}.${p}.signature-part`;
  };

  test('三段都能解出来才算成功', () => {
    const token = makeJwt({ sub: 'user1', exp: 1900000000 });
    const r = decodeJwt(token);
    expect(r.error).toBeUndefined();
    expect(r.header).toEqual({ alg: 'HS256', typ: 'JWT' });
    expect(r.payload).toEqual({ sub: 'user1', exp: 1900000000 });
    expect(r.signature).toBe('signature-part');
  });

  test('空输入与段数不对都给中文说明', () => {
    expect(decodeJwt('')).toEqual({ error: '请输入 JWT' });
    expect(decodeJwt('a.b').error).toContain('三段');
    expect(decodeJwt('a.b.c.d').error).toContain('三段');
  });

  test('损坏的段返回解码失败而不是抛异常', () => {
    const r = decodeJwt('!!!.###.%%%');
    expect(r.error).toBeDefined();
    expect(r.error).toContain('解码失败');
  });
});

describe('jwtExpiry', () => {
  test('无 payload 返回空对象', () => {
    expect(jwtExpiry(undefined)).toEqual({});
    expect(jwtExpiry()).toEqual({});
  });

  test('提取 exp/iat 并判定过期', () => {
    const now = Math.floor(Date.now() / 1000);
    const future = jwtExpiry({ exp: now + 3600, iat: now - 60 });
    expect(future.expired).toBe(false);
    expect(future.expiresInSec).toBeGreaterThan(3500);

    const past = jwtExpiry({ exp: now - 100 });
    expect(past.expired).toBe(true);
    expect(past.expiresInSec).toBeLessThan(0);
  });

  test('没有 exp 时不判定过期(只给 iat)', () => {
    expect(jwtExpiry({ iat: 1 })).toEqual({ exp: undefined, iat: 1 });
    expect(jwtExpiry({ sub: 'x' })).toEqual({ exp: undefined, iat: undefined });
  });

  test('exp 不是数字时按缺失处理', () => {
    expect(jwtExpiry({ exp: 'tomorrow' }).expired).toBeUndefined();
  });
});
