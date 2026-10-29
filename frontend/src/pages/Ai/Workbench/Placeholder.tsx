import React from 'react';
import { Button, Card, Empty, Space, Typography } from 'antd';
import { history } from '@umijs/max';

const { Title, Paragraph, Text } = Typography;

export interface PlaceholderProps {
  title: string;
  desc: string;
  /** 这个模块会做什么 —— 让占位页也能说明白, 而不是一句"建设中" */
  points?: string[];
  backPath?: string;
}

/**
 * AI 工作台各场景的占位组件
 *
 * Phase 1 只有骨架: 路由先挂上, 组件用占位页顶着, 避免「路由指向不存在的组件」。
 * 各故事阶段(US1~US4)会把这个占位替换成真实实现。
 */
const Placeholder: React.FC<PlaceholderProps> = ({ title, desc, points, backPath }) => {
  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>{title}</Title>
      <Paragraph type="secondary">{desc}</Paragraph>
      <Card>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="该模块建设中"
          style={{ padding: '24px 0' }}
        >
          {points && points.length > 0 && (
            <ul style={{ textAlign: 'left', color: '#8c8c8c', margin: '0 0 16px', paddingLeft: 20 }}>
              {points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          )}
          <Space>
            <Button type="primary" onClick={() => history.push(backPath || '/ai/workbench')}>
              返回工作台
            </Button>
          </Space>
          <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
            实现进度见 specs/001-ai-workbench/tasks.md
          </Text>
        </Empty>
      </Card>
    </div>
  );
};

export default Placeholder;
