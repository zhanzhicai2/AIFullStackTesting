import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import { PityResponse } from '@/services/auth';

export interface DataFactoryColumn {
  name: string;
  type: string;
  rule: Record<string, any>;
  unique?: boolean;
  nullable?: boolean;
  default?: any;
  comment?: string;
}

export interface DataFactoryDataset {
  id: number;
  name: string;
  env: number;
  project_id?: number;
  database_id?: number;
  table_name?: string;
  columns: string; // JSON 字符串
  count: number;
  seed: number;
  remark?: string;
  status: number;
  created_at?: string;
  updated_at?: string;
}

export interface GeneratePayload {
  dataset_id?: number;
  columns?: string;
  count?: number;
  seed?: number;
  rows?: Record<string, any>[];
}

export interface TableColumn {
  name: string;
  type: string;
  nullable: boolean;
  default?: any;
  primary_key: boolean;
  autoincrement: boolean;
}

export interface AiParseResult {
  rules: {
    count: number;
    columns: DataFactoryColumn[];
  };
  warnings: string[];
}

// ---------- 数据集 ----------

export async function listDataFactoryDatasets(params: {
  page: number;
  size: number;
  env?: number;
  name?: string;
  project_id?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/dataset/list`, {
    method: 'GET',
    params,
    headers: auth.headers(),
  });
}

export async function queryDataFactoryDataset(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/dataset/detail`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

export async function insertDataFactoryDataset(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/dataset/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function updateDataFactoryDataset(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/dataset/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function deleteDataFactoryDataset(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/dataset/delete`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

// ---------- 生成 / 导出 / 写库 / 绑定 ----------

export async function generateData(payload: GeneratePayload) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/generate`, {
    method: 'POST',
    data: payload,
    headers: auth.headers(),
  });
}

export async function writeDataFactoryToDb(payload: GeneratePayload & { database_id: number; table_name: string }) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/write-db`, {
    method: 'POST',
    data: payload,
    headers: auth.headers(),
  });
}

export async function bindDataFactoryToCase(
  payload: GeneratePayload & { case_id: number; env: number; name_prefix?: string; replace?: boolean }
) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/bind-case`, {
    method: 'POST',
    data: payload,
    headers: auth.headers(),
  });
}

/**
 * 导出文件下载。
 * 不能用 request(umi-request): 它会把 body 读完再 resolve, 拿不到文件流,
 * 参考 services/chat.ts 的原生 fetch 模式。
 */
export async function downloadDataFactoryFile(
  payload: GeneratePayload & { file_type: string; table_name?: string },
  filename: string
) {
  const res = await fetch(`${CONFIG.URL}/datafactory/export`, {
    method: 'POST',
    headers: auth.headers(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let msg = `导出失败(HTTP ${res.status})`;
    try {
      const err = await res.json();
      if (err?.msg) msg = err.msg;
    } catch (e) {
      // 响应体不是 JSON, 保留默认文案
    }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(href);
}

// ---------- 目标表结构 ----------

export async function listDataFactoryTables(databaseId: number) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/table/list`, {
    method: 'GET',
    params: { database_id: databaseId },
    headers: auth.headers(),
  });
}

export async function listDataFactoryTableColumns(databaseId: number, table: string) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/table/columns`, {
    method: 'GET',
    params: { database_id: databaseId, table },
    headers: auth.headers(),
  });
}

// ---------- AI 规则翻译 ----------

export async function aiParseDataFactoryRules(payload: {
  prompt: string;
  vendor_id: number;
  model_id: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/datafactory/ai/parse`, {
    method: 'POST',
    data: payload,
    headers: auth.headers(),
  });
}
