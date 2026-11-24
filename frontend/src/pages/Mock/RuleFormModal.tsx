import React, { useEffect } from 'react';
import { Alert, Form, Input, InputNumber, Modal, Select, Switch, Typography } from 'antd';
import { MOCK_MAX_DELAY, MOCK_METHODS, MOCK_VARIABLE_HINTS } from '@/consts/mock';
import { MockRule, MockRuleForm } from '@/services/mock';

const { Text } = Typography;

interface Props {
  open: boolean;
  /** 新建时为 null, 编辑时为规则对象 */
  record: MockRule | null;
  projectId?: number;
  saving: boolean;
  onCancel: () => void;
  onSubmit: (form: MockRuleForm) => Promise<string | undefined>;
}

/**
 * 新建 / 编辑 Mock 规则表单
 *
 * 就地指引(constitution 原则 IV): 变量清单在表单内就地展示, 用户无需翻文档;
 * 精确路径重复时后端返回 warning 文案, 用 message 就地提示(不阻断)。
 */
const RuleFormModal: React.FC<Props> = ({ open, record, projectId, saving, onCancel, onSubmit }) => {
  const [form] = Form.useForm();

  useEffect(() => {
    if (open) {
      if (record) {
        form.setFieldsValue({
          name: record.name,
          method: record.method,
          path: record.path,
          priority: record.priority,
          status_code: record.status_code,
          response_headers: record.response_headers || '',
          response_body: record.response_body || '',
          delay: record.delay,
          status: record.status,
          remark: record.remark || '',
        });
      } else {
        form.resetFields();
        form.setFieldsValue({ method: 'GET', priority: 0, status_code: 200, delay: 0, status: 1 });
      }
    }
  }, [open, record, form]);

  const handleOk = async () => {
    if (!projectId) return;
    const values = await form.validateFields();
    await onSubmit({
      id: record?.id,
      project_id: projectId,
      name: values.name,
      method: values.method,
      path: values.path,
      priority: values.priority,
      status_code: values.status_code,
      response_headers: values.response_headers || undefined,
      response_body: values.response_body || undefined,
      delay: values.delay,
      status: values.status ? 1 : 0,
      remark: values.remark || '',
    });
  };

  return (
    <Modal
      title={record ? '编辑规则' : '新建规则'}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={saving}
      destroyOnHidden
      width={720}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item
          name="name"
          label="规则名"
          rules={[{ required: true, message: '请填写规则名' }]}
        >
          <Input placeholder="如: 用户详情" maxLength={50} />
        </Form.Item>
        <Form.Item
          name="method"
          label="请求方法"
          rules={[{ required: true, message: '请选择请求方法' }]}
        >
          <Select
            options={MOCK_METHODS.map((m) => ({ label: m, value: m }))}
            placeholder="选择方法"
          />
        </Form.Item>
        <Form.Item
          name="path"
          label="接口路径"
          extra={
            <>
              <Text type="secondary">以 / 开头, 支持 <Text code>:id</Text> 参数占位与末尾 <Text code>*</Text> 通配。</Text>
              <br />
              <Text type="secondary">例: <Text code>/api/user/:id</Text> · <Text code>/api/*</Text></Text>
            </>
          }
          rules={[{ required: true, message: '请填写接口路径' }]}
        >
          <Input placeholder="/api/user/:id" maxLength={255} />
        </Form.Item>
        <Form.Item name="status" label="启用" valuePropName="checked">
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>
        <Form.Item name="priority" label="优先级" extra={<Text type="secondary">数字越小越优先; 精确路径 &gt; 参数化 &gt; 通配, 同类型内按此值排序</Text>}>
          <InputNumber min={0} precision={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="delay" label={`模拟延迟(毫秒, 0~${MOCK_MAX_DELAY})`}>
          <InputNumber min={0} max={MOCK_MAX_DELAY} precision={0} style={{ width: '100%' }} placeholder="0" />
        </Form.Item>
        <Form.Item name="status_code" label="响应状态码" rules={[{ required: true, message: '请填写状态码' }]}>
          <InputNumber min={100} max={599} precision={0} style={{ width: '100%' }} placeholder="200" />
        </Form.Item>
        <Form.Item
          name="response_headers"
          label="响应头(JSON 对象)"
          extra={<Text type="secondary">如 <Text code>{'{"Content-Type": "application/json"}'}</Text>, 留空时按响应体形态自动推断</Text>}
        >
          <Input.TextArea rows={2} placeholder='{"Content-Type": "application/json"}' />
        </Form.Item>
        <Form.Item
          name="response_body"
          label="响应体(JSON 或纯文本)"
          extra={
            <>
              <Text type="secondary">支持回显变量(由请求内容决定, 取不到值为空串):</Text>
              <br />
              <Text type="secondary">{MOCK_VARIABLE_HINTS.join(' · ')}</Text>
            </>
          }
        >
          <Input.TextArea rows={6} placeholder='{"code": 0, "data": {"name": "$request.query.name"}}' />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} maxLength={200} placeholder="选填" />
        </Form.Item>
        <Alert
          type="info"
          showIcon
          message="保存即生效"
          description="保存后规则立即参与对外匹配; 未知变量(如 $randomInt / $timestamp)会被拦截。不要在响应中放置真实凭据 —— mock 基地址是半公开入口。"
        />
      </Form>
    </Modal>
  );
};

export default RuleFormModal;
