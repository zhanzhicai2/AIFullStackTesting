import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import { PityResponse } from '@/services/auth';
import { CI_RUN_STATUS } from '@/consts/ci';

// 持续集成(CI)的接口封装 —— 8 个端点
// 契约: specs/004-ci/contracts/api.md
//
// ⚠️ CI 端点的鉴权 header 与平台同名(`token`), 但**值是 pity_ci_ 前缀的长期凭据**,
// 不是 JWT —— 走的是后端 `CIPermission()`, 见 contracts §1。

/** 集成配置(凭据) —— **响应里永远没有完整明文**, 只有前缀 */
export interface CiIntegration {
  id: number;
  project_id: number;
  name: string;
  token_prefix: string;
  plan_id: number | null;
  callback_url: string | null;
  enabled: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
  create_user: number;
}

/** 签发响应 —— `token` **仅此一次出现** */
export interface CiIntegrationIssued extends CiIntegration {
  token: string;
}

export interface CiIntegrationForm {
  id?: number;
  project_id: number;
  name: string;
  plan_id?: number | null;
  callback_url?: string | null;
  /** 不传 = 默认 1 年; 显式 null = 长期有效(决定 Q4) */
  expires_at?: string | null;
}

/** 一次触发的完整结果(契约 §3.2 同构) */
export interface CiRun {
  run_id: number;
  status: number;
  integration_id?: number;
  project_id: number;
  plan_id: number;
  plan_name: string | null;
  env: number[];
  external_build_id: string | null;
  external_url: string | null;
  success_count: number;
  failed_count: number;
  error_count: number;
  skipped_count: number;
  pass_rate: number;
  report_ids: number[];
  report_url: string | null;
  error_msg: string | null;
  cost: string | null;
  waited: boolean;
  wait_timeout: boolean;
  started_at: string | null;
  finished_at: string | null;
  created_at?: string | null;
}

export interface CiRunForm {
  plan_id?: number;
  env?: number[];
  /** 默认 false(决定 Q3: 轮询为主推姿势) */
  wait?: boolean;
  timeout_sec?: number;
  external_build_id?: string;
  external_url?: string;
}

export interface CiRunListParams {
  project_id: number;
  page?: number;
  size?: number;
  plan_id?: number;
  status?: number;
  start_time?: string;
  end_time?: string;
}

// ---------------------------------------------------------------------------
// 集成配置管理 —— Permission(MANAGER), 仅 admin/superAdmin
// ---------------------------------------------------------------------------

/** 集成配置列表 */
export async function listCiIntegrations(params: {
  project_id: number;
  page?: number;
  size?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ci/integration/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

/**
 * 签发凭据 —— **明文只在这一次响应里**, 前端必须用一次性弹窗展示后立刻丢弃
 */
export async function insertCiIntegration(data: CiIntegrationForm) {
  return request<PityResponse>(`${CONFIG.URL}/ci/integration/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 编辑集成配置(**不接受任何凭据字段** —— 凭据不可改, 只能删了重签) */
export async function updateCiIntegration(data: CiIntegrationForm) {
  return request<PityResponse>(`${CONFIG.URL}/ci/integration/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 启停(停用即吊销, 立即生效) */
export async function switchCiIntegration(id: number, status: boolean) {
  return request<PityResponse>(`${CONFIG.URL}/ci/integration/switch`, {
    method: 'GET',
    params: { id, status },
    headers: auth.headers(),
  });
}

/** 删除(逻辑删除, 保留触发记录可回溯) */
export async function deleteCiIntegration(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/ci/integration/delete`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

// ---------------------------------------------------------------------------
// 触发与查询 —— CIPermission(项目级长期凭据)
// ---------------------------------------------------------------------------

/**
 * 触发测试计划。
 * `wait=false`(默认)时 `code` 恒为 0 —— **受理成功 ≠ 测试通过**, 判定必须再查
 * `getCiRun`。等待语义下的业务码: 0 通过 / 111 未通过 / 112 超时 / 110 业务异常。
 */
export async function triggerCiRun(data: CiRunForm) {
  return request<PityResponse>(`${CONFIG.URL}/ci/run`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 查询单次触发结果(轮询用) */
export async function getCiRun(runId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ci/run/${runId}`, {
    method: 'GET',
    headers: auth.headers(),
  });
}

/** 触发历史(分页) */
export async function listCiRuns(params: CiRunListParams) {
  return request<PityResponse>(`${CONFIG.URL}/ci/run/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

/** 是否处于「可能仍在跑」的状态 —— 历史列表据此显示轮询/刷新提示 */
export function isCiRunInFlight(status: number): boolean {
  return status === CI_RUN_STATUS.PENDING || status === CI_RUN_STATUS.RUNNING;
}
