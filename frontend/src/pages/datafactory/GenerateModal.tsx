import React, { useEffect, useMemo, useState } from 'react';
import { Button, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { DownloadOutlined, DatabaseOutlined, LinkOutlined } from '@ant-design/icons';
import { DataFactoryColumn, GeneratePayload } from '@/services/datafactory';

interface Props {
  open: boolean;
  rows: Record<string, any>[];
  columns: DataFactoryColumn[];
  /** 数据集里已配的目标库 / 目标表 / 环境, 打开弹窗时做初值, 免得每次重填 */
  defaultDatabaseId?: number;
  defaultTableName?: string;
  defaultEnv?: number;
  exporting?: boolean;
  writing?: boolean;
  binding?: boolean;
  databaseOptions?: { label: string; value: number }[];
  caseOptions?: { label: string; value: number }[];
  onCancel: () => void;
  onExport: (payload: GeneratePayload & { file_type: string }, filename: string) => void;
  onWriteDb: (payload: GeneratePayload & { database_id: number; table_name: string }) => void;
  onBindCase: (
    payload: GeneratePayload & { case_id: number; env: number; name_prefix?: string; replace?: boolean }
  ) => void;
}

/**
 * 生成结果预览 + 落地入口(导出 / 写库 / 绑定用例)。
 * 后端的导出/写库/绑定都是按 dataset_id + count + seed 重新生成一遍,
 * 所以这里不需要把大批量数据回传给后端。
 */
const GenerateModal: React.FC<Props> = ({
  open,
  rows,
  columns,
  defaultDatabaseId,
  defaultTableName,
  defaultEnv,
  exporting,
  writing,
  binding,
  databaseOptions = [],
  caseOptions = [],
  onCancel,
  onExport,
  onWriteDb,
  onBindCase,
}) => {
  const [fileType, setFileType] = useState('json');
  const [databaseId, setDatabaseId] = useState<number | undefined>();
  const [tableName, setTableName] = useState('');
  const [caseId, setCaseId] = useState<number | undefined>();
  const [env, setEnv] = useState<number | undefined>();
  const [namePrefix, setNamePrefix] = useState('数据工厂');

  // 组件常驻挂载(open 只是控制显隐), 所以每次打开都要用当前数据集重新灌一次初值
  useEffect(() => {
    if (!open) return;
    setDatabaseId(defaultDatabaseId);
    setTableName(defaultTableName || '');
    setEnv(defaultEnv);
  }, [open, defaultDatabaseId, defaultTableName, defaultEnv]);

  const fieldNames = columns.map((c) => c.name);

  // 预生成行 key。
  // antd 5.29 起废弃 rowKey 的第二参 index(按函数参数个数判定),
  // 所以这里提前给每行挂 key, 再用单参 rowKey; __rowKey 不在 fieldNames 里, 不会渲染成列
  const tableRows = useMemo(
    () => rows.map((row, index) => ({ ...row, __rowKey: `df-row-${index}` })),
    [rows]
  );

  const tableColumns = fieldNames.map((name) => ({
    title: name,
    dataIndex: name,
    key: name,
    ellipsis: true,
    render: (value: any) =>
      value === null || value === undefined ? (
        <Tag color="default">null</Tag>
      ) : (
        String(value)
      ),
  }));

  return (
    <Modal
      open={open}
      title={`生成结果预览 (${rows.length} 条)`}
      width={1100}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          关闭
        </Button>,
        <Button
          key="export"
          icon={<DownloadOutlined />}
          loading={exporting}
          onClick={() => onExport({ file_type: fileType, rows }, `datafactory.${fileType}`)}
        >
          导出文件
        </Button>,
        <Button
          key="write"
          icon={<DatabaseOutlined />}
          loading={writing}
          disabled={!databaseId || !tableName}
          onClick={() =>
            onWriteDb({
              rows,
              database_id: databaseId as number,
              table_name: tableName,
            })
          }
        >
          写入数据库
        </Button>,
        <Button
          key="bind"
          icon={<LinkOutlined />}
          loading={binding}
          disabled={!caseId || !env}
          onClick={() =>
            onBindCase({
              rows,
              case_id: caseId as number,
              env: env as number,
              name_prefix: namePrefix,
              replace: true,
            })
          }
        >
          绑定到用例
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Table
          size="small"
          rowKey="__rowKey"
          dataSource={tableRows}
          columns={tableColumns}
          pagination={{ pageSize: 10, size: 'small' }}
          scroll={{ x: 'max-content', y: 320 }}
        />
        <Space wrap>
          <Space.Compact>
            <span style={{ lineHeight: '32px' }}>导出格式</span>
            <Select
              style={{ width: 100 }}
              value={fileType}
              onChange={setFileType}
              options={[
                { label: 'JSON', value: 'json' },
                { label: 'SQL', value: 'sql' },
              ]}
            />
          </Space.Compact>
          <Space.Compact>
            <span style={{ lineHeight: '32px' }}>目标库</span>
            <Select
              style={{ width: 200 }}
              placeholder="选择数据库"
              value={databaseId}
              onChange={setDatabaseId}
              options={databaseOptions}
            />
          </Space.Compact>
          <Input
            style={{ width: 200 }}
            placeholder="目标表名"
            value={tableName}
            onChange={(e) => setTableName(e.target.value)}
          />
          <Space.Compact>
            <span style={{ lineHeight: '32px' }}>绑定用例</span>
            <Select
              style={{ width: 200 }}
              placeholder="选择用例"
              value={caseId}
              onChange={setCaseId}
              options={caseOptions}
            />
            <InputNumber
              style={{ width: 110 }}
              placeholder="环境id"
              value={env}
              onChange={(v) => setEnv(v === null ? undefined : v)}
            />
            <Input style={{ width: 140 }} placeholder="数据名前缀" value={namePrefix} onChange={(e) => setNamePrefix(e.target.value)} />
          </Space.Compact>
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          绑定到用例后, 这些数据会成为该用例的测试数据, 用例里用{' '}
          {'${字段名}'} 引用即可; 执行一次会按数据条数跑出多条测试结果。
        </Typography.Text>
      </Space>
    </Modal>
  );
};

export default GenerateModal;
