import { useCallback, useState } from 'react';
import auth from '@/utils/auth';
import {
  UiAllowedDomain,
  UiCase,
  UiCaseDetail,
  UiElement,
  UiNode,
  UiPage,
  UiRunResult,
  UiStep,
  deleteUiCase,
  deleteUiDomain,
  deleteUiElement,
  deleteUiNode,
  deleteUiPage,
  importUiRecord,
  insertUiCase,
  insertUiDomain,
  insertUiElement,
  insertUiPage,
  listUiCases,
  listUiDomains,
  listUiElements,
  listUiNodes,
  listUiPages,
  queryUiCase,
  runUiCase,
  updateUiCase,
  updateUiElement,
  updateUiElementStatus,
  updateUiPage,
} from '@/services/uiTest';

/**
 * UI 自动化子系统的前端状态(hooks 风格)
 *
 * 页面树、元素库、用例、白名单、节点各自一份状态,
 * 元素引用的可用性(elRefValid)由后端在保存时裁决, 前端只做**提前提示**,
 * 不在前端做最终判定 —— 前端放行、后端丢弃会造成「改了还是被丢弃」的困惑。
 */
export default () => {
  const [pages, setPages] = useState<UiPage[]>([]);
  const [elements, setElements] = useState<UiElement[]>([]);
  const [cases, setCases] = useState<UiCase[]>([]);
  const [currentCase, setCurrentCase] = useState<UiCaseDetail | null>(null);
  const [domains, setDomains] = useState<UiAllowedDomain[]>([]);
  const [nodes, setNodes] = useState<UiNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<UiRunResult | null>(null);

  const fetchPages = useCallback(async (projectId: number): Promise<UiPage[]> => {
    setLoading(true);
    try {
      const res = await listUiPages(projectId);
      if (!auth.response(res)) return [];
      const data = (res.data || []) as UiPage[];
      setPages(data);
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const savePage = useCallback(
    async (payload: Record<string, unknown>): Promise<boolean> => {
      setSaving(true);
      try {
        const res = payload.id ? await updateUiPage(payload) : await insertUiPage(payload);
        return auth.response(res, true);
      } finally {
        setSaving(false);
      }
    },
    []
  );

  const removePage = useCallback(async (id: number, projectId: number): Promise<boolean> => {
    const res = await deleteUiPage(id, projectId);
    return auth.response(res, true);
  }, []);

  const fetchElements = useCallback(
    async (params: { project_id?: number; page_id?: number; status?: number }): Promise<UiElement[]> => {
      setLoading(true);
      try {
        const res = await listUiElements(params);
        if (!auth.response(res)) return [];
        const data = (res.data || []) as UiElement[];
        setElements(data);
        return data;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const saveElement = useCallback(
    async (payload: Record<string, unknown>): Promise<{ id: number; duplicated: boolean } | null> => {
      setSaving(true);
      try {
        const res = payload.id ? await updateUiElement(payload) : await insertUiElement(payload);
        if (!auth.response(res, true)) return null;
        return (res.data as { id: number; duplicated: boolean }) || null;
      } finally {
        setSaving(false);
      }
    },
    []
  );

  const removeElement = useCallback(async (id: number, projectId: number): Promise<boolean> => {
    const res = await deleteUiElement(id, projectId);
    return auth.response(res, true);
  }, []);

  const toggleElementStatus = useCallback(
    async (id: number, projectId: number, status: number): Promise<boolean> => {
      const res = await updateUiElementStatus({ id, project_id: projectId, status });
      return auth.response(res, true);
    },
    []
  );

  const fetchCases = useCallback(
    async (params: { project_id?: number; directory_id?: number; name?: string }): Promise<UiCase[]> => {
      setLoading(true);
      try {
        const res = await listUiCases(params);
        if (!auth.response(res)) return [];
        const data = (res.data || []) as UiCase[];
        setCases(data);
        return data;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const loadCase = useCallback(async (id: number): Promise<UiCaseDetail | null> => {
    setLoading(true);
    try {
      const res = await queryUiCase(id);
      if (!auth.response(res)) return null;
      const data = (res.data as UiCaseDetail) || null;
      setCurrentCase(data);
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const saveCase = useCallback(
    async (payload: Record<string, unknown>): Promise<{ case_id: number; warnings: string[] } | null> => {
      setSaving(true);
      try {
        const res = payload.id ? await updateUiCase(payload) : await insertUiCase(payload);
        if (!auth.response(res, true)) return null;
        return (res.data as { case_id: number; warnings: string[] }) || null;
      } finally {
        setSaving(false);
      }
    },
    []
  );

  const removeCase = useCallback(async (id: number): Promise<boolean> => {
    const res = await deleteUiCase(id);
    return auth.response(res, true);
  }, []);

  const executeCase = useCallback(
    async (payload: { case_id: number; env?: number; node_id?: number }): Promise<UiRunResult | null> => {
      setRunning(true);
      try {
        const res = await runUiCase(payload);
        if (!auth.response(res)) return null;
        const data = (res.data as UiRunResult) || null;
        setRunResult(data);
        return data;
      } finally {
        setRunning(false);
      }
    },
    []
  );

  const fetchDomains = useCallback(async (projectId: number, env?: number): Promise<UiAllowedDomain[]> => {
    const res = await listUiDomains(projectId, env);
    if (!auth.response(res)) return [];
    const data = (res.data || []) as UiAllowedDomain[];
    setDomains(data);
    return data;
  }, []);

  const saveDomain = useCallback(async (payload: Record<string, unknown>): Promise<boolean> => {
    setSaving(true);
    try {
      const res = await insertUiDomain(payload);
      return auth.response(res, true);
    } finally {
      setSaving(false);
    }
  }, []);

  const removeDomain = useCallback(async (id: number): Promise<boolean> => {
    const res = await deleteUiDomain(id);
    return auth.response(res, true);
  }, []);

  const fetchNodes = useCallback(async (): Promise<UiNode[]> => {
    const res = await listUiNodes();
    if (!auth.response(res)) return [];
    const data = (res.data || []) as UiNode[];
    setNodes(data);
    return data;
  }, []);

  const removeNode = useCallback(async (id: number): Promise<boolean> => {
    const res = await deleteUiNode(id);
    return auth.response(res, true);
  }, []);

  // 录制导入 —— 后端只做静态解析, 平台不执行录制脚本里的任何内容
  const importRecord = useCallback(
    async (payload: {
      project_id: number;
      source: string;
      script: string;
      directory_id?: number;
      name?: string;
    }) => {
      setSaving(true);
      try {
        const res = await importUiRecord(payload);
        if (!auth.response(res, true)) return null;
        return res.data || null;
      } finally {
        setSaving(false);
      }
    },
    []
  );

  return {
    pages,
    elements,
    cases,
    currentCase,
    domains,
    nodes,
    loading,
    saving,
    running,
    runResult,
    setRunResult,
    setCurrentCase,
    fetchPages,
    savePage,
    removePage,
    fetchElements,
    saveElement,
    removeElement,
    toggleElementStatus,
    fetchCases,
    loadCase,
    saveCase,
    removeCase,
    executeCase,
    fetchDomains,
    saveDomain,
    removeDomain,
    fetchNodes,
    removeNode,
    importRecord,
  };
};

export type { UiAllowedDomain, UiCase, UiCaseDetail, UiElement, UiNode, UiPage, UiRunResult, UiStep };
