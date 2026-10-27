import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import { PityResponse } from '@/services/auth';

export interface UiPage {
  id: number;
  project_id: number;
  name: string;
  url?: string;
  parent?: number | null;
  description?: string;
  element_count?: number;
  children?: UiPage[];
}

export interface UiElement {
  id: number;
  project_id: number;
  page_id: number;
  name: string;
  strategy: string;
  locator: string;
  name_attr?: string;
  description?: string;
  status: number;
}

export interface UiAllowedDomain {
  id: number;
  project_id: number;
  domain: string;
  env?: number | null;
}

export interface UiNode {
  id: number;
  name: string;
  node_type: string;
  status: number;
  browser: string;
  headless: boolean;
  max_concurrency: number;
  version?: string;
}

export interface UiCase {
  id: number;
  name: string;
  directory_id: number;
  priority: string;
  status: number;
  base_url?: string;
  viewport?: string;
  timeout?: number;
  updated_at?: string;
}

export interface UiStep {
  action: string;
  element?: string;
  by?: string;
  value?: any;
  name?: string;
  text?: string;
  url?: string;
  state?: string;
  timeout?: number;
  files?: string[];
}

export interface UiCaseDetail {
  id: number;
  name: string;
  directory_id: number;
  priority: string;
  status: number;
  base_url: string;
  viewport: string;
  locale: string;
  timeout: number;
  browser: string;
  screenshot: boolean;
  steps: UiStep[];
}

export interface UiStepResult {
  index: number;
  action: string;
  target: string;
  strategy?: string;
  locator?: string;
  name_attr?: string;
  status: 'ok' | 'failed' | 'skipped';
  cost: number;
  error?: string;
  /** 失败原因分类 —— element_not_found / element_ambiguous / timeout / ... */
  reason?: string;
}

export interface UiRunResult {
  result_id?: number;
  status: number;
  status_label: string;
  cost: number;
  steps: UiStepResult[];
  assertions?: Array<{
    name: string;
    assert_type: string;
    expected: any;
    actually: any;
    status: boolean;
    msg?: string;
  }>;
  asserts: string;
  screenshot_url?: string;
  error?: string;
  error_reason?: string;
}

// ---------- 页面 ----------

export async function listUiPages(projectId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/page/list`, {
    method: 'GET',
    params: { project_id: projectId },
    headers: auth.headers(),
  });
}

export async function insertUiPage(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/page/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function updateUiPage(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/page/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function deleteUiPage(id: number, projectId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/page/delete`, {
    method: 'GET',
    params: { id, project_id: projectId },
    headers: auth.headers(),
  });
}

// ---------- 元素 ----------

export async function listUiElements(params: {
  project_id?: number;
  page_id?: number;
  status?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ui/element/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

export async function insertUiElement(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/element/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function updateUiElement(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/element/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function deleteUiElement(id: number, projectId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/element/delete`, {
    method: 'GET',
    params: { id, project_id: projectId },
    headers: auth.headers(),
  });
}

export async function updateUiElementStatus(data: {
  id: number;
  project_id: number;
  status: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ui/element/status`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

// ---------- 允许域名(SSRF 白名单) ----------

export async function listUiDomains(projectId: number, env?: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/domain/list`, {
    method: 'GET',
    params: { project_id: projectId, env },
    headers: auth.headers(),
  });
}

export async function insertUiDomain(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/domain/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function deleteUiDomain(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/domain/delete`, {
    method: 'POST',
    params: { id },
    headers: auth.headers(),
  });
}

// ---------- 执行节点 ----------

export async function listUiNodes() {
  return request<PityResponse>(`${CONFIG.URL}/ui/node/list`, {
    method: 'GET',
    headers: auth.headers(),
  });
}

export async function uiNodeHeartbeat(data?: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/node/heartbeat`, {
    method: 'POST',
    data: data || {},
    headers: auth.headers(),
  });
}

export async function deleteUiNode(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/node/delete`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

// ---------- UI 用例 ----------

export async function listUiCases(params: {
  project_id?: number;
  directory_id?: number;
  name?: string;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ui/case/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

export async function queryUiCase(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/case/detail`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

export async function insertUiCase(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/case/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function updateUiCase(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ui/case/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function deleteUiCase(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/case/delete`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

export async function runUiCase(data: { case_id: number; env?: number; node_id?: number }) {
  return request<PityResponse>(`${CONFIG.URL}/ui/case/run`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

// ---------- 执行中心 ----------

export interface UiExecution {
  id: number;
  executor: number;
  env: number;
  plan_id?: number;
  plan_name?: string;
  status: number;
  mode: number;
  cost?: string;
  start_at?: string;
  finished_at?: string;
  success_count: number;
  failed_count: number;
  error_count: number;
  skipped_count: number;
  /** 该报告里 UI 用例的数量与通过数 —— 与接口用例同一套口径 */
  ui_total: number;
  ui_success: number;
  ui_failed: number;
  ui_error: number;
  ui_percent: number;
}

export interface UiAttachment {
  case_id: number;
  name: string;
  url: string;
  file_path: string;
  file_size?: string;
}

export async function listUiExecutions(params: {
  page?: number;
  size?: number;
  start_time?: string;
  end_time?: string;
  executor?: string;
  deleted?: boolean;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ui/execution/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

export async function listUiRunningExecutions() {
  return request<PityResponse>(`${CONFIG.URL}/ui/execution/running`, {
    method: 'GET',
    headers: auth.headers(),
  });
}

export async function listUiAttachments(reportId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/execution/attachments`, {
    method: 'GET',
    params: { report_id: reportId },
    headers: auth.headers(),
  });
}

export async function rerunUiExecutions(payload: { env: number; case_id: number[] }) {
  return request<PityResponse>(`${CONFIG.URL}/ui/execution/rerun`, {
    method: 'POST',
    data: payload,
    headers: auth.headers(),
  });
}

export async function deleteUiExecution(reportId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ui/execution/delete`, {
    method: 'GET',
    params: { report_id: reportId },
    headers: auth.headers(),
  });
}

// ---------- 录制导入 ----------

export async function importUiRecord(data: {
  project_id: number;
  source: string;
  script: string;
  directory_id?: number;
  name?: string;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ui/record/import`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}
