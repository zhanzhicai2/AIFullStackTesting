import { useCallback, useEffect, useRef, useState } from 'react';
import { message as antdMessage } from 'antd';
import auth from '@/utils/auth';
import {
  listChatSessions,
  insertChatSession,
  updateChatSession,
  deleteChatSession,
  listChatMessages,
  listChatModels,
  streamChat,
  ChatMessage,
  ChatSession,
  ChatVendorOption,
} from '@/services/chat';

// Markdown 渲染节流间隔: bytemd Viewer 每次 value 变化都会全量重新解析 + SSR 高亮,
// 每个 token 都触发一次会让长回复明显卡顿
const FLUSH_INTERVAL = 200;

export default () => {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [vendors, setVendors] = useState<ChatVendorOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const bufferRef = useRef('');
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 切换会话时要中止上一条流, 否则旧会话的 token 会串到新会话的气泡里
  const currentIdRef = useRef<number | null>(null);

  useEffect(() => {
    currentIdRef.current = currentId;
  }, [currentId]);

  const stopStream = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setStreaming(false);
  }, []);

  const flush = useCallback(() => {
    timerRef.current = null;
    const text = bufferRef.current;
    setMessages((prev) =>
      prev.map((m, idx) =>
        idx === prev.length - 1 && m.role === 'assistant' && m.id === -1
          ? { ...m, content: text }
          : m
      )
    );
  }, []);

  const pushContent = useCallback(
    (piece: string) => {
      bufferRef.current += piece;
      if (!timerRef.current) {
        timerRef.current = setTimeout(flush, FLUSH_INTERVAL);
      }
    },
    [flush]
  );

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listChatSessions();
      if (!auth.response(res)) return [];
      const data = (res.data || []) as ChatSession[];
      setSessions(data);
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const selectSession = useCallback(
    async (id: number) => {
      if (currentIdRef.current === id) return;
      stopStream();
      setCurrentId(id);
      const res = await listChatMessages(id);
      if (!auth.response(res)) return;
      setMessages((res.data || []) as ChatMessage[]);
    },
    [stopStream]
  );

  const createSession = useCallback(
    async (vendorId?: number, modelId?: number) => {
      const res = await insertChatSession({ vendor_id: vendorId, model_id: modelId });
      if (!auth.response(res, true)) return null;
      const created = res.data as ChatSession;
      stopStream();
      setSessions((prev) => [created, ...prev]);
      setCurrentId(created.id);
      setMessages([]);
      return created;
    },
    [stopStream]
  );

  const removeSession = useCallback(
    async (id: number) => {
      const res = await deleteChatSession(id);
      if (!auth.response(res, true)) return;
      if (currentIdRef.current === id) {
        stopStream();
        setCurrentId(null);
        setMessages([]);
      }
      setSessions((prev) => prev.filter((s) => s.id !== id));
    },
    [stopStream]
  );

  const renameSession = useCallback(async (id: number, title: string) => {
    const res = await updateChatSession({ session_id: id, title });
    if (auth.response(res)) {
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
    }
  }, []);

  const switchModel = useCallback(
    async (sessionId: number, vendorId: number, modelId: number) => {
      const res = await updateChatSession({
        session_id: sessionId,
        vendor_id: vendorId,
        model_id: modelId,
      });
      if (auth.response(res)) {
        setSessions((prev) =>
          prev.map((s) => (s.id === sessionId ? { ...s, vendor_id: vendorId } : s))
        );
      }
    },
    []
  );

  const fetchModels = useCallback(async () => {
    const res = await listChatModels();
    if (!auth.response(res)) return;
    setVendors((res.data || []) as ChatVendorOption[]);
  }, []);

  const sendMessage = useCallback(
    async (content: string, vendorId?: number, modelId?: number) => {
      const sessionId = currentIdRef.current;
      if (!sessionId) {
        antdMessage.warning('请先新建一个会话');
        return;
      }
      if (streaming) return;

      stopStream();
      setStreaming(true);
      bufferRef.current = '';

      // 先乐观上屏: 用户消息 + 一条空的 assistant 占位
      const placeholder: ChatMessage = {
        id: -1,
        session_id: sessionId,
        role: 'assistant',
        content: '',
      };
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          session_id: sessionId,
          role: 'user',
          content,
        },
        placeholder,
      ]);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await streamChat(
          { session_id: sessionId, content, vendor_id: vendorId, model_id: modelId },
          {
            onContent: pushContent,
            onError: (msg) => antdMessage.error(msg),
          },
          controller.signal
        );
      } catch (e) {
        // 用户主动停止不算错误
        const err = e as Error;
        if (err.name !== 'AbortError') {
          antdMessage.error(err.message || '生成失败');
        }
      } finally {
        stopStream();
        // 以服务端落库的内容为准重新拉一次, 保证刷新后一致
        const res = await listChatMessages(sessionId);
        if (auth.response(res)) {
          setMessages((res.data || []) as ChatMessage[]);
        }
        fetchSessions();
      }
    },
    [streaming, pushContent, stopStream, fetchSessions]
  );

  return {
    sessions,
    currentId,
    messages,
    vendors,
    loading,
    streaming,
    fetchSessions,
    selectSession,
    createSession,
    removeSession,
    renameSession,
    switchModel,
    fetchModels,
    sendMessage,
    stopStream,
  };
};