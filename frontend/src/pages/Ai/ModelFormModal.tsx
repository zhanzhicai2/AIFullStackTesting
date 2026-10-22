import React, { useEffect } from 'react';
import { Form, Input, InputNumber, Modal, Select, message } from 'antd';
import { DEFAULT_MODEL_PARAMS, MODEL_TYPES } from '@/consts/ai';
import { AIModel } from '@/services/ai';

interface Props {
  open: boolean;
  /** 传入 record 为编辑(齿轮),不传为新增(+ 自定义) */
  record?: AIModel | null;
  onCancel: () => void;
  onOk: (payload: Record<string, unknown>) => void;
}

const parseParams = (raw?: string): Record<string, number> => {
  if (!raw) return { ...DEFAULT_MODEL_PARAMS };
  try {
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_MODEL_PARAMS, ...(typeof parsed === 'object' ? parsed : {}) };
  } catch {
    // 历史脏数据不让整个弹窗打不开
    return { ...DEFAULT_MODEL_PARAMS };
  }
};

const ModelFormModal: React.FC<Props> = ({ open, record, onCancel, onOk }) => {
  const [form] = Form.useForm();
  const isEdit = Boolean(record?.id);

  useEffect(() => {
    if (!open) return;
    if (record) {
      const params = parseParams(record.params);
      form.setFieldsValue({
        name: record.name,
        model_type: record.model_type,
        temperature: params.temperature,
        max_tokens: params.max_tokens,
        top_p: params.top_p,
      });
    } else {
      form.setFieldsValue({
        model_type: 'chat',
        ...DEFAULT_MODEL_PARAMS,
      });
    }
  }, [open, record, form]);

  const onSubmit = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      message.info('有必填字段未填写，请检查');
      return;
    }
    const params = JSON.stringify({
      temperature: values.temperature,
      max_tokens: values.max_tokens,
      top_p: values.top_p,
    });
    onOk({
      id: record?.id,
      vendor_id: record?.vendor_id,
      name: values.name,
      model_type: values.model_type,
      enable: record?.enable ?? false,
      params,
    });
  };

  return (
    <Modal
      open={open}
      title={isEdit ? `模型参数设置 - ${record?.name}` : '自定义添加模型'}
      onCancel={onCancel}
      onOk={onSubmit}
      destroyOnClose
      width={520}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="name"
          label="模型名称"
          rules={[
            { required: true, message: '请输入模型名称' },
            {
              // 手动加模型时不校验格式,厂商自定义模型名规则差异太大
              validator: (_, value) =>
                value && String(value).trim() ? Promise.resolve() : Promise.reject(new Error('请输入模型名称')),
            },
          ]}
        >
          <Input placeholder="例如 deepseek-chat" />
        </Form.Item>
        <Form.Item name="model_type" label="模型类型" rules={[{ required: true, message: '请选择模型类型' }]}>
          <Select options={MODEL_TYPES} />
        </Form.Item>
        <Form.Item name="temperature" label="temperature">
          <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="max_tokens" label="max_tokens">
          <InputNumber min={1} step={128} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="top_p" label="top_p">
          <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default ModelFormModal;