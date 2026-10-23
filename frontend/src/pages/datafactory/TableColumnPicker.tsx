import React, { useEffect, useState } from 'react';
import { Alert, Empty, Modal, Select, Space, Transfer, Typography } from 'antd';
import { TableColumn } from '@/services/datafactory';

interface Props {
  open: boolean;
  /** 目标库下拉, 来自 /config/dbconfig/list */
  databaseOptions: { label: string; value: number }[];
  /** 当前选中的目标库 id(弹窗内部维护, 打开时用数据集里的初值) */
  databaseId?: number;
  tables: string[];
  onCancel: () => void;
  onDatabaseChange: (databaseId?: number) => void;
  /** 选表后由调用方去拉列结构, 返回拉到的列 */
  onTableChange: (table: string) => Promise<TableColumn[]>;
  onConfirm: (columns: TableColumn[], databaseId?: number, table?: string) => void;
}

/**
 * 把 SQL 类型映射成数据工厂的字段类型
 */
export const guessType = (sqlType: string): string => {
  const t = (sqlType || '').toLowerCase();
  if (t.includes('int') || t.includes('serial') || t.includes('bit')) return 'int';
  if (t.includes('float') || t.includes('double') || t.includes('decimal') || t.includes('numeric')) {
    return 'float';
  }
  if (t.includes('bool')) return 'bool';
  return 'string';
};

/**
 * 从目标表结构导入字段。
 *
 * 目标库选在这一步, 而不是要求先在表单里填好 —— 弹窗里就能选库、选表、挑字段,
 * 一气呵成; 否则用户会先撞上"请先选择目标库"却不知道去哪填。
 * 确认后把库 id / 表名 / 字段一并回传, 由调用方写回数据集。
 */
const TableColumnPicker: React.FC<Props> = ({
  open,
  databaseOptions,
  databaseId,
  tables,
  onCancel,
  onDatabaseChange,
  onTableChange,
  onConfirm,
}) => {
  const [table, setTable] = useState<string | undefined>();
  // 列结构放在弹窗内部按所选表维护。
  // 之前复用 model 里的全局 tableColumns, 会把上一次选的表的列带进来 ——
  // 弹窗刚打开、表还没选时, 下面就已经列着一堆列, 状态对不上。
  const [columns, setColumns] = useState<TableColumn[]>([]);
  const [columnsLoading, setColumnsLoading] = useState(false);
  const [selected, setSelected] = useState<React.Key[]>([]);

  useEffect(() => {
    if (!open) {
      setTable(undefined);
      setColumns([]);
      setSelected([]);
      setColumnsLoading(false);
    }
  }, [open]);

  // 换表后默认全选(自增主键除外)
  useEffect(() => {
    setSelected(columns.filter((c) => !c.autoincrement).map((c) => c.name));
  }, [columns]);

  const dataSource = columns.map((c) => ({
    key: c.name,
    name: c.name,
    type: c.type,
    primary_key: c.primary_key,
    autoincrement: c.autoincrement,
    guess: guessType(c.type),
  }));

  const noDatabase = databaseOptions.length === 0;
  const canConfirm = !!databaseId && !!table && selected.length > 0;

  return (
    <Modal
      open={open}
      title="从表结构导入字段"
      width={860}
      onCancel={onCancel}
      onOk={() => onConfirm(columns.filter((c) => selected.includes(c.name)), databaseId, table)}
      okText={`导入选中的 ${selected.length} 个字段`}
      okButtonProps={{ disabled: !canConfirm }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Alert
          type="info"
          showIcon
          message="读取目标表的列结构自动生成字段规则（只读，不会往表里写数据）, 自增主键默认不导入"
        />

        {noDatabase ? (
          <Alert
            type="warning"
            showIcon
            message="还没有可用的目标库, 请先到「配置 → 数据库配置」里添加一条, 再回来导入"
          />
        ) : (
          <Space wrap>
            <span style={{ width: 64 }}>目标库</span>
            <Select
              showSearch
              optionFilterProp="label"
              style={{ width: 240 }}
              placeholder="选择数据库"
              value={databaseId}
              onChange={(v) => {
                onDatabaseChange(v);
                setTable(undefined);
                setColumns([]);
              }}
              options={databaseOptions}
            />
            <span style={{ width: 64 }}>目标表</span>
            <Select
              showSearch
              style={{ width: 280 }}
              placeholder={databaseId ? '选择目标表' : '请先选择目标库'}
              disabled={!databaseId}
              loading={columnsLoading}
              value={table}
              onChange={async (v) => {
                setTable(v);
                setColumns([]);
                setColumnsLoading(true);
                try {
                  setColumns(await onTableChange(v));
                } finally {
                  setColumnsLoading(false);
                }
              }}
              options={tables.map((t) => ({ label: t, value: t }))}
            />
          </Space>
        )}

        {dataSource.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              columnsLoading
                ? '正在读取表结构...'
                : databaseId
                ? table
                  ? '该表没有可导入的列'
                  : '请选择目标表'
                : '先选择目标库和目标表'
            }
          />
        ) : (
          <Transfer
            dataSource={dataSource}
            showSearch
            titles={['可选字段', '已选字段']}
            targetKeys={selected}
            onChange={(keys) => setSelected(keys as React.Key[])}
            rowKey={(record) => record.key}
            render={(item: any) => (
              <Space direction="vertical" size={0}>
                <Typography.Text>{item.name}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {item.type} · 推断为 {item.guess}
                  {item.autoincrement ? ' · 自增主键' : ''}
                </Typography.Text>
              </Space>
            )}
            filterOption={(input, item) =>
              String(item.name || '').toLowerCase().includes(input.toLowerCase())
            }
          />
        )}
      </Space>
    </Modal>
  );
};

export default TableColumnPicker;
