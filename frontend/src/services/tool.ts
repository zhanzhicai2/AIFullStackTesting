import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import type { PityResponse } from '@/services/auth';

/**
 * 实用工具的 4 个后端接口(`/tool/*`)。
 *
 * 这些都是**无状态计算**: 不写库、不产生副作用, 所以返回值里没有分页、没有 id。
 * 失败时后端返回 `code !== 0`, 这里统一不吞错 —— 页面各自决定怎么提示。
 *
 * 开发代理与 nginx 的前缀白名单都已包含 `/tool/`(见 `config/proxy.ts` 与
 * `nginx/nginx.conf`), 少任何一处的表现是生产 404 落到 SPA。
 */

/**
 * 从 umi-request 的返回值里提取错误文案。
 *
 * **为什么不能只看 `data.code`**: `src/utils/request.js` 的 `errorHandler` 是
 * `return response` 而不是 `throw` —— HTTP 层错误(404/500)不会 reject,
 * 于是 `useRequest` 的 `error` 是 undefined, `data` 是一个 Response 对象,
 * `data.code` 是 `undefined`。按 `data.code !== 0` 判断会得到 `data.msg`
 * (也是 undefined), 页面**一声不吭**。实测 `/tool/*` 未代理时就是这个表现。
 *
 * 所以三条路径都要覆盖: 业务码错 → 后端 msg; HTTP 错 → 状态码; 网络错 → error。
 */
export function toolError(data: any, error?: any): string | undefined {
  if (error?.message) return error.message;
  if (data && typeof data === 'object') {
    if (typeof data.code === 'number') {
      if (data.code === 0) return undefined;
      return data.msg || `请求失败(code=${data.code})`;
    }
    if (typeof data.status === 'number') {
      return data.status === 404
        ? 'HTTP 404 —— 接口不存在。开发环境请重启前端 dev server 以加载 /tool/ 代理, 并确认后端已加载 /tool 路由'
        : `HTTP ${data.status} —— 请求失败`;
    }
  }
  return undefined;
}

export interface JsonDiffResult {
  identical: boolean;
  diffs: string[];
  expected_type: string;
  actual_type: string;
}

/** JSON 深度对比 —— 复用断言引擎同款 `JsonCompare`, 文案与报告页一致 */
export async function diffJsonByBackend(expected: string, actual: string) {
  return request<PityResponse>(`${CONFIG.URL}/tool/json/diff`, {
    method: 'POST',
    data: { expected, actual },
    headers: auth.headers(),
  });
}

export interface NetIpDetail {
  ip: string;
  blocked: boolean;
  /** 命中的网段; 公网为 null */
  network: string | null;
  label: string;
}

export interface NetCheckResult {
  target: string;
  host: string;
  resolved: boolean;
  ips: NetIpDetail[];
  blocked: boolean;
  blocked_ips: string[];
  total: number;
}

/** 内网地址判断 —— 与 UI 自动化的 SSRF 拦截共用同一套网段规则 */
export async function checkNetTarget(target: string) {
  return request<PityResponse>(`${CONFIG.URL}/tool/net/check`, {
    method: 'POST',
    data: { target },
    headers: auth.headers(),
  });
}

export interface HashResult {
  digests: Record<string, string>;
  /** 填了密钥才有; 没填为 null */
  hmacs: Record<string, string> | null;
  bytes: number;
  char_count: number;
}

/** 摘要 / HMAC —— 走后端, 理由见后端 `routers/tool/crypto.py` 模块注释 */
export async function computeHash(text: string, key?: string, algorithms?: string[]) {
  return request<PityResponse>(`${CONFIG.URL}/tool/hash`, {
    method: 'POST',
    data: { text, key: key || null, algorithms: algorithms || null },
    headers: auth.headers(),
  });
}

export type CryptoAction = 'encrypt' | 'decrypt';
export type CryptoAlgorithm = 'aes' | 'des';
export type CryptoEncoding = 'hex' | 'base64';

export interface CryptoResult {
  result: string;
  algorithm: CryptoAlgorithm;
  action: CryptoAction;
  encoding: CryptoEncoding;
}

export async function runSymmetricCrypto(params: {
  action: CryptoAction;
  text: string;
  algorithm: CryptoAlgorithm;
  key: string;
  iv?: string | null;
  encoding: CryptoEncoding;
}) {
  return request<PityResponse>(`${CONFIG.URL}/tool/crypto/symmetric`, {
    method: 'POST',
    data: params,
    headers: auth.headers(),
  });
}
