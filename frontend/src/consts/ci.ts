/**
 * 持续集成(CI)的前端镜像 —— 权威定义在后端 `backend/app/enums/CiEnum.py`
 *
 * constitution 原则 III: 前后端共享常量 MUST 单一出处, 两端 MUST 互相指认。
 * ⚠️ **改一处必须同时改另一处**, 契约见 `specs/004-ci/contracts/api.md` §0、§4。
 *
 * 本文件只是镜像, 不是第二份定义; 判定以 `code === 0` / `status` 为准,
 * 不要在页面里硬编码数字字面量 —— 一律引用这里的常量。
 */

/** CI 相关业务码(与后端 `CiErrorCode` 对齐, 落在既有 0/101/110 同区段) */
export const CI_ERROR_CODE = {
  /** 成功且测试通过 */
  OK: 0,
  /** 参数错误 */
  INVALID: 101,
  /** 业务异常(计划不存在 / 重复触发 / 凭据配置非法) */
  BUSINESS: 110,
  /** 测试未通过 —— 流水线据此阻断 */
  NOT_PASSED: 111,
  /** 等待超时, 执行仍在后台继续 —— 拿 run_id 轮询 */
  WAIT_TIMEOUT: 112,
  /** 凭据无效 / 已过期 / 已停用 */
  UNAUTHORIZED: 401,
  /** 凭据越权(跨项目)或角色不足 */
  FORBIDDEN: 403,
} as const;

/** `pity_ci_run.status` 六态(与后端 `RunStatus` 对齐) */
export const CI_RUN_STATUS = {
  PENDING: 0,
  RUNNING: 1,
  SUCCESS: 2,
  FAILED: 3,
  TIMEOUT: 4,
  ERROR: 5,
} as const;

/**
 * 六态 → 展示文案。
 * **`3`(测试未通过) 与 `5`(平台执行失败) 必须可区分** —— spec FR-015 / SC-006:
 * 一个是测试红了, 一个是平台坏了, 文案与颜色都不能混。
 */
export const CI_RUN_STATUS_LABELS: Record<number, string> = {
  0: '进行中',
  1: '进行中',
  2: '通过',
  3: '未通过',
  4: '超时',
  5: '执行失败',
};

/** 六态 → antd Tag 颜色(与 `CI_RUN_STATUS_LABELS` 同步维护) */
export const CI_RUN_STATUS_COLORS: Record<number, string> = {
  0: 'default',
  1: 'processing',
  2: 'success',
  3: 'error',
  4: 'warning',
  5: 'default',
};

/** 与后端 `CiEnum.TOKEN_PREFIX` 对齐 —— 示例片段里的凭据占位符(D10) */
export const CI_TOKEN_PREFIX = 'pity_ci_';
/** 接入示例片段里的凭据占位符: **绝不能填真实凭据**(片段要被粘进 Git 仓库) */
export const CI_TOKEN_PLACEHOLDER = 'YOUR_PITY_CI_TOKEN';

/** 等待语义默认值(决定 Q3: 默认不等待) */
export const CI_WAIT_DEFAULT = false;
export const CI_WAIT_TIMEOUT_DEFAULT_SEC = 300;
export const CI_WAIT_TIMEOUT_MAX_SEC = 1800;

/** 集成配置字段上限(与后端 `CiEnum` 对齐) */
export const CI_INTEGRATION_NAME_MAX_LEN = 32;
export const CI_EXTERNAL_BUILD_ID_MAX_LEN = 64;
export const CI_EXTERNAL_URL_MAX_LEN = 255;

/**
 * 允许渲染成链接的 URL scheme(与后端 `CiEnum.ALLOWED_URL_SCHEMES` 对齐)。
 *
 * `external_url` 由**调用方**提供, 会被历史面板渲染成可点链接。
 * React 18 对 `javascript:` href **只在 dev 打 warning、不阻断** ——
 * 所以前端必须再校验一次(纵深防御), 后端 schema 的白名单是第一道。
 */
export const CI_ALLOWED_URL_SCHEMES: string[] = ['http', 'https'];

/** 该 URL 是否可以安全渲染成 `<a href>` —— 只认白名单 scheme */
export function isSafeHttpUrl(url?: string | null): boolean {
  if (!url) return false;
  const matched = /^([a-zA-Z][a-zA-Z0-9+.-]*):\/\//.exec(url);
  if (!matched) return false;
  return CI_ALLOWED_URL_SCHEMES.includes(matched[1].toLowerCase());
}
