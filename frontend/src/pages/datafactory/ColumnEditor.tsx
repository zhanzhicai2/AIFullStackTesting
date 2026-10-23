import React, { useMemo } from 'react';
import { Button, Input, InputNumber, Select, Space, Tag, Tooltip } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { COLUMN_TYPES, FAKER_PROVIDERS, RULE_KINDS, ruleKindHint, ruleKindLabel } from '@/consts/datafactory';
import { DataFactoryColumn } from '@/services/datafactory';

interface Props {
  value?: DataFactoryColumn[];
  onChange?: (columns: DataFactoryColumn[]) => void;
  fieldNames?: string[];
}

const { TextArea } = Input;

const emptyColumn = (): DataFactoryColumn => ({
  name: '',
  type: 'string',
  rule: { kind: 'fixed', value: '' },
  unique: false,
  nullable: false,
  comment: '',
});

/**
 * 字段规则编辑器。
 * kind 决定该显示哪些参数输入框, 参数存在 rule 对象里。
 */
const ColumnEditor: React.FC<Props> = ({ value = [], onChange, fieldNames = [] }) => {
  const columns = value || [];
  const fieldNamesInUse = useMemo(() => columns.map((c) => c.name).filter(Boolean), [columns]);

  const update = (index: number, patch: Partial<DataFactoryColumn>) => {
    const next = columns.map((item, i) => (i === index ? { ...item, ...patch } : item));
    onChange?.(next);
  };

  const updateRule = (index: number, patch: Record<string, any>) => {
    const next = columns.map((item, i) =>
      i === index ? { ...item, rule: { ...item.rule, ...patch } } : item
    );
    onChange?.(next);
  };

  const onKindChange = (index: number, kind: string) => {
    // 只改 kind, 旧参数保留在 rule 里 —— 换回来时参数还在, 后端按 kind 取用, 多余的键会被忽略
    updateRule(index, { kind });
  };

  const remove = (index: number) => {
    onChange?.(columns.filter((_, i) => i !== index));
  };

  const add = () => {
    onChange?.([...columns, emptyColumn()]);
  };

  const renderParams = (column: DataFactoryColumn, index: number) => {
    const kind = column.rule?.kind || 'fixed';
    switch (kind) {
      case 'fixed':
        return (
          <Input
            size="small"
            placeholder="固定值"
            value={column.rule?.value ?? ''}
            onChange={(e) => updateRule(index, { value: e.target.value })}
          />
        );
      case 'random':
        return (
          <Space.Compact style={{ width: '100%' }}>
            <InputNumber
              size="small"
              style={{ width: '33%' }}
              placeholder="最小"
              value={column.rule?.min}
              onChange={(v) => updateRule(index, { min: v })}
            />
            <InputNumber
              size="small"
              style={{ width: '33%' }}
              placeholder="最大"
              value={column.rule?.max}
              onChange={(v) => updateRule(index, { max: v })}
            />
            <InputNumber
              size="small"
              style={{ width: '33%' }}
              placeholder="小数位"
              value={column.rule?.decimals}
              onChange={(v) => updateRule(index, { decimals: v })}
            />
          </Space.Compact>
        );
      case 'enum':
        return (
          <TextArea
            size="small"
            rows={2}
            placeholder="每行一个值, 如 男&#10;女"
            value={(column.rule?.values || []).join('\n')}
            onChange={(e) =>
              updateRule(index, { values: e.target.value.split('\n').filter((v) => v.trim() !== '') })
            }
          />
        );
      case 'sequence':
        return (
          <Space.Compact style={{ width: '100%' }}>
            <InputNumber
              size="small"
              style={{ width: '50%' }}
              placeholder="起始"
              value={column.rule?.start}
              onChange={(v) => updateRule(index, { start: v })}
            />
            <InputNumber
              size="small"
              style={{ width: '50%' }}
              placeholder="步长"
              value={column.rule?.step}
              onChange={(v) => updateRule(index, { step: v })}
            />
          </Space.Compact>
        );
      case 'uuid':
        return (
          <Input
            size="small"
            placeholder="前缀(可空)"
            value={column.rule?.prefix ?? ''}
            onChange={(e) => updateRule(index, { prefix: e.target.value })}
          />
        );
      case 'template':
        return (
          <Input
            size="small"
            placeholder="138########"
            value={column.rule?.template ?? ''}
            onChange={(e) => updateRule(index, { template: e.target.value })}
          />
        );
      case 'regex':
        return (
          <Input
            size="small"
            placeholder="^1[3-9]\d{9}$"
            value={column.rule?.pattern ?? ''}
            onChange={(e) => updateRule(index, { pattern: e.target.value })}
          />
        );
      case 'reference':
        return (
          <Select
            size="small"
            style={{ width: '100%' }}
            placeholder="选择被引用的字段"
            value={column.rule?.from}
            onChange={(v) => updateRule(index, { from: v })}
          >
            {fieldNames
              .filter((name) => name !== column.name)
              .map((name) => (
                <Select.Option key={name} value={name}>
                  {name}
                </Select.Option>
              ))}
          </Select>
        );
      case 'faker':
        return (
          <Select
            size="small"
            style={{ width: '100%' }}
            showSearch
            placeholder="选择 provider"
            value={column.rule?.provider}
            onChange={(v) => updateRule(index, { provider: v })}
          >
            {FAKER_PROVIDERS.map((p) => (
              <Select.Option key={p} value={p}>
                {p}
              </Select.Option>
            ))}
          </Select>
        );
      case 'func':
        return (
          <Input
            size="small"
            placeholder="${random_int(1,100)}"
            value={column.rule?.expr ?? ''}
            onChange={(e) => updateRule(index, { expr: e.target.value })}
          />
        );
      case 'date':
        return (
          <Space.Compact style={{ width: '100%' }}>
            <Input
              size="small"
              style={{ width: '40%' }}
              placeholder="起始 -30d"
              value={column.rule?.start ?? ''}
              onChange={(e) => updateRule(index, { start: e.target.value })}
            />
            <Input
              size="small"
              style={{ width: '30%' }}
              placeholder="now"
              value={column.rule?.end ?? ''}
              onChange={(e) => updateRule(index, { end: e.target.value })}
            />
            <Input
              size="small"
              style={{ width: '30%' }}
              placeholder="%Y-%m-%d"
              value={column.rule?.format ?? ''}
              onChange={(e) => updateRule(index, { format: e.target.value })}
            />
          </Space.Compact>
        );
      default:
        return <span style={{ color: '#999' }}>不支持的生成方式</span>;
    }
  };

  return (
    <div>
      {columns.length === 0 && (
        <div style={{ padding: '24px 0', textAlign: 'center', color: '#999' }}>
          还没有字段, 点右上角「新增字段」或用「AI 生成规则 / 从表结构导入」
        </div>
      )}
      {columns.map((column, index) => (
        <div
          key={index}
          style={{
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            padding: 12,
            marginBottom: 8,
            background: '#fafafa',
          }}
        >
          <Space style={{ width: '100%', marginBottom: 8 }} align="center">
            <Input
              size="small"
              style={{ width: 180 }}
              placeholder="字段名"
              value={column.name}
              onChange={(e) => update(index, { name: e.target.value })}
            />
            <Select
              size="small"
              style={{ width: 100 }}
              value={column.type}
              onChange={(v) => update(index, { type: v })}
            >
              {COLUMN_TYPES.map((t) => (
                <Select.Option key={t.value} value={t.value}>
                  {t.label}
                </Select.Option>
              ))}
            </Select>
            <Select
              size="small"
              style={{ width: 140 }}
              value={column.rule?.kind || 'fixed'}
              onChange={(v) => onKindChange(index, v)}
            >
              {RULE_KINDS.map((k) => (
                <Select.Option key={k.value} value={k.value}>
                  {k.label}
                </Select.Option>
              ))}
            </Select>
            <Tooltip title={ruleKindHint(column.rule?.kind)}>
              <Tag color="blue">{ruleKindLabel(column.rule?.kind)}</Tag>
            </Tooltip>
            <Space size={4}>
              <Tooltip title="该字段不允许重复">
                <Button
                  size="small"
                  type={column.unique ? 'primary' : 'default'}
                  onClick={() => update(index, { unique: !column.unique })}
                >
                  唯一
                </Button>
              </Tooltip>
              <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => remove(index)} />
            </Space>
          </Space>
          <div style={{ marginBottom: 8 }}>{renderParams(column, index)}</div>
          <Input
            size="small"
            placeholder="字段说明(可空)"
            value={column.comment ?? ''}
            onChange={(e) => update(index, { comment: e.target.value })}
          />
        </div>
      ))}
      <Button icon={<PlusOutlined />} onClick={add} type="dashed" block>
        新增字段
      </Button>
      {fieldNamesInUse.length > 0 && (
        <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
          可被引用的字段: {fieldNamesInUse.join(', ')}
        </div>
      )}
    </div>
  );
};

export default ColumnEditor;
