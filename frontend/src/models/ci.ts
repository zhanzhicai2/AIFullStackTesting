import { useCallback, useState } from 'react';
import {
  CiIntegration,
  CiRun,
  CiRunListParams,
  listCiIntegrations,
  listCiRuns,
} from '@/services/ci';
import { listTestPlan } from '@/services/testplan';

/**
 * 持续集成(CI)页的前端状态(hooks 风格)
 *
 * 新文件一律用 hooks 风格(`@umijs/plugin-model`), 不混 dva model —— 见 frontend/CLAUDE.md。
 * 状态全部按项目隔离: 切换项目即重拉(与 Mock 页同款)。
 *
 * `justIssuedToken` 是**一次性明文**: 签发成功后置入, 弹窗关闭即清空 ——
 * 任何刷新 / 切项目都拿不回来(spec FR-002 / SC-007)。
 */
export default () => {
  const [projectId, setProjectId] = useState<number | undefined>();

  // 集成配置
  const [integrations, setIntegrations] = useState<CiIntegration[]>([]);
  const [integrationTotal, setIntegrationTotal] = useState(0);
  const [integrationLoading, setIntegrationLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);

  // 一次性明文凭据
  const [justIssuedToken, setJustIssuedToken] = useState<string | null>(null);
  const [justIssuedId, setJustIssuedId] = useState<number | null>(null);

  // 项目下的测试计划(G3 前置 + 接入示例要填 plan_id)
  const [plans, setPlans] = useState<{ id: number; name: string }[]>([]);

  // 触发历史
  const [runs, setRuns] = useState<CiRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsPage, setRunsPage] = useState(1);
  const [runsSize, setRunsSize] = useState(20);
  const [runsFilter, setRunsFilter] = useState<Partial<CiRunListParams>>({});

  const fetchIntegrations = useCallback(
    async (pid?: number, p?: number, s?: number) => {
      const target = pid ?? projectId;
      if (!target) {
        setIntegrations([]);
        setIntegrationTotal(0);
        return;
      }
      setIntegrationLoading(true);
      try {
        const curPage = p ?? page;
        const curSize = s ?? size;
        const res: any = await listCiIntegrations({
          project_id: target,
          page: curPage,
          size: curSize,
        });
        if (res?.code === 0) {
          setIntegrations(res.data || []);
          setIntegrationTotal(res.total || 0);
          setPage(curPage);
          setSize(curSize);
        }
      } finally {
        setIntegrationLoading(false);
      }
    },
    [projectId, page, size],
  );

  const fetchPlans = useCallback(async (pid?: number) => {
    const target = pid ?? projectId;
    if (!target) {
      setPlans([]);
      return;
    }
    try {
      const res: any = await listTestPlan({ page: 1, size: 200, project_id: target });
      if (res?.code === 0) {
        setPlans((res.data || []).map((p: any) => ({ id: p.id, name: p.name })));
      }
    } catch {
      setPlans([]);
    }
  }, [projectId]);

  const fetchRuns = useCallback(
    async (pid?: number, p?: number, s?: number, filter?: Partial<CiRunListParams>) => {
      const target = pid ?? projectId;
      if (!target) {
        setRuns([]);
        setRunsTotal(0);
        return;
      }
      setRunsLoading(true);
      try {
        const curPage = p ?? runsPage;
        const curSize = s ?? runsSize;
        const res: any = await listCiRuns({
          project_id: target,
          page: curPage,
          size: curSize,
          ...(filter ?? runsFilter),
        } as CiRunListParams);
        if (res?.code === 0) {
          setRuns(res.data || []);
          setRunsTotal(res.total || 0);
          setRunsPage(curPage);
          setRunsSize(curSize);
          if (filter) setRunsFilter(filter);
        }
      } finally {
        setRunsLoading(false);
      }
    },
    [projectId, runsPage, runsSize, runsFilter],
  );

  /** 切换项目 → 三块状态一起重拉(清一次性明文, 防止跨项目串凭据) */
  const changeProject = useCallback(
    (id: number | undefined) => {
      setProjectId(id);
      setPage(1);
      setRunsPage(1);
      setRunsFilter({});
      setJustIssuedToken(null);
      setJustIssuedId(null);
      fetchIntegrations(id, 1, size);
      fetchPlans(id);
      fetchRuns(id, 1, runsSize, {});
    },
    [size, runsSize, fetchIntegrations, fetchPlans, fetchRuns],
  );

  /** 记录一次性明文(签发成功后调用) */
  const rememberIssuedToken = useCallback((token: string, id: number) => {
    setJustIssuedToken(token);
    setJustIssuedId(id);
  }, []);

  /** 弹窗关闭即丢弃明文 —— 之后任何路径都拿不回来 */
  const discardIssuedToken = useCallback(() => {
    setJustIssuedToken(null);
    setJustIssuedId(null);
  }, []);

  return {
    projectId,
    changeProject,

    integrations,
    integrationTotal,
    integrationLoading,
    page,
    size,
    fetchIntegrations,

    justIssuedToken,
    justIssuedId,
    rememberIssuedToken,
    discardIssuedToken,

    plans,
    fetchPlans,

    runs,
    runsTotal,
    runsLoading,
    runsPage,
    runsSize,
    runsFilter,
    fetchRuns,
    setRunsPage,
    setRunsFilter,
  };
};
