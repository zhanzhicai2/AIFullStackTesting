import React from 'react';
import { Card, Col, Row, Tag, Typography } from 'antd';
import { history } from '@umijs/max';
import {
  BugOutlined,
  CodeOutlined,
  FileSearchOutlined,
  ProfileOutlined,
} from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

interface SceneCard {
  key: string;
  title: string;
  desc: string;
  path: string;
  icon: React.ReactNode;
  tags: string[];
}

/**
 * AI 工作台首页 —— 四个场景的入口
 *
 * 四个场景共用一套公共能力(模型选择、调用流水、结论落库), 所以放在一个工作台下,
 * 与既有的 `/ai` 菜单(模型服务商 / 聊天助手)并列。
 */
const AiWorkbenchPage: React.FC = () => {
  const scenes: SceneCard[] = [
    {
      key: 'casegen',
      title: '用例生成',
      desc: '上传需求文档或粘贴需求文本, 生成可审核的用例草稿, 人工确认后批量采纳进用例库',
      path: '/ai/casegen',
      icon: <ProfileOutlined style={{ fontSize: 28 }} />,
      tags: ['草稿态', '人工审核', '14 条校验'],
    },
    {
      key: 'bug',
      title: 'Bug 分析',
      desc: '对失败用例做根因分析, 输出带原文依据的根因假设、修复建议与复现步骤',
      path: '/ai/bug',
      icon: <BugOutlined style={{ fontSize: 28 }} />,
      tags: ['证据校验', '历史规律', '复现步骤'],
    },
    {
      key: 'log',
      title: '日志分析',
      desc: '日志先做确定性聚类与突增检测, 再对错误簇逐簇归因, 只解读 Top-N 簇',
      path: '/ai/log',
      icon: <FileSearchOutlined style={{ fontSize: 28 }} />,
      tags: ['零 token 聚类', '突增检测', '逐簇归因'],
    },
    {
      key: 'sql',
      title: 'SQL 分析',
      desc: '慢查询排行, 单条 SQL 的执行计划解读、索引建议与改写建议, 改写结果可一键执行验证',
      path: '/ai/sql',
      icon: <CodeOutlined style={{ fontSize: 28 }} />,
      tags: ['只读采集', '索引建议', '改写可验证'],
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>AI 工作台</Title>
      <Paragraph type="secondary">
        AI 只做翻译与解读, 产物先进<strong>草稿态</strong>, 人工审核后才由确定性内核落地 —— 脏用例比没有用例更糟。
      </Paragraph>
      <Row gutter={[16, 16]}>
        {scenes.map((item) => (
          <Col key={item.key} xs={24} sm={12} lg={6}>
            <Card
              hoverable
              onClick={() => history.push(item.path)}
              style={{ height: '100%' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                {item.icon}
                <Text strong style={{ fontSize: 16 }}>
                  {item.title}
                </Text>
              </div>
              <Paragraph type="secondary" style={{ minHeight: 66 }}>
                {item.desc}
              </Paragraph>
              <div>
                {item.tags.map((tag) => (
                  <Tag key={tag} style={{ marginBottom: 4 }}>
                    {tag}
                  </Tag>
                ))}
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
};

export default AiWorkbenchPage;
