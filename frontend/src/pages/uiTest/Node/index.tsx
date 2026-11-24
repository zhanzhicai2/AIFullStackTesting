import React, { useCallback, useEffect } from 'react';
import { Alert, Badge, Button, Card, Empty, Space, Table, Tag, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { UiNode } from '@/services/uiTest';

/**
 * UI 执行节点
 *
 * v1 只有内置的本地节点 —— 平台启动时自动注册, 用户无需额外配置。
 * 分布式节点是 v2, 但表与接口形状先定好, 免得 v2 时改调用方。
 */
const UiNodeList: React.FC = () => {
  const { nodes, loading, fetchNodes, removeNode } = useModel('uiTest');

  const load = useCallback(async () => {
    await fetchNodes();
  }, [fetchNodes]);

  useEffect(() => {
    load();
  }, [load]);

  // U6: 没有可用的执行节点 —— 就地提示并给入口, 而不是只报一个错误码
  const onlineNodes = nodes.filter((n) => n.status === 1);
  const noNode = onlineNodes.length === 0;

  const columns = [
    { title: '节点名', dataIndex: 'name', key: 'name' },
    {
      title: '类型',
      dataIndex: 'node_type',
      key: 'node_type',
      width: 100,
      render: (value: string) => <Tag>{value === 'local' ? '本地' : value}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (value: number) => (
        <Badge status={value === 1 ? 'success' : 'default'} text={value === 1 ? '在线' : '离线'} />
      ),
    },
    { title: '浏览器', dataIndex: 'browser', key: 'browser', width: 110 },
    {
      title: '无头模式',
      dataIndex: 'headless',
      key: 'headless',
      width: 100,
      render: (value: boolean) => (value ? '是' : '否'),
    },
    { title: '并发上限', dataIndex: 'max_concurrency', key: 'max_concurrency', width: 100 },
    { title: '版本', dataIndex: 'version', key: 'version', width: 100, render: (v?: string) => v || '-' },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, record: UiNode) => (
        <a
          onClick={() =>
            // 删除节点要 ADMIN 权限, 失败会如实提示
            removeNode(record.id).then((ok) => {
              if (ok) {
                message.success('节点已删除');
                load();
              }
            })
          }
        >
          删除
        </a>
      ),
    },
  ];

  return (
    <div className="ui-page">
      <Card
        variant="borderless"
        title="执行节点"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
          </Space>
        }
      >
        {noNode ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="没有可用的执行节点"
            description="UI 用例需要浏览器才能执行。内置的本地节点会在平台启动时自动注册, 如果这里为空, 说明平台刚启动还没完成注册 —— 刷新一下试试。"
          />
        ) : null}
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns as any}
          dataSource={nodes}
          pagination={false}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有执行节点" />,
          }}
        />
      </Card>
    </div>
  );
};

export default UiNodeList;
