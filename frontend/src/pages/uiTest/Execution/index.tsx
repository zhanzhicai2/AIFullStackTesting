import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Modal,
  Space,
  Table,
  Tabs,
  Tag,
  message,
} from 'antd';
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { history } from '@umijs/max';
import { UiExecution } from '@/services/uiTest';
import { listUiExecutions, listUiRunningExecutions } from '@/services/uiTest';

const { TabPane } = Tabs;

const EXECUTE_STATUS: Record<number, { label: string; color: string }> = {
  0: { label: '待执行', color: 'default' },
  1: { label: '执行中', color: 'processing' },
  2: { label: '已停止', color: 'warning' },
  3: { label: '已完成', color: 'success' },
};

/**
 * UI 执行中心
 *
 * 三个视图: 正在执行 / 执行历史 / 回收站。
 * 数据全部来自既有的 `pity_report` / `pity_test_result` —— **不新建表**,
 * 统计口径与接口用例完全一致。
 */
const UiExecutionCenter: React.FC = () => {
  const [historyRows, setHistoryRows] = useState<UiExecution[]>([]);
  const [running, setRunning] = useState<UiExecution[]>([]);
  const [recycle, setRecycle] = useState<UiExecution[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState('running');

  const loadRunning = useCallback(async () => {
    const res = await listUiRunningExecutions();
    if (res?.code === 0) setRunning((res.data || []) as UiExecution[]);
  }, []);

  const loadHistory = useCallback(async (deleted = false) => {
    setLoading(true);
    try {
      const res = await listUiExecutions({ page: 1, size: 50, deleted });
      if (res?.code === 0) {
        const data = (res.data || []) as UiExecution[];
        if (deleted) setRecycle(data);
        else setHistoryRows(data);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRunning();
    loadHistory(false);
    loadHistory(true);
  }, [loadRunning, loadHistory]);

  const columns = useMemo(
    () => [
      { title: '执行时间', dataIndex: 'start_at', key: 'start_at', width: 170 },
      {
        title: '任务名称',
        key: 'plan_name',
        width: 180,
        render: (_: unknown, record: UiExecution) => (
          <a onClick={() => history.push(`/record/report/${record.id}`)}>
            {record.plan_name || 'UI 自动化执行'}
          </a>
        ),
      },
      { title: '环境', dataIndex: 'env', key: 'env', width: 90, render: (v: number) => `环境 ${v}` },
      {
        title: '执行结果',
        dataIndex: 'status',
        key: 'status',
        width: 110,
        render: (value: number) => {
          const conf = EXECUTE_STATUS[value] || EXECUTE_STATUS[0];
          return <Tag color={conf.color}>{conf.label}</Tag>;
        },
      },
      {
        title: '用例数',
        key: 'total',
        width: 90,
        render: (_: unknown, record: UiExecution) => (
          <span>
            {record.ui_total}
            <span style={{ color: '#999', marginLeft: 4 }}>/ {record.success_count + record.failed_count + record.error_count}</span>
          </span>
        ),
      },
      {
        title: '通过率',
        key: 'percent',
        width: 90,
        render: (_: unknown, record: UiExecution) => (
          <Badge
            status={record.ui_percent >= 90 ? 'success' : 'error'}
            text={`${record.ui_percent}%`}
          />
        ),
      },
      {
        title: '执行人',
        dataIndex: 'executor',
        key: 'executor',
        width: 100,
        render: (value: number) => (value === 0 ? 'pity机器人' : `用户 ${value}`),
      },
      {
        title: '操作',
        key: 'action',
        width: 160,
        render: (_: unknown, record: UiExecution) => (
          <Space>
            <a onClick={() => history.push(`/record/report/${record.id}`)}>报告</a>
            <a
              onClick={() =>
                Modal.confirm({
                  title: '确定删除这条执行记录吗?',
                  content: '删除后进回收站, 重新执行会产生新的记录, 原记录不会被覆盖',
                  onOk: async () => {
                    // 延迟引入, 避免首屏加载执行中心就把整个执行模块拉进来
                    const { deleteUiExecution } = await import('@/services/uiTest');
                    const res = await deleteUiExecution(record.id);
                    if (res?.code === 0) {
                      message.success('已删除');
                      loadHistory(false);
                      loadHistory(true);
                    }
                  },
                })
              }
            >
              删除
            </a>
          </Space>
        ),
      },
    ],
    [loadHistory]
  );

  return (
    <div className="ui-page">
      <Card
        bordered={false}
        title="执行中心"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => {
              loadRunning();
              loadHistory(false);
              loadHistory(true);
            }}>
              刷新
            </Button>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => history.push('/uiTest/case')}>
              去执行用例
            </Button>
          </Space>
        }
      >
        <Tabs activeKey={active} onChange={setActive}>
          <TabPane tab={`正在执行 (${running.length})`} key="running">
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              columns={columns as any}
              dataSource={running}
              pagination={false}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有正在执行的任务" /> }}
            />
          </TabPane>
          <TabPane tab="执行历史" key="history">
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              columns={columns as any}
              dataSource={historyRows}
              pagination={false}
              scroll={{ y: 480 }}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有执行记录" /> }}
            />
          </TabPane>
          <TabPane tab={`回收站 (${recycle.length})`} key="recycle">
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="回收站里的执行记录已被软删除, 重新执行会产生新的记录"
            />
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              columns={columns as any}
              dataSource={recycle}
              pagination={false}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="回收站是空的" /> }}
            />
          </TabPane>
        </Tabs>
      </Card>
    </div>
  );
};

export default UiExecutionCenter;
