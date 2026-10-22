import request from '@/utils/request';
import CONFIG from '@/consts/config';
import auth from '@/utils/auth';
import { PityResponse } from '@/services/auth';

export interface ChatSession {
  id: number;
  title: string;
  vendor_id?: number;
  model_name?: string;
  preview?: string;
  updated_at?: string;
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  model_name?: string;
  tokens?: number;
}

export interface ChatModelOption {
  model_id: number;
  model_name: string;
}

export interface ChatVendorOption {
  vendor_id: number;
  vendor_name: string;
  vendor_code: string;
  models: ChatModelOption[];
}

// ---------------- 会话与消息 CRUD ----------------

export async function listChatSessions() {
  return request<PityResponse>(`${CONFIG.URL}/ai/chat/session/list`, {
    method: 'GET',
    headers: auth.headers(),
  });
}

export async function insertChatSession(data: { vendor_id?: number; model_id?: number }) {
  return request<PityResponse>(`${CONFIG.URL}/ai/chat/session/insert`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function updateChatSession(data: {
  session_id: number;
  title?: string;
  vendor_id?: number;
  model_id?: number;
}) {
  return request<PityResponse>(`${CONFIG.URL}/ai/chat/session/update`, {
    method: 'POST',
    data,
    headers: auth.headers(),
  });
}

export async function deleteChatSession(sessionId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ai/chat/session/delete`, {
    method: 'GET',
    params: { session_id: sessionId },
    headers: auth.headers(),
  });
}

export async function listChatMessages(sessionId: number) {
  return request<PityResponse>(`${CONFIG.URL}/ai/chat/message/list`, {
    method: 'GET',
    params: { session_id: sessionId },
    headers: auth.headers(),
  });
}

export async function listChatModels() {
  return request<PityResponse>(`${CONFIG.URL}/ai/chat/models`, {
    method: 'GET',
    headers: auth.headers(),
  });
}

// ---------------- 流式对话 ----------------
// 必须用原生 fetch: umi-request 基于 umi-fetch, 一定读完整个 body 才 resolve, 拿不到流。
// 也刻意不用 EventSource: 它不能自定义 header, token 只能塞 query string,
// 会被后端 main.py 的 request_info 依赖记进 logs/pity_info.log。

export interface StreamHandlers {
  onContent: (piece: string) => void;
  onError?: (msg: string) => void;
  onDone?: () => void;
}

export async function streamChat(
  payload: { session_id: number; content: string; vendor_id?: number; model_id?: number },
  handlers: StreamHandlers,
  signal?: AbortSignal
) {
  const res = await fetch(`${CONFIG.URL}/ai/chat/stream`, {
    method: 'POST',
    headers: auth.headers(),
    body: JSON.stringify(payload),
    signal,
  });

  // 鉴权失败时后端返回 application/json(不是 SSE), 这里必须先判 content-type,
  // 否则会拿着错误 body 去解析 SSE, 得到一堆看不懂的乱码
  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('text/event-stream')) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.msg || `流式请求失败(HTTP ${res.status})`);
  }
  if (!res.body) {
    throw new Error('当前浏览器不支持流式响应');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  // SSE 以空行分帧, 帧内是若干 event:/data: 行
  function handleFrame(frame: string) {
    let event = 'message';
    const dataLines: string[] = [];
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return;
    const raw = dataLines.join('\n');
    if (raw === '[DONE]') {
      handlers.onDone?.();
      return;
    }
    try {
      const obj = JSON.parse(raw);
      if (event === 'error') {
        handlers.onError?.(obj.error || '生成失败');
      } else if (obj.content) {
        handlers.onContent(obj.content);
      }
    } catch {
      // 心跳注释行或厂商夹带的非 JSON, 忽略
    }
  }

  try {
    // ★ 这个 while 里的 read() 本身可能抛: 后端生成器崩溃时,
    //   客户端拿到的是被截断的响应体(网络层错误), 而不是干净的 EOF。
    //   所以外层调用方必须 catch, 不能只依赖 [DONE]
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // stream: true 必须, 否则多字节 UTF-8 字符会被截断成乱码
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';
      frames.forEach(handleFrame);
    }
  } finally {
    reader.releaseLock?.();
  }
}