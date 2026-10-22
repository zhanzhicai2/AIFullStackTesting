import { useState, useCallback } from 'react';
import auth from '@/utils/auth';
import {
  listAIVendors,
  updateAIVendor,
  listAIModels,
  addAIModel,
  updateAIModel,
  deleteAIModel,
  fetchRemoteModels,
  listSystemModels,
  importAIModels,
  AIVendor,
  AIVendorItem,
  AIModel,
  AIModelBrief,
} from '@/services/ai';

// 模型来源,与后端 app/enums/AIModelEnum.py 的 AIModelSourceEnum 对应
export const ModelSource = {
  system: 1,
  remote: 2,
  custom: 3,
} as const;

export default () => {
  const [vendors, setVendors] = useState<AIVendorItem[]>([]);
  const [current, setCurrent] = useState<AIVendor | null>(null);
  const [models, setModels] = useState<AIModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [authorized, setAuthorized] = useState<boolean | null>(null);

  const fetchVendors = useCallback(async (): Promise<AIVendorItem[]> => {
    setLoading(true);
    try {
      const res = await listAIVendors();
      // 前端 authority 是死配置,菜单不做过滤,这里靠后端 403 兜底
      if (res.code === 403) {
        setAuthorized(false);
        return [];
      }
      setAuthorized(true);
      if (!auth.response(res)) return [];
      const data = (res.data || []) as AIVendorItem[];
      setVendors(data);
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const selectVendor = useCallback(async (item: AIVendorItem, models?: AIModel[]) => {
    setCurrent(item.vendor);
    if (models) {
      setModels(models);
      return;
    }
    const res = await listAIModels(item.vendor.id);
    if (auth.response(res)) {
      setModels((res.data || []) as AIModel[]);
    }
  }, []);

  const saveVendor = useCallback(async (payload: Record<string, unknown>) => {
    setSaving(true);
    try {
      const res = await updateAIVendor(payload);
      if (auth.response(res, true)) {
        const saved = res.data as AIVendor;
        // 左侧列表的开关也会走这里,那时右侧详情可能显示的是别的厂商,
        // 所以只在确实是当前厂商时才同步详情区
        setCurrent((prev) => (prev && prev.id === saved.id ? saved : prev));
        setVendors((prev) =>
          prev.map((item) => (item.vendor.id === saved.id ? { ...item, vendor: saved } : item))
        );
        return true;
      }
      return false;
    } finally {
      setSaving(false);
    }
  }, []);

  const reloadModels = useCallback(async (vendorId: number) => {
    const res = await listAIModels(vendorId);
    if (auth.response(res)) {
      setModels((res.data || []) as AIModel[]);
    }
  }, []);

  const saveModel = useCallback(
    async (payload: Record<string, unknown>) => {
      const res = payload.id
        ? await updateAIModel(payload)
        : await addAIModel(payload);
      if (!auth.response(res, true)) return false;
      const saved = res.data as AIModel;
      setModels((prev) => {
        const exists = prev.some((m) => m.id === saved.id);
        return exists
          ? prev.map((m) => (m.id === saved.id ? saved : m))
          : [...prev, saved];
      });
      // 同步左侧列表的模型计数
      setVendors((prev) =>
        prev.map((item) =>
          item.vendor.id === saved.vendor_id
            ? { ...item, model_count: item.model_count + (payload.id ? 0 : 1) }
            : item
        )
      );
      return true;
    },
    []
  );

  const toggleModel = useCallback(async (record: AIModel, enable: boolean) => {
    const res = await updateAIModel({
      id: record.id,
      vendor_id: record.vendor_id,
      name: record.name,
      model_type: record.model_type,
      enable,
      params: record.params,
    });
    if (auth.response(res)) {
      setModels((prev) => prev.map((m) => (m.id === record.id ? { ...m, enable } : m)));
    }
  }, []);

  const removeModel = useCallback(
    async (id: number) => {
      // 先记下归属厂商,删除后只减这一个厂商的计数
      const target = models.find((m) => m.id === id);
      const res = await deleteAIModel(id);
      if (auth.response(res, true)) {
        setModels((prev) => prev.filter((m) => m.id !== id));
        if (target) {
          setVendors((prev) =>
            prev.map((item) =>
              item.vendor.id === target.vendor_id
                ? { ...item, model_count: Math.max(0, item.model_count - 1) }
                : item
            )
          );
        }
      }
    },
    [models]
  );

  const fetchRemote = useCallback(
    async (vendorId: number): Promise<{ models: AIModelBrief[]; existed: string[] } | null> => {
      setFetching(true);
      try {
        const res = await fetchRemoteModels(vendorId);
        // 错误信息已在后端转成中文,auth.response 统一弹提示
        if (!auth.response(res)) return null;
        return res.data as { models: AIModelBrief[]; existed: string[] };
      } finally {
        setFetching(false);
      }
    },
    []
  );

  const fetchSystemModels = useCallback(
    async (vendorCode: string): Promise<{ models: AIModelBrief[]; existed: string[] } | null> => {
      const res = await listSystemModels(vendorCode);
      if (!auth.response(res)) return null;
      return res.data as { models: AIModelBrief[]; existed: string[] };
    },
    []
  );

  const importModels = useCallback(
    async (
      vendorId: number,
      source: number,
      names: string[],
      modelTypes?: Record<string, string>
    ) => {
      const res = await importAIModels({ vendor_id: vendorId, source, models: names, model_types: modelTypes });
      if (!auth.response(res, true)) return false;
      await reloadModels(vendorId);
      setVendors((prev) =>
        prev.map((item) =>
          item.vendor.id === vendorId
            ? { ...item, model_count: item.model_count + ((res.data as { added: number }).added || 0) }
            : item
        )
      );
      return true;
    },
    [reloadModels]
  );

  return {
    vendors,
    current,
    models,
    loading,
    saving,
    fetching,
    authorized,
    fetchVendors,
    selectVendor,
    saveVendor,
    saveModel,
    toggleModel,
    removeModel,
    fetchRemote,
    fetchSystemModels,
    importModels,
    reloadModels,
  };
};