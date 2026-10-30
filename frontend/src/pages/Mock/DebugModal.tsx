import React, { useEffect, useState } from 'react';
import { Alert, Button, Divider, Form, Input, message, Modal, Select, Typography } from 'antd';
import { MOCK_METHODS } from '@/consts/mock';
import { MockRulePreviewResult } from '@/services/mock';

const { Text } = Typography;

interface Props {
  open: boolean;
  projectId?: number;
  preview: (params: any) => Promise<MockRulePreviewResult | undefined>;
  onCancel: () => void;
}

/**
 * 规则调试 Modal —— 就地模拟一次匹配(spec FR-009 / US3)
 *
 * 填入请求方法、路径(可带 query)、请求体与请求头, 展示命中规则与变量解析后的最终响应;
 * 未命中时明确提示, 而不是展示空响应。
 */
const DebugModal: React.FC<Props> = ({ open, projectId, preview, onCancel }) => {
  const [form] = Form.useForm();
  const [result, setResult] = useState<MockRulePreviewResult | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ method: 'GET' });
      setResult(null);
    }
  }, [open, form]);

  const handleRun = async () => {
    const values = await form.validateFields();
    setRunning(true);
    try {
      const res = await preview({
        project_id: projectId,
        method: values.method,
        path: values.path,
        body: values.body || undefined,
        headers: values.headers || undefined,
      });
      setResult(res || null);
    } catch (e: any) {
      message.error(e?.message || '调试失败');
    } finally {
      setRunning(false);
    }
  };

  return (
    <Modal
      title="规则调试"
      open={open}
      onCancel={onCancel}
      footer={
        <Button type="primary" onClick={handleRun} loading={running}>
          发起调试
        </Button>
      }
      width={720}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item name="method" label="请求方法" rules={[{ required: true, message: '请选择方法' }]}>
          <Select options={MOCK_METHODS.map((m) => ({ label: m, value: m }))} placeholder="选择方法" />
        </Form.Item>
        <Form.Item
          name="path"
          label="请求路径"
          extra={<Text type="secondary">被测接口路径, 可带 query —— 如 /api/user/1?name=tom</Text>}
          rules={[{ required: true, message: '请填写请求路径' }]}
        >
          <Input placeholder="/api/user/1?name=tom" />
        </Form.Item>
        <Form.Item name="body" label="请求体(JSON 字符串, 选填)">
          <Input.TextArea rows={3} placeholder='{"name": "tom"}' />
        </Form.Item>
        <Form.Item name="headers" label="请求头(JSON 对象, 选填)">
          <Input.TextArea rows={2} placeholder='{"X-Token": "abc"}' />
        </Form.Item>
      </Form>
      <Divider style={{ margin: '8px 0' }} />
      {result === null ? (
        <Text type="secondary">填写请求后点击「发起调试」, 查看命中规则与最终响应。</Text>
      ) : result.matched ? (
        <>
          <Alert
            type="success"
            showIcon
            message={`命中规则: ${result.rule?.name}(优先级 ${result.rule?.priority})`}
            description={`${result.rule?.method} ${result.rule?.path} → HTTP ${result.status_code} · 延迟 ${result.delay}ms`}
            style={{ marginBottom: 8 }}
          />
          <Text type="secondary">响应头:</Text>
          <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
            {result.response_headers || '(无)'}
          </pre>
          <Text type="secondary">解析后响应体:</Text>
          <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
            {result.response_body || '(空)'}
          </pre>
        </>
      ) : (
        <Alert type="warning" showIcon message={result.reason || '没有规则会命中该请求'} />
      )}
    </Modal>
  );
};

export default DebugModal;
