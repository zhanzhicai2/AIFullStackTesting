import React from 'react';
import { Alert, Card, Space, Typography } from 'antd';
import { PageContainer } from '@ant-design/pro-components';

const { Paragraph, Text } = Typography;

/**
 * 实用工具页的统一外壳 —— 12 个工具页共用, 保证标题位置、留白、结果区一致。
 *
 * `title={false}` 与既有的 `Tool/SqlOnline` 保持一致: 外层 layout 已经给了
 * 页面头, PageContainer 再渲染一份会出现双标题。**面包屑刻意保留** ——
 * `/tool/` 下有 15 个平铺入口, 没有面包屑容易忘了自己在哪个工具里。
 *
 * 注意 SqlOnline 用的是 `breadcrumb={null}`(它是 .jsx, 不过类型检查),
 * 这里不能照抄: `BreadcrumbProps` 不接受 `null`, tsc 会报 TS2322。
 */
export const ToolShell: React.FC<{
  title: string;
  description?: React.ReactNode;
  extra?: React.ReactNode;
  children: React.ReactNode;
}> = ({ title, description, extra, children }) => (
  <PageContainer title={false}>
    <Card
      title={
        <Space direction="vertical" size={2}>
          <Text strong style={{ fontSize: 16 }}>
            {title}
          </Text>
          {description ? (
            <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {description}
            </Text>
          ) : null}
        </Space>
      }
      extra={extra}
    >
      {children}
    </Card>
  </PageContainer>
);

/**
 * 工具输出区 —— 只读展示 + 一键复制。
 *
 * 用 `Paragraph` 而不是 `TextArea`: 复制按钮是 antd 原生的, 不用自己接
 * `navigator.clipboard`(它在 http 非安全上下文下不可用, 与 `crypto.subtle` 同病)。
 */
export const ToolResult: React.FC<{
  value: string;
  label?: string;
  /** 有值时在结果上方渲染一条提示(错误/警告) */
  notice?: { type: 'success' | 'error' | 'warning' | 'info'; text: string } | null;
  emptyText?: string;
}> = ({ value, label = '结果', notice, emptyText = '等待输入' }) => (
  <Space direction="vertical" style={{ width: '100%' }} size={8}>
    {notice ? (
      <Alert type={notice.type} showIcon message={notice.text} style={{ marginBottom: 0 }} />
    ) : null}
    <Text type="secondary" style={{ fontSize: 12 }}>
      {label}
    </Text>
    {value ? (
      <Paragraph
        copyable={{ text: value }}
        style={{
          marginBottom: 0,
          padding: 12,
          background: 'rgba(0,0,0,0.04)',
          borderRadius: 6,
          maxHeight: 360,
          overflow: 'auto',
          fontFamily: 'monospace',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {value}
      </Paragraph>
    ) : (
      <Text type="secondary">{emptyText}</Text>
    )}
  </Space>
);

/** 输入区标签 —— 统一各页面表单项上方的小标题 */
export const ToolLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text type="secondary" style={{ fontSize: 12 }}>
    {children}
  </Text>
);
