import { useCallback, useState } from 'react';
import {
  MockRule,
  MockRuleForm,
  deleteMockRule,
  insertMockRule,
  listMockRules,
  previewMockRule,
  MockRulePreviewParams,
  MockRulePreviewResult,
  updateMockRule,
  updateMockRuleStatus,
} from '@/services/mock';

/**
 * Mock 配置的前端状态(hooks 风格)
 *
 * 新文件一律用 hooks 风格(`@umijs/plugin-model`), 不混 dva model —— 见 frontend/CLAUDE.md。
 * 状态全部按项目隔离: 切换项目即重拉列表。
 */
export default () => {
  const [projectId, setProjectId] = useState<number | undefined>();
  const [rules, setRules] = useState<MockRule[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [filters, setFilters] = useState<{ method?: string; path?: string; status?: number }>({});

  const fetchRules = useCallback(
    async (p?: number, s?: number) => {
      if (!projectId) return;
      setLoading(true);
      try {
        const curPage = p ?? page;
        const curSize = s ?? size;
        const res: any = await listMockRules({
          project_id: projectId,
          page: curPage,
          size: curSize,
          ...filters,
        });
        if (res?.code === 0) {
          setRules(res.data || []);
          setTotal(res.total || 0);
          setPage(curPage);
          setSize(curSize);
        }
      } finally {
        setLoading(false);
      }
    },
    [projectId, page, size, filters],
  );

  /** 切换项目 → 重置筛选并拉列表 */
  const changeProject = useCallback(
    (id: number | undefined) => {
      setProjectId(id);
      setFilters({});
      setPage(1);
      if (id) {
        listMockRules({ project_id: id, page: 1, size })
          .then((res: any) => {
            if (res?.code === 0) {
              setRules(res.data || []);
              setTotal(res.total || 0);
            }
          })
          .catch(() => undefined);
      } else {
        setRules([]);
        setTotal(0);
      }
    },
    [size],
  );

  const applyFilters = useCallback(
    (f: { method?: string; path?: string; status?: number }) => {
      setFilters(f);
      setPage(1);
      if (projectId) {
        listMockRules({ project_id: projectId, page: 1, size, ...f })
          .then((res: any) => {
            if (res?.code === 0) {
              setRules(res.data || []);
              setTotal(res.total || 0);
            }
          })
          .catch(() => undefined);
      }
    },
    [projectId, size],
  );

  /** 新建规则(返回 warning 文案给表单展示) */
  const addRule = useCallback(
    async (form: MockRuleForm): Promise<string | undefined> => {
      const res: any = await insertMockRule(form);
      if (res?.code !== 0) {
        throw new Error(res?.msg || '新建失败');
      }
      await fetchRules();
      return res.msg && res.msg !== '操作成功' ? res.msg : undefined;
    },
    [fetchRules],
  );

  /** 更新规则 */
  const editRule = useCallback(
    async (form: MockRuleForm) => {
      const res: any = await updateMockRule(form);
      if (res?.code !== 0) {
        throw new Error(res?.msg || '更新失败');
      }
      await fetchRules();
    },
    [fetchRules],
  );

  /** 删除规则(逻辑删除) */
  const removeRule = useCallback(
    async (id: number) => {
      if (!projectId) return;
      const res: any = await deleteMockRule(id, projectId);
      if (res?.code !== 0) {
        throw new Error(res?.msg || '删除失败');
      }
      await fetchRules();
    },
    [projectId, fetchRules],
  );

  /** 启停规则 */
  const toggleRule = useCallback(
    async (id: number, status: number) => {
      if (!projectId) return;
      const res: any = await updateMockRuleStatus(id, projectId, status);
      if (res?.code !== 0) {
        throw new Error(res?.msg || '操作失败');
      }
      await fetchRules();
    },
    [projectId, fetchRules],
  );

  /** 就地调试: 模拟一次匹配(不经过对外服务) */
  const preview = useCallback(
    async (params: MockRulePreviewParams): Promise<MockRulePreviewResult | undefined> => {
      const res: any = await previewMockRule(params);
      if (res?.code !== 0) {
        throw new Error(res?.msg || '调试失败');
      }
      return res.data as MockRulePreviewResult;
    },
    [],
  );

  return {
    projectId,
    rules,
    total,
    loading,
    page,
    size,
    filters,
    fetchRules,
    changeProject,
    applyFilters,
    addRule,
    editRule,
    removeRule,
    toggleRule,
    preview,
  };
};
