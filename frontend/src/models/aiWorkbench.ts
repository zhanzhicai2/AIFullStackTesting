import { useCallback, useState } from 'react';
import auth from '@/utils/auth';
import {
  AiBugAnalysis,
  AiClusterResult,
  AiDraftSummary,
  AiGenerateParams,
  AiGenerateResult,
  AiInvokeLog,
  AiSlowSql,
  AiSqlAnalysis,
  AiVendorModels,
  analyzeAiBug,
  analyzeAiLogCluster,
  analyzeAiSql,
  acceptAiDrafts,
  clusterAiLogs,
  generateAiCases,
  listAiDrafts,
  listAiInvokeLogs,
  listAiSlowSql,
  parseAiDocument,
  rejectAiDrafts,
  updateAiDraft,
} from '@/services/aiWorkbench';
import { listChatModels } from '@/services/chat';

/**
 * AI 工作台的前端状态(hooks 风格)
 *
 * 新文件一律用 hooks 风格(`@umijs/plugin-model`), 不混 dva model ——
 * 见 frontend/CLAUDE.md。
 *
 * **前端只做提前提示, 不做最终判定** —— 后端是最终裁决者(不合规的字段被丢弃)。
 * 前端放行、后端丢弃会造成「改了还是被丢弃」的困惑。
 */
export default () => {
  const [generating, setGenerating] = useState(false);
  const [generatingBug, setGeneratingBug] = useState(false);
  const [generatingLog, setGeneratingLog] = useState(false);
  const [generatingSql, setGeneratingSql] = useState(false);
  const [loading, setLoading] = useState(false);

  const [batchId, setBatchId] = useState<number | undefined>(undefined);
  const [drafts, setDrafts] = useState<AiDraftSummary[]>([]);
  const [draftTotal, setDraftTotal] = useState(0);
  const [generateResult, setGenerateResult] = useState<AiGenerateResult | null>(null);

  const [bugResult, setBugResult] = useState<AiBugAnalysis | null>(null);
  const [clusterResult, setClusterResult] = useState<AiClusterResult | null>(null);
  const [sqlResult, setSqlResult] = useState<AiSqlAnalysis | null>(null);
  const [slowSqls, setSlowSqls] = useState<AiSlowSql[]>([]);
  const [invokeLogs, setInvokeLogs] = useState<AiInvokeLog[]>([]);
  const [invokeLogTotal, setInvokeLogTotal] = useState(0);
  const [models, setModels] = useState<AiVendorModels[]>([]);

  /** 可选的对话模型(复用既有 /ai/chat/models) —— G1 就地指引靠它判断有没有可用模型 */
  const fetchModels = useCallback(async (): Promise<AiVendorModels[]> => {
    try {
      const res: any = await listChatModels();
      if (!auth.response(res)) return [];
      const data = (res.data || []) as AiVendorModels[];
      setModels(data);
      return data;
    } catch (e) {
      return [];
    }
  }, []);

  /** 生成用例草稿 */
  const generate = useCallback(async (params: AiGenerateParams): Promise<AiGenerateResult | null> => {
    setGenerating(true);
    try {
      const res: any = await generateAiCases(params);
      if (!auth.response(res)) return null;
      const data = res.data as AiGenerateResult;
      setGenerateResult(data);
      setBatchId(data.batch_id);
      return data;
    } finally {
      setGenerating(false);
    }
  }, []);

  /** 草稿列表 */
  const fetchDrafts = useCallback(
    async (id: number, status?: number, page = 1, size = 10) => {
      setLoading(true);
      try {
        const res: any = await listAiDrafts({ batch_id: id, status, page, size });
        if (!auth.response(res)) return [];
        setDrafts((res.data?.list || []) as AiDraftSummary[]);
        setDraftTotal(res.data?.total || 0);
        return res.data?.list || [];
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  /** 修改草稿 —— 保存后后端会重新过一遍 14 条校验规则, 返回新的告警 */
  const saveDraft = useCallback(
    async (payload: {
      draft_id: number;
      content?: Record<string, unknown>;
      title?: string;
      priority?: string;
      category?: string;
    }): Promise<string[] | null> => {
      const res: any = await updateAiDraft(payload);
      if (!auth.response(res)) return null;
      return (res.data?.warn || []) as string[];
    },
    [],
  );

  /** 批量采纳 */
  const acceptDrafts = useCallback(async (draftIds: number[]) => {
    const res: any = await acceptAiDrafts(draftIds);
    return res;
  }, []);

  /** 批量驳回 */
  const rejectDrafts = useCallback(async (draftIds: number[]) => {
    const res: any = await rejectAiDrafts(draftIds);
    return res;
  }, []);

  /** 文档解析 */
  const parseDocument = useCallback(async (file: File) => {
    const res: any = await parseAiDocument(file);
    if (!auth.response(res)) return null;
    return res.data;
  }, []);

  /** Bug 分析 */
  const analyzeBug = useCallback(
    async (payload: { result_id?: number; text?: string; vendor_id?: number; model_id?: number }) => {
      setGeneratingBug(true);
      try {
        const res: any = await analyzeAiBug(payload);
        if (!auth.response(res)) return null;
        const data = res.data as AiBugAnalysis;
        setBugResult(data);
        return data;
      } finally {
        setGeneratingBug(false);
      }
    },
    [],
  );

  /** 日志聚类 —— 纯确定性, 不调用模型 */
  const clusterLogs = useCallback(
    async (payload: {
      source: string;
      file_id?: number;
      text?: string;
      since?: string;
      until?: string;
      max_lines?: number;
    }) => {
      setGeneratingLog(true);
      try {
        const res: any = await clusterAiLogs(payload);
        if (!auth.response(res)) return null;
        const data = res.data as AiClusterResult;
        setClusterResult(data);
        return data;
      } finally {
        setGeneratingLog(false);
      }
    },
    [],
  );

  /** 错误簇归因 */
  const analyzeCluster = useCallback(
    async (payload: {
      fingerprint: string;
      samples: string[];
      count: number;
      vendor_id?: number;
      model_id?: number;
    }) => {
      setGeneratingLog(true);
      try {
        const res: any = await analyzeAiLogCluster(payload);
        if (!auth.response(res)) return null;
        return res.data;
      } finally {
        setGeneratingLog(false);
      }
    },
    [],
  );

  /** SQL 分析 */
  const analyzeSql = useCallback(
    async (payload: {
      sql?: string;
      database_id: number;
      sql_history_id?: number;
      vendor_id?: number;
      model_id?: number;
    }) => {
      setGeneratingSql(true);
      try {
        const res: any = await analyzeAiSql(payload);
        if (!auth.response(res)) return null;
        const data = res.data as AiSqlAnalysis;
        setSqlResult(data);
        return data;
      } finally {
        setGeneratingSql(false);
      }
    },
    [],
  );

  /** 慢查询排行 */
  const fetchSlowSqls = useCallback(
    async (params: { database_id?: number; page?: number; size?: number; min_elapsed?: number }) => {
      setLoading(true);
      try {
        const res: any = await listAiSlowSql(params);
        if (!auth.response(res)) return [];
        setSlowSqls((res.data?.list || []) as AiSlowSql[]);
        return res.data?.list || [];
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  /** 调用流水 */
  const fetchInvokeLogs = useCallback(
    async (params: {
      page?: number;
      size?: number;
      scene?: string;
      model_name?: string;
      start_time?: string;
      end_time?: string;
    }) => {
      setLoading(true);
      try {
        const res: any = await listAiInvokeLogs(params);
        if (!auth.response(res)) return [];
        setInvokeLogs((res.data?.list || []) as AiInvokeLog[]);
        setInvokeLogTotal(res.data?.total || res.data?.list?.length || 0);
        return res.data?.list || [];
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return {
    generating,
    generatingBug,
    generatingLog,
    generatingSql,
    loading,
    batchId,
    drafts,
    draftTotal,
    generateResult,
    bugResult,
    clusterResult,
    sqlResult,
    slowSqls,
    invokeLogs,
    invokeLogTotal,
    models,
    fetchModels,
    generate,
    fetchDrafts,
    saveDraft,
    acceptDrafts,
    rejectDrafts,
    parseDocument,
    analyzeBug,
    clusterLogs,
    analyzeCluster,
    analyzeSql,
    fetchSlowSqls,
    fetchInvokeLogs,
  };
};
