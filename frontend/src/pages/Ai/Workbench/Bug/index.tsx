import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { history, useSearchParams } from '@umijs/max';
import { useModel } from '@umijs/max';
import { AiBugAnalysis, AiVendorModels } from '@/services/aiWorkbench';
import { AI_HISTORY_PATTERN_LABEL } from '@/consts/aiWorkbench';

const { Text, Paragraph } = Typography;

/**
 * Bug 分析
 *
 * 两种入口:
 * - 报告详情页点「AI 分析」跳过来, URL 带 `result_id` —— 上下文由后端自动组装
 * - 直接粘贴堆栈文本
 *
 * **没有原文依据的结论标灰并标注「低可信」**(spec FR-020) —— 后端把对不上的
 * evidence 移进了 `unsupported`, 前端据此标灰。
 */
const BugPage: React.FC = () => {
  const { models, generatingBug, analyzeBug, fetchModels } = useModel('aiWorkbench');
  const [searchParams] = useSearchParams();
  const resultId = searchParams.get('result_id');

  const [text, setText] = useState('');
  const [vendorId, setVendorId] = useState<number | undefined>();
  const [modelId, setModelId] = useState<number | undefined>();
  const [result, setResult] = useState<AiBugAnalysis | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  useEffect(() => {
    if (resultId) {
      setText('');
    }
  }, [resultId]);

  const modelOptions = useMemo(() => {
    const vendor = models.find((item) => item.vendor_id === vendorId);
    return (vendor?.models || []).map((item) => ({ label: item.model_name, value: item.model_id }));
  }, [models, vendorId]);

  const noModel = models.length === 0;

  const handleAnalyze = async () => {
    if (!resultId && !text.trim()) {
      message.warning('请粘贴报错堆栈, 或从报告详情页点「AI 分析」进来');
      return;
    }
    if (!vendorId || !modelId) {
      message.warning('请先选择模型');
      return;
    }
    setError('');
    try {
      const data: any = await analyzeBug({
        result_id: resultId ? Number(resultId) : undefined,
        text: resultId ? undefined : text,
        vendor_id: vendorId,
        model_id: modelId,
      });
      if (data) setResult(data);
    } catch (e: any) {
      setError(e?.msg || e?.message || '分析失败, 请重试');
    }
  };

  const historyBlock = result?.history;

  return (
    <div className="ai-workbench-page">
      <Row gutter={12}>
        <Col xs={24} xl={8}>
          <Card variant="borderless" title="分析输入">
            {noModel ? (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="当前无可用模型"
                description={
                  <span>
                    去
                    <a onClick={() => history.push('/ai/vendor')}>模型服务商</a>
                    配置或启用一个对话模型。
                  </span>
                }
              />
            ) : null}
            {resultId ? (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message={`已载入执行记录 #${resultId}`}
                description="请求 / 响应 / 断言明细 / 执行日志 / 耗时 / 重试次数由平台自动组装, 并补了该用例最近 10 次执行历史。"
              />
            ) : (
              <Input.TextArea
                rows={12}
                placeholder="把报错堆栈粘贴到这里"
                value={text}
                onChange={(e) => setText(e.target.value)}
                style={{ fontFamily: 'monospace' }}
              />
            )}
            <Space.Compact style={{ width: '100%', marginTop: 12 }}>
              <Select
                style={{ flex: 1 }}
                placeholder="选择厂商"
                value={vendorId}
                disabled={noModel}
                options={models.map((item: AiVendorModels) => ({
                  label: item.vendor_name,
                  value: item.vendor_id,
                }))}
                onChange={(value) => {
                  setVendorId(value);
                  setModelId(undefined);
                }}
              />
              <Select
                style={{ flex: 1 }}
                placeholder="选择模型"
                value={modelId}
                disabled={!vendorId}
                options={modelOptions}
                onChange={setModelId}
              />
            </Space.Compact>
            <Button
              type="primary"
              block
              style={{ marginTop: 12 }}
              loading={generatingBug}
              disabled={noModel || !vendorId || !modelId}
              onClick={handleAnalyze}
            >
              开始分析
            </Button>
            {error ? (
              <Alert type="error" showIcon style={{ marginTop: 12 }} message={error} />
            ) : null}
          </Card>

          {historyBlock ? (
            <Card variant="borderless" title="历史规律">
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="判定">
                  <Tag color={historyBlock.pattern === 'consistent_failure' ? 'red' : 'blue'}>
                    {AI_HISTORY_PATTERN_LABEL[historyBlock.pattern] || historyBlock.pattern}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="最近执行">
                  {historyBlock.total} 次(失败 {historyBlock.failed} / 成功 {historyBlock.passed})
                </Descriptions.Item>
                <Descriptions.Item label="连续失败">{historyBlock.consecutive_failures} 次</Descriptions.Item>
                <Descriptions.Item label="说明">{historyBlock.note}</Descriptions.Item>
              </Descriptions>
              {historyBlock.recent?.length ? (
                <Table
                  size="small"
                  rowKey="result_id"
                  style={{ marginTop: 12 }}
                  pagination={false}
                  dataSource={historyBlock.recent}
                  columns={[
                    { title: '时间', dataIndex: 'finished_at', width: 150 },
                    {
                      title: '结果',
                      dataIndex: 'status',
                      width: 70,
                      render: (value: number) => (
                        <Tag color={value === 0 ? 'success' : 'error'}>
                          {value === 0 ? '成功' : '失败'}
                        </Tag>
                      ),
                    },
                    { title: '耗时', dataIndex: 'cost', width: 70 },
                    { title: '失败摘要', dataIndex: 'summary', ellipsis: true },
                  ]}
                />
              ) : null}
            </Card>
          ) : null}
        </Col>

        <Col xs={24} xl={16}>
          <Spin spinning={generatingBug}>
            <Card variant="borderless" title="分析结论">
              {!result ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="还没有分析结果 —— 在左边粘贴堆栈或从报告详情页点「AI 分析」"
                />
              ) : (
                <div>
                  <Space style={{ marginBottom: 12 }}>
                    <Tag color="blue">{result.category}</Tag>
                    <Tag>可信度 {(result.confidence * 100).toFixed(0)}%</Tag>
                    {result.analysis_id ? <Tag>分析 #{result.analysis_id}</Tag> : null}
                  </Space>
                  <Paragraph strong>{result.summary}</Paragraph>

                  <Paragraph strong>根因假设</Paragraph>
                  {result.root_causes?.length ? (
                    result.root_causes.map((cause, index) => {
                      // 没有原文依据的结论 → 标灰并标注「低可信」(FR-020)
                      const lowTrust = (cause.evidence?.length || 0) === 0;
                      return (
                        <Card
                          key={index}
                          size="small"
                          style={{ marginBottom: 8, opacity: lowTrust ? 0.55 : 1 }}
                          title={
                            <Space>
                              <Text strong>{cause.cause}</Text>
                              {lowTrust ? <Tag color="warning">低可信 · 无原文依据</Tag> : null}
                            </Space>
                          }
                        >
                          <Paragraph style={{ marginBottom: 8 }}>
                            <Text type="secondary">原文依据</Text>
                          </Paragraph>
                          {cause.evidence?.length ? (
                            cause.evidence.map((item) => (
                              <Paragraph key={item} style={{ marginBottom: 4 }}>
                                <Text code>{item}</Text>
                              </Paragraph>
                            ))
                          ) : (
                            <Text type="secondary">没有可核对的原文依据</Text>
                          )}
                          {cause.unsupported?.length ? (
                            <Paragraph style={{ marginBottom: 4, marginTop: 8 }}>
                              <Text type="secondary">以下引用在上下文里找不到, 已降级为无依据:</Text>
                            </Paragraph>
                          ) : null}
                          {cause.unsupported?.length
                            ? cause.unsupported.map((item) => (
                                <Paragraph key={item} style={{ marginBottom: 4 }}>
                                  <Text code delete>
                                    {item}
                                  </Text>
                                </Paragraph>
                              ))
                            : null}
                          {cause.verify_checklist?.length ? (
                            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
                              <Text type="secondary">自证清单</Text>
                            </Paragraph>
                          ) : null}
                          {cause.verify_checklist?.length
                            ? cause.verify_checklist.map((item) => (
                                <Paragraph key={item} style={{ marginBottom: 2 }}>
                                  · {item}
                                </Paragraph>
                              ))
                            : null}
                        </Card>
                      );
                    })
                  ) : (
                    <Text type="secondary">模型没有给出根因假设</Text>
                  )}

                  {result.fix_suggestions?.length ? (
                    <>
                      <Paragraph strong>修复建议</Paragraph>
                      {result.fix_suggestions.map((item, index) => (
                        <Card key={index} size="small" style={{ marginBottom: 8 }}>
                          <Paragraph strong style={{ marginBottom: 4 }}>
                            {item.title}
                          </Paragraph>
                          <Paragraph style={{ marginBottom: item.patch ? 8 : 0 }}>{item.detail}</Paragraph>
                          {item.patch ? <pre style={{ margin: 0 }}>{item.patch}</pre> : null}
                        </Card>
                      ))}
                    </>
                  ) : null}

                  {result.repro_steps?.length ? (
                    <>
                      <Space style={{ marginTop: 8 }}>
                        <Paragraph strong style={{ marginBottom: 4 }}>
                          复现步骤
                        </Paragraph>
                        <Button
                          size="small"
                          onClick={() => {
                            const prompt = result.repro_steps.join('\n');
                            history.push(`/ai/casegen?prompt=${encodeURIComponent(prompt)}`);
                          }}
                        >
                          用此生成用例
                        </Button>
                      </Space>
                      <ol>
                        {result.repro_steps.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ol>
                    </>
                  ) : null}
                </div>
              )}
            </Card>
          </Spin>
        </Col>
      </Row>
    </div>
  );
};

export default BugPage;
