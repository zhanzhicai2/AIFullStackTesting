import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Tag } from 'antd';
import { DatabaseOutlined, RobotOutlined, TableOutlined } from '@ant-design/icons';
import { DataFactoryColumn, DataFactoryDataset } from '@/services/datafactory';
import { ruleKindLabel } from '@/consts/datafactory';
import ColumnEditor from './ColumnEditor';

interface Props {
  dataset: DataFactoryDataset | null;
  saving?: boolean;
  envOptions: { label: string; value: number }[];
  projectOptions: { label: string; value: number }[];
  databaseOptions: { label: string; value: number }[];
  onSave: (payload: Record<string, unknown>) => void;
  onAiParse: () => void;
  onImportFromTable: () => void;
}

const parseColumns = (raw?: string): DataFactoryColumn[] => {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    const list = Array.isArray(parsed) ? parsed : parsed?.columns || [];
    return list as DataFactoryColumn[];
  } catch (e) {
    return [];
  }
};

/**
 * 数据集详情: 基本信息 + 字段规则
 */
const DatasetForm: React.FC<Props> = ({
  dataset,
  saving,
  envOptions,
  projectOptions,
  databaseOptions,
  onSave,
  onAiParse,
  onImportFromTable,
}) => {
  const [form] = Form.useForm();
  const [columns, setColumns] = useState<DataFactoryColumn[]>([]);
  // 记录当前表单对应的数据集 id, 只有换了数据集才整表回填
  const filledForId = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!dataset) {
      form.resetFields();
      setColumns([]);
      filledForId.current = undefined;
      return;
    }
    setColumns(parseColumns(dataset.columns));
    if (filledForId.current === dataset.id) {
      // 同一个数据集只是被更新了(AI 应用规则 / 从表结构导入会写库并刷新 current)。
      // 这时只同步这几个联动字段, 不能整表回填 —— 否则会把用户
      // 还没点「保存」的名称、备注等编辑静默覆盖掉。
      form.setFieldsValue({ count: dataset.count, database_id: dataset.database_id, table_name: dataset.table_name });
      return;
    }
    filledForId.current = dataset.id;
    form.setFieldsValue({
      name: dataset.name,
      env: dataset.env,
      project_id: dataset.project_id,
      database_id: dataset.database_id,
      table_name: dataset.table_name,
      count: dataset.count,
      seed: dataset.seed,
      remark: dataset.remark,
      status: dataset.status,
    });
  }, [dataset, form]);

  const fieldNames = useMemo(() => columns.map((c) => c.name).filter(Boolean), [columns]);

  const onFinish = (values: Record<string, any>) => {
    onSave({
      // id 为 0 表示"复制出来的新数据集", 不带 id 走新增
      ...(dataset && dataset.id ? { id: dataset.id } : {}),
      ...values,
      columns: JSON.stringify({ columns }),
    });
  };

  return (
    <Card
      title={dataset ? `编辑数据集 · ${dataset.name}` : '新建数据集'}
      bordered={false}
      extra={
        <Space>
          <Button icon={<TableOutlined />} onClick={onImportFromTable}>
            从表结构导入
          </Button>
          <Button icon={<RobotOutlined />} onClick={onAiParse}>
            AI 生成规则
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" onFinish={onFinish} disabled={saving}>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="name"
              label="数据集名称"
              rules={[{ required: true, message: '请输入数据集名称' }]}
            >
              <Input placeholder="如: 用户测试数据" />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="env" label="环境" rules={[{ required: true, message: '请选择环境' }]}>
              <Select placeholder="选择环境" options={envOptions} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="project_id" label="所属项目">
              <Select allowClear placeholder="可选" options={projectOptions} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="count" label="默认生成条数">
              <InputNumber style={{ width: '100%' }} min={1} max={10000} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item
              name="seed"
              label="随机种子"
              tooltip="相同种子生成的数据完全一致, 0 表示每次随机"
            >
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="database_id" label="目标库">
              <Select
                allowClear
                showSearch
                placeholder="写库时使用"
                options={databaseOptions}
                suffixIcon={<DatabaseOutlined />}
              />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="table_name" label="目标表">
              <Input placeholder="写库时使用" />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="status" label="状态">
              <Select
                options={[
                  { label: '启用', value: 1 },
                  { label: '禁用', value: 0 },
                ]}
              />
            </Form.Item>
          </Col>
          <Col span={16}>
            <Form.Item name="remark" label="备注">
              <Input placeholder="可选" />
            </Form.Item>
          </Col>
        </Row>

        <Card
          size="small"
          title="字段规则"
          bordered
          style={{ background: '#fff' }}
          extra={
            <Space size={4} wrap>
              {columns.map((c) => (
                <Tag key={c.name} color="blue">
                  {c.name} · {ruleKindLabel(c.rule?.kind)}
                </Tag>
              ))}
              {columns.length === 0 && <span style={{ color: '#999' }}>暂无字段</span>}
            </Space>
          }
        >
          <ColumnEditor value={columns} onChange={setColumns} fieldNames={fieldNames} />
        </Card>

        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <Space>
            <Button onClick={onImportFromTable}>从表结构导入</Button>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存
            </Button>
          </Space>
        </div>
      </Form>
    </Card>
  );
};

export { parseColumns };
export default DatasetForm;
