import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import {PityResponse} from '@/services/auth';

export interface AIVendor {
  id: number;
  name: string;
  en_name?: string;
  code: string;
  api_key?: string;
  base_url?: string;
  console_url?: string;
  enable: boolean;
  builtin: boolean;
  sort: number;
  has_key?: boolean;
}

export interface AIVendorItem {
  vendor: AIVendor;
  model_count: number;
}

export interface AIModel {
  id: number;
  vendor_id: number;
  name: string;
  model_type: string;
  enable: boolean;
  source: number;
  params?: string;
  sort: number;
}

export interface AIModelBrief {
  name: string;
  model_type: string;
}

// ---------- 厂商 ----------

export async function listAIVendors() {
  return request<PityResponse>(`${CONFIG.URL}/ai/vendor/list`, {
    method: 'GET',
    headers: auth.headers(),
  });
}

export async function queryAIVendor(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/ai/vendor/query`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

export async function updateAIVendor(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ai/vendor/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

// ---------- 模型 ----------

export async function listAIModels(vendorId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ai/model/list`, {
    method: 'GET',
    params: { vendor_id: vendorId },
    headers: auth.headers(),
  });
}

export async function addAIModel(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ai/model/add`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function updateAIModel(data: Record<string, unknown>) {
  return request<PityResponse>(`${CONFIG.URL}/ai/model/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function deleteAIModel(id: number) {
  return request<PityResponse>(`${CONFIG.URL}/ai/model/delete`, {
    method: 'GET',
    params: { id },
    headers: auth.headers(),
  });
}

export async function fetchRemoteModels(vendorId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ai/model/fetch`, {
    method: 'POST',
    data: { vendor_id: vendorId },
    headers: auth.headers(),
  });
}

export async function listSystemModels(vendorCode: string) {
  return request<PityResponse>(`${CONFIG.URL}/ai/model/system`, {
    method: 'POST',
    data: { vendor_code: vendorCode },
    headers: auth.headers(),
  });
}

export async function importAIModels(data: {
  vendor_id: number;
  source: number;
  models: string[];
  model_types?: Record<string, string>;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/model/import`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}