import React, { useEffect, useState } from 'react';
import { Card, Select, Table, Tag, Typography } from 'antd';
import { useModel } from '@umijs/max';
import { AI_SCENE_LABELS } from '@/consts/aiWorkbench';

const { Text } = Typography;

const STATUS_TAGS: Record<string, string> = { success: 'success', failed: 'error' };

/**
 * 模型调用流水
 *
 * 谁在什么时候用什么模型调了 AI、花了多少 token、成没成。
 * 支撑成本核算与"哪个模型干哪个活更准"的评测(FR-015)。
 */
const InvokeLogPage: React.FC = () => {
  const { invokeLogs, invokeLogTotal, fetchInvokeLogs, loading } = useModel('aiWorkbench');
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [scene, setScene] = useState<string | undefined>();

  useEffect(() => {
    fetchInvokeLogs({ page, size, scene });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, size, scene]);

  return (
    <div className="ai-workbench-page">
      <Card
        variant="borderless"
        title="模型调用流水"
        extra={
          <Select
            style={{ width: 140 }}
            allowClear
            placeholder="按场景过滤"
            value={scene}
            onChange={(value) => {
              setScene(value);
              setPage(1);
            }}
            options={Object.keys(AI_SCENE_LABELS).map((key) => ({
              label: AI_SCENE_LABELS[key],
              value: key,
            }))}
          />
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={invokeLogs}
          pagination={{
            current: page,
            pageSize: size,
            total: invokeLogTotal,
            showSizeChanger: true,
            onChange: (nextPage, nextSize) => {
              setPage(nextPage);
              setSize(nextSize);
            },
          }}
          columns={[
            {
              title: '场景',
              dataIndex: 'scene',
              width: 100,
              render: (value: string) => <Tag>{AI_SCENE_LABELS[value] || value}</Tag>,
            },
            { title: '模型', dataIndex: 'model_name', width: 180 },
            { title: '调用人', dataIndex: 'user_id', width: 80 },
            { title: 'prompt 字符', dataIndex: 'prompt_chars', width: 110 },
            { title: 'token', dataIndex: 'tokens', width: 90 },
            {
              title: '耗时(秒)',
              dataIndex: 'elapsed',
              width: 90,
              render: (value: number) => (value ? value.toFixed(1) : '-'),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 90,
              render: (value: string) => (
                <Tag color={STATUS_TAGS[value]}>{value === 'success' ? '成功' : '失败'}</Tag>
              ),
            },
            {
              title: '错误信息(已脱敏)',
              dataIndex: 'error_msg',
              ellipsis: true,
              render: (value: string) =>
                value ? <Text type="secondary">{value}</Text> : <Text type="secondary">-</Text>,
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 170,
              render: (value: string) => <Text style={{ fontSize: 12 }}>{value}</Text>,
            },
          ]}
        />
      </Card>
    </div>
  );
};

export default InvokeLogPage;
