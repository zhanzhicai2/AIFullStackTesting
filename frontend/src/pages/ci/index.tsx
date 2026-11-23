import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Card, Empty, Select, Space, Tabs, Typography } from 'antd';
import { useModel } from '@umijs/max';
import { listProject } from '@/services/project';
import IntegrationPanel from './IntegrationPanel';
import SnippetsPanel from './SnippetsPanel';
import RunHistoryPanel from './RunHistoryPanel';
import './index.less';

const { Text } = Typography;

interface ProjectOption {
  id: number;
  name: string;
}

/**
 * 持续集成(CI)页 —— 原先指向 `./Building` 占位页(spec FR-025)
 *
 * 三个 tab: 集成配置 / 接入示例 / 触发历史。
 * 就地指引(constitution 原则 IV / spec FR-029):
 *   G1 未选项目 → 提示选择 + 项目入口, **不渲染任何空表格**
 *   G2 无集成配置 → 集成面板内给「新建集成」入口
 *   G3 无测试计划 → 集成面板与示例面板内给「去创建测试计划」入口(硬前置)
 *   G4 无触发历史 → 历史面板内展示接入示例与三步说明, 而不是空白
 */
const CiPage: React.FC = () => {
  const { projectId, changeProject, fetchIntegrations, fetchPlans, fetchRuns } = useModel('ci');
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [activeTab, setActiveTab] = useState('integration');

  useEffect(() => {
    let alive = true;
    listProject({ page: 1, size: 200 })
      .then((res: any) => {
        if (alive && res?.code === 0) {
          setProjects((res.data || []).map((p: any) => ({ id: p.id, name: p.name })));
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  /** 首次进入默认选中第一个项目 —— 少一次点击, 也避免一屏空态 */
  useEffect(() => {
    if (!projectId && projects.length > 0) {
      changeProject(projects[0].id);
    }
  }, [projects, projectId, changeProject]);

  const refreshAll = useCallback(() => {
    fetchIntegrations();
    fetchPlans();
    fetchRuns();
  }, [fetchIntegrations, fetchPlans, fetchRuns]);

  const tabs = [
    {
      key: 'integration',
      label: '集成配置',
      children: (
        <IntegrationPanel onIssued={() => setActiveTab('snippets')} />
      ),
    },
    {
      key: 'snippets',
      label: '接入示例',
      children: <SnippetsPanel />,
    },
    {
      key: 'history',
      label: '触发历史',
      children: <RunHistoryPanel onRefresh={refreshAll} />,
    },
  ];

  return (
    <div className="pity-ci-page">
      <Card
        title="持续集成"
        extra={
          <Space>
            <Text type="secondary">项目</Text>
            <Select
              style={{ minWidth: 220 }}
              placeholder="请选择项目"
              value={projectId}
              onChange={(v) => changeProject(v)}
              options={projects.map((p) => ({ label: p.name, value: p.id }))}
              showSearch
              optionFilterProp="label"
            />
          </Space>
        }
      >
        {!projectId ? (
          <Empty
            description={
              <span>
                请先选择项目 —— 接入凭据与触发记录都按项目隔离。
                {projects.length === 0 ? '（当前账号下还没有可选项目）' : ''}
              </span>
            }
          >
            {projects.length === 0 ? null : (
              <Text type="secondary">用上方下拉框选择一个项目即可开始接入。</Text>
            )}
          </Empty>
        ) : (
          <>
            <Alert
              showIcon
              type="info"
              style={{ marginBottom: 16 }}
              message="外部流水线接入说明"
              description="在「集成配置」签发一条凭据 → 到「接入示例」复制流水线片段 → 之后每次触发的结果都会出现在「触发历史」。凭据明文只在签发那一刻展示一次，请当场复制。"
            />
            <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabs} />
          </>
        )}
      </Card>
    </div>
  );
};

export default CiPage;
