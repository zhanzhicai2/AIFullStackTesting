import React from 'react';
import { Button, Empty, Input, Space, Spin, Tag, Typography } from 'antd';
import { CopyOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { DataFactoryDataset } from '@/services/datafactory';

interface Props {
  datasets: DataFactoryDataset[];
  current: DataFactoryDataset | null;
  loading?: boolean;
  keyword: string;
  onKeywordChange: (value: string) => void;
  onSelect: (dataset: DataFactoryDataset) => void;
  onCreate: () => void;
  onRemove: (id: number) => void;
  onDuplicate: (dataset: DataFactoryDataset) => void;
}

/**
 * 左侧数据集列表
 */
const DatasetList: React.FC<Props> = ({
  datasets,
  current,
  loading,
  keyword,
  onKeywordChange,
  onSelect,
  onCreate,
  onRemove,
  onDuplicate,
}) => {
  return (
    <div className="df-dataset-list">
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Input.Search
          placeholder="搜索数据集"
          allowClear
          value={keyword}
          onChange={(e) => onKeywordChange(e.target.value)}
        />
        <Button type="primary" icon={<PlusOutlined />} block onClick={onCreate}>
          新建数据集
        </Button>
      </Space>

      <Spin spinning={loading}>
        {datasets.length === 0 && !loading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有数据集" style={{ marginTop: 40 }} />
        ) : (
          <div style={{ marginTop: 12 }}>
            {datasets.map((item) => {
              const active = current?.id === item.id;
              return (
                <div
                  key={item.id}
                  className={`df-dataset-item${active ? ' active' : ''}`}
                  onClick={() => onSelect(item)}
                >
                  <div className="df-dataset-name">
                    {item.name}
                    {item.status === 0 && <Tag color="default">已禁用</Tag>}
                  </div>
                  <div className="df-dataset-meta">
                    <span>{item.count} 条</span>
                    <span>seed {item.seed === 0 ? '随机' : item.seed}</span>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {item.table_name || '未绑定表'}
                    </Typography.Text>
                  </div>
                  <div className="df-dataset-ops" onClick={(e) => e.stopPropagation()}>
                    <Button
                      size="small"
                      type="text"
                      icon={<CopyOutlined />}
                      title="复制"
                      onClick={() => onDuplicate(item)}
                    />
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      title="删除"
                      onClick={() => onRemove(item.id)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Spin>
    </div>
  );
};

export default DatasetList;
