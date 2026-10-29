import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import { PityResponse } from '@/services/auth';

// AI 工作台的四个场景共用的接口封装
// 契约: specs/001-ai-workbench/contracts/api.md

// ---------- 通用类型 ----------

export interface AiChatModel {
  model_id: number;
  model_name: string;
}

export interface AiVendorModels {
  vendor_id: number;
  vendor_name: string;
  vendor_code: string;
  models: AiChatModel[];
}

// ---------- 用例生成 ----------

export interface AiGenerateParams {
  project_id: number;
  directory_id: number;
  title: string;
  test_type: string;
  vendor_id: number;
  model_id: number;
  source_type: string;
  source_name?: string;
  content: string;
  params?: Record<string, unknown>;
}

export interface AiDraftSummary {
  id: number;
  batch_id: number;
  code: string;
  title: string;
  category: string;
  priority: string;
  status: number;
  steps: number;
  warn: string[] | null;
  case_id?: number;
  order?: number;
}

export interface AiGenerateResult {
  batch_id: number;
  case_count: number;
  total_tokens: number;
  warnings: string[];
  cases: AiDraftSummary[];
}

/** 生成用例草稿 */
export async function generateAiCases(data: AiGenerateParams) {
  return request<PityResponse>(`${CONFIG.URL}/ai/case/generate`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 草稿列表 */
export async function listAiDrafts(params: {
  batch_id: number;
  status?: number;
  page?: number;
  size?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/case/draft/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

/** 修改单条草稿(保存时后端会重新过一遍 14 条校验规则) */
export async function updateAiDraft(data: {
  draft_id: number;
  content?: Record<string, unknown>;
  title?: string;
  priority?: string;
  category?: string;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/case/draft/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 批量采纳 */
export async function acceptAiDrafts(draftIds: number[]) {
  return request<PityResponse>(`${CONFIG.URL}/ai/case/draft/accept`, {
    method: 'POST',
    data: { draft_ids: draftIds },
    headers: auth.headers(),
  });
}

/** 批量驳回 */
export async function rejectAiDrafts(draftIds: number[]) {
  return request<PityResponse>(`${CONFIG.URL}/ai/case/draft/reject`, {
    method: 'POST',
    data: { draft_ids: draftIds },
    headers: auth.headers(),
  });
}

/** 文档解析(PDF / Word / Markdown / 纯文本) */
export async function parseAiDocument(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return request<PityResponse>(`${CONFIG.URL}/ai/document/parse`, {
    method: 'POST',
    data: formData,
    // ⚠️ 必须不能带 Content-Type —— 让浏览器自己写 multipart 的 boundary,
    //    手工指定 application/json 会让后端收不到文件
    headers: auth.headers(false),
  });
}

// ---------- 分析类 ----------

export interface AiEvidence {
  cause: string;
  evidence: string[];
  unsupported?: string[];
  confidence: number;
  verify_checklist: string[];
}

export interface AiFixSuggestion {
  title: string;
  detail: string;
  patch?: string;
}

export interface AiHistoryItem {
  result_id: number;
  status: number;
  finished_at: string;
  cost: number;
  summary: string;
}

export interface AiAnalysisHistory {
  total: number;
  failed: number;
  passed: number;
  consecutive_failures: number;
  pattern: string;
  pattern_label: string;
  note: string;
  recent: AiHistoryItem[];
}

export interface AiBugAnalysis {
  analysis_id: number;
  summary: string;
  category: string;
  confidence: number;
  root_causes: AiEvidence[];
  fix_suggestions: AiFixSuggestion[];
  repro_steps: string[];
  history: AiAnalysisHistory;
}

/** Bug 分析(result_id 与 text 二选一) */
export async function analyzeAiBug(data: {
  result_id?: number;
  text?: string;
  vendor_id?: number;
  model_id?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/bug/analyze`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export interface AiErrorCluster {
  fingerprint: string;
  sample: string;
  count: number;
  first_at: string;
  last_at: string;
  scope: { cases: number; users: number };
}

export interface AiLogSpike {
  start_at: string;
  end_at: string;
  count: number;
  baseline: number;
}

export interface AiClusterResult {
  total_lines: number;
  error_clusters: AiErrorCluster[];
  spikes: AiLogSpike[];
  truncated: boolean;
}

/** 日志聚类 —— 纯确定性处理, 不调用模型 */
export async function clusterAiLogs(data: {
  source: string;
  file_id?: number;
  text?: string;
  since?: string;
  until?: string;
  max_lines?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/log/cluster`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

/** 错误簇归因 */
export async function analyzeAiLogCluster(data: {
  fingerprint: string;
  samples: string[];
  count: number;
  vendor_id?: number;
  model_id?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/log/analyze`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export interface AiSqlProblem {
  level: string;
  point: string;
  detail: string;
}

export interface AiSqlIndexSuggestion {
  table: string;
  ddl: string;
  reason: string;
}

export interface AiSqlAnalysis {
  analysis_id: number;
  confidence: number;
  elapsed_ms: number;
  plan: Array<Record<string, unknown>>;
  problems: AiSqlProblem[];
  index_suggestions: AiSqlIndexSuggestion[];
  rewritten_sql: string;
  table_refs: string[];
  sql?: string;
}

/** SQL 分析 */
export async function analyzeAiSql(data: {
  sql?: string;
  database_id: number;
  sql_history_id?: number;
  vendor_id?: number;
  model_id?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/sql/analyze`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export interface AiSlowSql {
  id: number;
  sql: string;
  elapsed: number;
  database_id: number;
  database_name?: string;
  create_user?: string;
  created_at: string;
}

/** 慢查询排行 */
export async function listAiSlowSql(params: {
  database_id?: number;
  page?: number;
  size?: number;
  min_elapsed?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/sql/slow`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

// ---------- 调用流水 ----------

export interface AiInvokeLog {
  id: number;
  scene: string;
  user_id: number;
  vendor_id: number;
  model_name: string;
  prompt_chars: number;
  tokens: number;
  elapsed: number;
  status: string;
  error_msg: string;
  created_at: string;
}

/** 模型调用流水 */
export async function listAiInvokeLogs(params: {
  page?: number;
  size?: number;
  scene?: string;
  model_name?: string;
  start_time?: string;
  end_time?: string;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/invoke/log`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}
