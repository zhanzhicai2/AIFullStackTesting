import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import { PityResponse } from '@/services/auth';

// Mock 配置的管理接口封装
// 契约: specs/003-mock-config/contracts/api.md §1

export interface MockRule {
  id: number;
  project_id: number;
  name: string;
  method: string;
  path: string;
  path_type: number;
  priority: number;
  status_code: number;
  response_headers: string | null;
  response_body: string | null;
  delay: number;
  status: number;
  remark: string;
  created_at: string;
  update_user: number;
}

export interface MockRuleForm {
  id?: number;
  project_id: number;
  name: string;
  method: string;
  path: string;
  priority?: number;
  status_code?: number;
  response_headers?: string;
  response_body?: string;
  delay?: number;
  status?: number;
  remark?: string;
}

export interface MockRuleListParams {
  project_id: number;
  method?: string;
  path?: string;
  status?: number;
  page?: number;
  size?: number;
}

export interface MockRulePreviewParams {
  project_id: number;
  method: string;
  path: string;
  body?: string;
  headers?: string;
}

export interface MockRulePreviewResult {
  matched: boolean;
  rule: Pick<MockRule, 'id' | 'name' | 'method' | 'path' | 'priority' | 'status_code'> | null;
  status_code?: number;
  response_headers?: string;
  response_body?: string;
  delay?: number;
  reason?: string;
}

/** 规则列表(分页) */
export async function listMockRules(params: MockRuleListParams) {
  return request<PityResponse>(`${CONFIG.URL}/mock/rule/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

/** 新建规则 */
export async function insertMockRule(data: MockRuleForm) {
  return request<PityResponse>(`${CONFIG.URL}/mock/rule/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 更新规则 */
export async function updateMockRule(data: MockRuleForm) {
  return request<PityResponse>(`${CONFIG.URL}/mock/rule/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 删除规则(逻辑删除) */
export async function deleteMockRule(id: number, project_id: number) {
  return request<PityResponse>(`${CONFIG.URL}/mock/rule/delete`, {
    method: 'GET',
    params: { id, project_id },
    headers: auth.headers(),
  });
}

/** 启停规则 */
export async function updateMockRuleStatus(id: number, project_id: number, status: number) {
  return request<PityResponse>(`${CONFIG.URL}/mock/rule/status`, {
    method: 'POST',
    data: { id, project_id, status },
    headers: auth.headers(),
  });
}

/** 规则详情 */
export async function getMockRuleDetail(id: number, project_id: number) {
  return request<PityResponse>(`${CONFIG.URL}/mock/rule/detail`, {
    method: 'GET',
    params: { id, project_id },
    headers: auth.headers(),
  });
}

/** 规则调试(就地模拟一次匹配) */
export async function previewMockRule(data: MockRulePreviewParams) {
  return request<PityResponse>(`${CONFIG.URL}/mock/rule/preview`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}
