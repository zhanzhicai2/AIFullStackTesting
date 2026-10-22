import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Transfer, Tag, Typography } from 'antd';
import { modelTypeColor, modelTypeLabel } from '@/consts/ai';
import { AIModelBrief } from '@/services/ai';

interface Props {
  open: boolean;
  loading?: boolean;
  /** 厂商接口或系统模板返回的模型清单 */
  models: AIModelBrief[];
  /** 已经导入过的模型名,会从候选列表里剔除 */
  existed: string[];
  title?: string;
  onCancel: () => void;
  onOk: (names: string[], types: Record<string, string>) => void;
}

const FetchModelModal: React.FC<Props> = ({ open, loading, models, existed, title, onCancel, onOk }) => {
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (open) {
      setSelected([]);
      setSearch('');
    }
  }, [open]);

  const existedSet = useMemo(() => new Set(existed || []), [existed]);

  // 已经导入过的直接从候选里剔除,避免用户勾了之后才发现重复
  const candidates = useMemo(
    () => (models || []).filter((m) => !existedSet.has(m.name)),
    [models, existedSet]
  );

  const dataSource = useMemo(
    () =>
      candidates.map((m) => ({
        key: m.name,
        title: m.name,
        modelType: m.model_type,
      })),
    [candidates]
  );

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return dataSource;
    return dataSource.filter((item) => item.title.toLowerCase().includes(keyword));
  }, [dataSource, search]);

  const typeMap = useMemo(() => {
    const map: Record<string, string> = {};
    candidates.forEach((m) => (map[m.name] = m.model_type || 'chat'));
    return map;
  }, [candidates]);

  return (
    <Modal
      open={open}
      title={title || '选择要添加的模型'}
      width={720}
      onCancel={onCancel}
      destroyOnClose
      okText={`导入 (${selected.length})`}
      okButtonProps={{ disabled: selected.length === 0 }}
      onOk={() => onOk(selected, typeMap)}
    >
      <div style={{ marginBottom: 12 }}>
        <Typography.Text type="secondary">
          共 {models?.length || 0} 个模型
          {existed?.length ? `，已添加 ${existed.length} 个` : ''}
          ，可选 {candidates.length} 个
        </Typography.Text>
      </div>
      {candidates.length === 0 ? (
        <Typography.Text type="secondary">
          {existed?.length ? '这些模型都已经添加过了。' : '没有可选的模型，请确认 API Key 与 Base URL 是否可用。'}
        </Typography.Text>
      ) : (
        <Transfer
          dataSource={filtered}
          targetKeys={selected}
          showSearch
          titles={['可选模型', '待添加']}
          searchPlaceholder="搜索模型名"
          onSearch={(_, direction, value) => direction === 'left' && setSearch(value)}
          onChange={(keys) => setSelected(keys as string[])}
          listStyle={{ width: 290, height: 380 }}
          render={(item) => ({
            label: (
              <Typography.Text ellipsis style={{ maxWidth: 190 }} title={item.title}>
                {item.title}
              </Typography.Text>
            ),
            value: (
              <Tag color={modelTypeColor(item.modelType)} style={{ marginRight: 0 }}>
                {modelTypeLabel(item.modelType)}
              </Tag>
            ),
          })}
        />
      )}
      {loading && <Typography.Text type="secondary">正在获取模型列表…</Typography.Text>}
    </Modal>
  );
};

export default FetchModelModal;