import React, { useEffect, useMemo } from 'react';
import { Form, Input, Modal, Select } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import { UI_SEMANTIC_HINT, UI_STRATEGY_OPTIONS, UI_STRATEGIES } from '@/consts/uiTest';
import { UiElement } from '@/services/uiTest';

export interface ElementModalProps {
  open: boolean;
  /** 编辑时传入, 新建时为 undefined */
  element?: UiElement | null;
  saving?: boolean;
  onCancel: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
}

/**
 * 元素编辑弹窗
 *
 * 元素 = 一条定位策略(策略 + 定位值 + 可选的 accessible name)。
 * `role` 策略之外不允许填可访问名称 —— 与后端 `UIElementForm` 的校验保持一致。
 */
const ElementModal: React.FC<ElementModalProps> = (props) => {
  const { open, element, saving, onCancel, onSubmit } = props;
  const [form] = Form.useForm();
  const strategy = Form.useWatch('strategy', form);

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      name: element?.name,
      strategy: element?.strategy || 'role',
      locator: element?.locator,
      name_attr: element?.name_attr,
      description: element?.description,
    });
  }, [open, element, form]);

  // 切换策略时清掉不适用的字段 —— role 之外不填可访问名称
  useEffect(() => {
    if (strategy && strategy !== 'role') {
      form.setFieldValue('name_attr', undefined);
    }
  }, [strategy, form]);

  const strategyHint = useMemo(
    () => (strategy && UI_STRATEGIES[strategy]?.semantic ? UI_SEMANTIC_HINT : ''),
    [strategy]
  );

  return (
    <Modal
      open={open}
      title={element?.id ? '编辑元素' : '新建元素'}
      onCancel={onCancel}
      onOk={() => form.submit()}
      confirmLoading={saving}
      destroyOnHidden
      width={560}
    >
      <Form form={form} layout="vertical" onFinish={onSubmit} preserve={false}>
        <Form.Item name="name" label="元素名" rules={[{ required: true, message: '请输入元素名' }]}>
          <Input placeholder="例如 登录按钮" maxLength={64} />
        </Form.Item>
        <Form.Item name="strategy" label="定位策略" rules={[{ required: true, message: '请选择定位策略' }]}>
          <Select options={UI_STRATEGY_OPTIONS} placeholder="选择定位策略" />
        </Form.Item>
        <Form.Item
          name="locator"
          label="定位值"
          rules={[{ required: true, message: '请输入定位值' }]}
          extra={
            strategyHint ? (
              <span style={{ color: '#52c41a' }}>
                <InfoCircleOutlined /> {strategyHint}
              </span>
            ) : (
              'CSS / XPath 抗改版能力弱, 页面一改就要回来改这里'
            )
          }
        >
          <Input placeholder="例如 登录 / button / #login-btn" maxLength={256} />
        </Form.Item>
        {strategy === 'role' ? (
          <Form.Item name="name_attr" label="可访问名称">
            <Input placeholder="例如 登录(可留空, 留空则只按 role 定位)" maxLength={64} />
          </Form.Item>
        ) : null}
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={255} placeholder="选填" />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default ElementModal;
