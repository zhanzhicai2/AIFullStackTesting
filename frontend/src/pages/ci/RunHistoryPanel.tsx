import React, { useCallback, useEffect } from 'react';
import { Alert, Button, Empty, Space, Table, Tag, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { CiRun, isCiRunInFlight } from '@/services/ci';
import { CI_RUN_STATUS_COLORS, CI_RUN_STATUS_LABELS } from '@/consts/ci';

const { Text, Link } = Typography;

/**
 * 触发历史面板(spec US3)
 *
 * **`3`(测试未通过) 与 `5`(平台执行失败) 必须看起来就不一样** —— 文案与 Tag 颜色
 * 都取自 `@/consts/ci`(后端 `CiEnum` 的镜像), 页面里不硬编码数字(spec FR-015 / SC-006)。
 *
 * G4: 没有记录时展示「如何触发第一次」三步说明, 而不是一片空白。
 */
const RunHistoryPanel: React.FC<{ onRefresh?: () => void }> = ({ onRefresh }) => {
  const {
    projectId,
    runs,
    runsTotal,
    runsLoading,
    runsPage,
    runsSize,
    fetchRuns,
    setRunsPage,
  } = useModel('ci');

  useEffect(() => {
    if (projectId) fetchRuns(projectId, 1, runsSize, {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const reload = useCallback(() => {
    if (projectId) fetchRuns(projectId, runsPage, runsSize, {});
    onRefresh?.();
  }, [projectId, runsPage, runsSize, fetchRuns, onRefresh]);

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string | null, r: CiRun) => v || r.started_at || '-',
    },
    {
      title: '测试计划',
      dataIndex: 'plan_name',
      key: 'plan_name',
      render: (v: string | null, r: CiRun) => v || `#${r.plan_id}`,
    },
    {
      title: '外部构建号',
      key: 'external',
      render: (_: unknown, r: CiRun) => {
        if (!r.external_build_id && !r.external_url) {
          return <Text type="secondary">-</Text>;
        }
        const label = r.external_build_id || r.external_url;
        return r.external_url ? (
          <Link href={r.external_url} target="_blank" rel="noreferrer">
            {label}
          </Link>
        ) : (
          <Text>{label}</Text>
        );
      },
    },
    {
      title: '结果',
      dataIndex: 'status',
      key: 'status',
      render: (status: number) => (
        <Tag color={CI_RUN_STATUS_COLORS[status] || 'default'}>
          {CI_RUN_STATUS_LABELS[status] || `未知(${status})`}
        </Tag>
      ),
    },
    {
      title: '通过率',
      dataIndex: 'pass_rate',
      key: 'pass_rate',
      width: 90,
      render: (v: number, r: CiRun) => {
        const total =
          r.success_count + r.failed_count + r.error_count + r.skipped_count;
        if (total === 0) return <Text type="secondary">无用例</Text>;
        return (
          <Text>
            {v}%（{r.success_count}/{total}）
          </Text>
        );
      },
    },
    {
      title: '耗时',
      dataIndex: 'cost',
      key: 'cost',
      width: 90,
      render: (v: string | null) => (v ? `${v}s` : '-'),
    },
    {
      title: '报告',
      key: 'report',
      width: 90,
      render: (_: unknown, r: CiRun) =>
        r.report_url ? (
          <Link href={r.report_url} target="_blank" rel="noreferrer">
            查看
          </Link>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '说明',
      dataIndex: 'error_msg',
      key: 'error_msg',
      ellipsis: true,
      render: (v: string | null) => (v ? <Text type="warning">{v}</Text> : '-'),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={reload} loading={runsLoading}>
          刷新
        </Button>
        <Text type="secondary">
          每次外部触发都会留一条记录，可按构建号回溯到对应流水线。
        </Text>
      </Space>

      {runs.length === 0 && !runsLoading ? (
        <Empty description={false}>
          <Alert
            showIcon
            type="info"
            style={{ maxWidth: 720, textAlign: 'left' }}
            message="还没有任何触发记录 —— 如何触发第一次？"
            description={
              <ol style={{ marginBottom: 0, paddingLeft: 20 }}>
                <li>
                  到「集成配置」签发一条凭据，并当场复制（明文只显示一次）。
                </li>
                <li>
                  到「接入示例」复制 Jenkinsfile 或 GitHub Actions 片段，粘进你的流水线仓库。
                </li>
                <li>跑一次流水线 —— 结果会出现在这张表里，可点报告查看用例明细。</li>
              </ol>
            }
          />
        </Empty>
      ) : (
        <Table<CiRun>
          rowKey="run_id"
          size="middle"
          loading={runsLoading}
          columns={columns}
          dataSource={runs}
          rowClassName={(r) => (isCiRunInFlight(r.status) ? 'ci-run-inflight' : '')}
          pagination={{
            current: runsPage,
            pageSize: runsSize,
            total: runsTotal,
            showSizeChanger: true,
            onChange: (p, s) => {
              setRunsPage(p);
              fetchRuns(projectId, p, s, {});
            },
          }}
        />
      )}
    </div>
  );
};

export default RunHistoryPanel;
