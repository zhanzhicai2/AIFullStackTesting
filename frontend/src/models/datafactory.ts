import { useCallback, useState } from 'react';
import auth from '@/utils/auth';
import {
  AiParseResult,
  DataFactoryColumn,
  DataFactoryDataset,
  GeneratePayload,
  TableColumn,
  aiParseDataFactoryRules,
  bindDataFactoryToCase,
  deleteDataFactoryDataset,
  downloadDataFactoryFile,
  generateData,
  insertDataFactoryDataset,
  listDataFactoryDatasets,
  listDataFactoryTableColumns,
  listDataFactoryTables,
  updateDataFactoryDataset,
  writeDataFactoryToDb,
} from '@/services/datafactory';

export default () => {
  const [datasets, setDatasets] = useState<DataFactoryDataset[]>([]);
  const [current, setCurrent] = useState<DataFactoryDataset | null>(null);
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [tables, setTables] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [writing, setWriting] = useState(false);
  const [binding, setBinding] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [total, setTotal] = useState(0);

  const fetchDatasets = useCallback(
    async (params: { page?: number; size?: number; env?: number; name?: string }) => {
      setLoading(true);
      try {
        const res = await listDataFactoryDatasets({ page: 1, size: 100, ...params });
        if (!auth.response(res)) return [];
        const data = (res.data || []) as DataFactoryDataset[];
        setDatasets(data);
        setTotal(res.total || data.length);
        return data;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const saveDataset = useCallback(
    async (payload: Record<string, unknown>): Promise<DataFactoryDataset | null> => {
      setSaving(true);
      try {
        const res = payload.id
          ? await updateDataFactoryDataset(payload)
          : await insertDataFactoryDataset(payload);
        if (!auth.response(res, true)) return null;
        await fetchDatasets({});
        // 返回落库后的记录(带 id), 调用方据此把"新建态"切到"编辑态",
        // 否则新建完 current 仍是 null, 点生成预览会被拦成"请先选择数据集"
        return (res.data as DataFactoryDataset) || null;
      } finally {
        setSaving(false);
      }
    },
    [fetchDatasets]
  );

  const removeDataset = useCallback(
    async (id: number) => {
      const res = await deleteDataFactoryDataset(id);
      if (!auth.response(res, true)) return false;
      setCurrent((prev) => (prev && prev.id === id ? null : prev));
      await fetchDatasets({});
      return true;
    },
    [fetchDatasets]
  );

  const generate = useCallback(async (payload: GeneratePayload): Promise<Record<string, any>[] | null> => {
    setGenerating(true);
    try {
      const res = await generateData(payload);
      if (!auth.response(res)) return null;
      const data = (res.data || []) as Record<string, any>[];
      setRows(data);
      return data;
    } finally {
      setGenerating(false);
    }
  }, []);

  const exportFile = useCallback(
    async (payload: GeneratePayload & { file_type: string; table_name?: string }, filename: string) => {
      setExporting(true);
      try {
        await downloadDataFactoryFile(payload, filename);
        return true;
      } catch (e) {
        const err = e as Error;
        auth.response({ code: 110, msg: err.message } as any);
        return false;
      } finally {
        setExporting(false);
      }
    },
    []
  );

  const writeDb = useCallback(
    async (payload: GeneratePayload & { database_id: number; table_name: string }) => {
      setWriting(true);
      try {
        const res = await writeDataFactoryToDb(payload);
        return auth.response(res, true);
      } finally {
        setWriting(false);
      }
    },
    []
  );

  const bindCase = useCallback(
    async (
      payload: GeneratePayload & { case_id: number; env: number; name_prefix?: string; replace?: boolean }
    ) => {
      setBinding(true);
      try {
        const res = await bindDataFactoryToCase(payload);
        return auth.response(res, true);
      } finally {
        setBinding(false);
      }
    },
    []
  );

  const loadTables = useCallback(async (databaseId: number): Promise<string[]> => {
    const res = await listDataFactoryTables(databaseId);
    if (!auth.response(res)) return [];
    const data = (res.data || []) as string[];
    setTables(data);
    return data;
  }, []);

  const loadTableColumns = useCallback(
    async (databaseId: number, table: string): Promise<TableColumn[]> => {
      const res = await listDataFactoryTableColumns(databaseId, table);
      if (!auth.response(res)) return [];
      // 只返回, 不缓存进 model: 调用方(导入弹窗)自己按所选表存,
      // 全局缓存会把上一张表的列带到下一次打开的弹窗里
      return (res.data || []) as TableColumn[];
    },
    []
  );

  const aiParse = useCallback(
    async (payload: { prompt: string; vendor_id: number; model_id: number }): Promise<AiParseResult | null> => {
      setParsing(true);
      try {
        const res = await aiParseDataFactoryRules(payload);
        if (!auth.response(res)) return null;
        return res.data as AiParseResult;
      } finally {
        setParsing(false);
      }
    },
    []
  );

  return {
    datasets,
    current,
    setCurrent,
    rows,
    setRows,
    tables,
    loading,
    saving,
    generating,
    exporting,
    writing,
    binding,
    parsing,
    total,
    fetchDatasets,
    saveDataset,
    removeDataset,
    generate,
    exportFile,
    writeDb,
    bindCase,
    loadTables,
    loadTableColumns,
    aiParse,
  };
};

export type { DataFactoryColumn, DataFactoryDataset };
