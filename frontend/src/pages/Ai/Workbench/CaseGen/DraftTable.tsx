import React, { useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import { CheckOutlined, CloseOutlined, EyeOutlined } from '@ant-design/icons';
import { AiDraftSummary } from '@/services/aiWorkbench';
import { AI_DRAFT_STATUS, AI_DRAFT_STATUS_LABEL } from '@/consts/aiWorkbench';

const { Text } = Typography;

export interface DraftTableProps {
  drafts: AiDraftSummary[];
  total: number;
  loading: boolean;
  /** 有草稿被拒时把原因回显出来 */
  failed?: Array<{ id: number; reason: string }>;
  onAccept: (draftIds: number[]) => void;
  onReject: (draftIds: number[]) => void;
  onView: (draft: AiDraftSummary) => void;
  onStatusFilter: (status?: number) => void;
}

const PRIORITY_TAGS: Record<string, string> = {
  P0: 'magenta',
  P1: 'red',
  P2: 'volcano',
  P3: 'orange',
  P4: 'green',
};

/**
 * 草稿审核表
 *
 * 列与后端 `pity_ai_case_draft` 一一对应: 标题 / 编码 / 优先级 / 类别 / 状态 / 步骤数 / 操作。
 * 支持多选、状态筛选、批量采纳、批量驳回。
 */
const DraftTable: React.FC<DraftTableProps> = ({
  drafts,
  total,
  loading,
  failed,
  onAccept,
  onReject,
  onView,
  onStatusFilter,
}) => {
  const [selected, setSelected] = useState<number[]>([]);
  const [status, setStatus] = useState<number | undefined>(undefined);

  const columns = useMemo(
    () => [
      {
        title: '标题',
        dataIndex: 'title',
        ellipsis: true,
        render: (value: string, record: AiDraftSummary) => (
          <Space size={4}>
            <Text strong>{value}</Text>
            {record.warn && record.warn.length > 0 ? (
              <Tooltip title={record.warn.join('\n')}>
                <Tag color="warning">{record.warn.length} 条告警</Tag>
              </Tooltip>
            ) : null}
          </Space>
        ),
      },
      { title: '编码', dataIndex: 'code', width: 110 },
      {
        title: '优先级',
        dataIndex: 'priority',
        width: 90,
        render: (value: string) => <Tag color={PRIORITY_TAGS[value]}>{value}</Tag>,
      },
      { title: '类别', dataIndex: 'category', width: 100 },
      {
        title: '状态',
        dataIndex: 'status',
        width: 90,
        render: (value: number) => (
          <Tag color={value === AI_DRAFT_STATUS.PENDING ? 'processing' : value === AI_DRAFT_STATUS.ACCEPTED ? 'success' : 'default'}>
            {AI_DRAFT_STATUS_LABEL[value] || value}
          </Tag>
        ),
      },
      { title: '步骤数', dataIndex: 'steps', width: 80 },
      {
        title: '操作',
        dataIndex: 'id',
        width: 90,
        render: (_: unknown, record: AiDraftSummary) => (
          <a onClick={() => onView(record)}>
            <EyeOutlined /> 详情
          </a>
        ),
      },
    ],
    [onView],
  );

  const pendingIds = drafts
    .filter((item) => item.status === AI_DRAFT_STATUS.PENDING)
    .map((item) => item.id);

  return (
    <Card
      bordered={false}
      title="用例草稿"
      extra={
        <Space>
          <Select
            style={{ width: 130 }}
            allowClear
            placeholder="按状态筛选"
            value={status}
            onChange={(value) => {
              setStatus(value);
              onStatusFilter(value);
            }}
            options={[
              { label: '待审核', value: AI_DRAFT_STATUS.PENDING },
              { label: '已采纳', value: AI_DRAFT_STATUS.ACCEPTED },
              { label: '已驳回', value: AI_DRAFT_STATUS.REJECTED },
            ]}
          />
          <Button
            type="primary"
            icon={<CheckOutlined />}
            disabled={selected.length === 0}
            onClick={() => onAccept(selected)}
          >
            批量采纳{selected.length ? `(${selected.length})` : ''}
          </Button>
          <Button
            danger
            icon={<CloseOutlined />}
            disabled={selected.length === 0}
            onClick={() => onReject(selected)}
          >
            批量驳回
          </Button>
        </Space>
      }
    >
      {failed && failed.length > 0 ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={`${failed.length} 条草稿未通过采纳前校验, 状态保持「待审核」`}
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {failed.map((item) => (
                <li key={item.id}>
                  #{item.id}: {item.reason}
                </li>
              ))}
            </ul>
          }
        />
      ) : null}

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={drafts}
        pagination={{
          total,
          showSizeChanger: true,
          showTotal: (count) => `共 ${count} 条`,
        }}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有草稿 —— 在左边填好需求后点「开始生成用例」"
            />
          ),
        }}
        rowSelection={{
          selectedRowKeys: selected,
          onChange: (keys) => setSelected(keys as number[]),
          getCheckboxProps: (record: AiDraftSummary) => ({
            // 只有待审核的草稿能选 —— 已采纳/已驳回的状态是终态
            disabled: record.status !== AI_DRAFT_STATUS.PENDING,
          }),
        }}
      />
      {pendingIds.length === 0 && drafts.length > 0 ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          当前批次没有待审核的草稿了
        </Text>
      ) : null}
    </Card>
  );
};

export default DraftTable;
