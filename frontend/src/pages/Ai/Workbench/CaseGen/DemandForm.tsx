import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Form, Input, Select, Space, Typography } from 'antd';
import { FolderAddOutlined } from '@ant-design/icons';
import { history } from '@umijs/max';
import { AiVendorModels } from '@/services/aiWorkbench';
import {
  AI_TEST_TYPE_OPTIONS,
  AI_SOURCE_TYPES,
  AI_THIRD_PARTY_MODEL_NOTICE,
} from '@/consts/aiWorkbench';

const { Text } = Typography;

export interface Option {
  label: string;
  value: number;
}

export interface DemandFormValues {
  title: string;
  test_type: string;
  source_type: string;
  content: string;
  vendor_id?: number;
  model_id?: number;
  directory_id: number;
  source_name?: string;
}

export interface DemandFormProps {
  projectOptions: Option[];
  projectId?: number;
  directoryOptions: Option[];
  directoryId?: number;
  models: AiVendorModels[];
  /** 元素库里的启用元素数 —— G4 用 */
  elementCount?: number;
  /** 文档解析出来的正文 —— nonce 变化时填进「需求正文」 */
  fillContent?: { content: string; nonce: number } | null;
  loading: boolean;
  onProjectChange: (projectId: number) => void;
  onDirectoryChange: (directoryId: number) => void;
  onCreateDirectory: () => void;
  onSubmit: (values: DemandFormValues) => void;
}

/**
 * 需求输入表单(生成工作台的左半边)
 *
 * **就地指引点 G1~G4**(constitution 原则 IV)——
 * 前置条件缺失时必须**在当前界面内**给出可操作指引, 不能只报错误码:
 * - G1 没有可用的对话模型 → 顶部提示条 + 跳转「模型服务商」, 并禁用提交
 * - G2 项目下没有目录 → 目录选择器旁的「新建目录」入口
 * - G4 Web UI 用例但元素库为空 → 表单内提示 + 跳转元素库
 * - G3 未配置对象存储 → 在 DocumentUpload 里提示(不阻断)
 */
const DemandForm: React.FC<DemandFormProps> = ({
  projectOptions,
  projectId,
  directoryOptions,
  directoryId,
  models,
  elementCount,
  fillContent,
  loading,
  onProjectChange,
  onDirectoryChange,
  onCreateDirectory,
  onSubmit,
}) => {
  const [form] = Form.useForm<DemandFormValues>();
  const [vendorId, setVendorId] = useState<number | undefined>();
  const [modelId, setModelId] = useState<number | undefined>();
  const testType = Form.useWatch('test_type', form);

  // 文档解析出来的正文 —— 填进「需求正文」
  useEffect(() => {
    if (fillContent?.content) {
      form.setFieldsValue({ content: fillContent.content });
    }
  }, [fillContent, form]);

  const modelOptions = useMemo(() => {
    const vendor = models.find((item) => item.vendor_id === vendorId);
    return (vendor?.models || []).map((item) => ({
      label: item.model_name,
      value: item.model_id,
    }));
  }, [models, vendorId]);

  // **G1** —— 没有可用的对话模型就禁掉提交, 别让用户提交后才发现
  const noModel = models.length === 0;
  const noDirectory = directoryOptions.length === 0;
  // **G4** —— Web UI 用例要引用元素库里的元素, 元素库为空就生成不出能用的步骤
  const emptyElementLibrary = testType === 'web' && (elementCount || 0) === 0;
  const thirdParty = models.some((item) => item.vendor_code !== 'ollama');

  return (
    <Card variant="borderless" title="需求输入">
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
              配置或启用一个对话模型后才能生成用例。
            </span>
          }
        />
      ) : null}

      <Form
        form={form}
        layout="vertical"
        onFinish={onSubmit}
        initialValues={{ test_type: 'api', source_type: 'text' }}
      >
        <Form.Item label="所属项目" required>
          <Select
            placeholder="选择项目"
            value={projectId}
            options={projectOptions}
            onChange={(value) => {
              onProjectChange(value);
              onDirectoryChange(undefined as unknown as number);
            }}
          />
        </Form.Item>

        {/* **G2** —— 项目下没有目录时, 就地给「新建目录」入口 */}
        <Form.Item label="目标目录" required>
          <Space.Compact style={{ width: '100%' }}>
            <Select
              style={{ flex: 1 }}
              placeholder={noDirectory ? '该项目下还没有目录' : '选择采纳后的用例目录'}
              value={directoryId}
              options={directoryOptions}
              onChange={onDirectoryChange}
              disabled={noDirectory}
            />
            <Button
              icon={<FolderAddOutlined />}
              disabled={!projectId}
              onClick={onCreateDirectory}
              title="新建目录"
            />
          </Space.Compact>
          {noDirectory && projectId ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 8 }}
              message="该项目下还没有目录"
              description={
                <a onClick={onCreateDirectory}>点右侧按钮就地新建目录, 建完即选中</a>
              }
            />
          ) : null}
        </Form.Item>

        <Form.Item
          label="任务标题"
          name="title"
          rules={[{ required: true, message: '请填写任务标题' }, { max: 64, message: '不超过 64 个字符' }]}
        >
          <Input placeholder="例如: 登录模块用例生成" />
        </Form.Item>

        <Form.Item label="测试类型" name="test_type">
          <Select options={AI_TEST_TYPE_OPTIONS} />
        </Form.Item>

        {/* **G4** —— Web UI 用例要引用元素库里的元素 */}
        {emptyElementLibrary ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Web UI 用例需引用元素库中已沉淀的元素, 元素库为空"
            description={
              <span>
                去
                <a onClick={() => history.push('/ui/element')}>元素库</a>
                先建页面与元素, 否则生成的步骤无法定位。
              </span>
            }
          />
        ) : null}

        <Form.Item label="使用模型" required>
          <Space.Compact style={{ width: '100%' }}>
            <Select
              style={{ flex: 1 }}
              placeholder="选择厂商"
              value={vendorId}
              disabled={noModel}
              options={models.map((item) => ({ label: item.vendor_name, value: item.vendor_id }))}
              onChange={(value) => {
                setVendorId(value);
                setModelId(undefined);
                form.setFieldsValue({ vendor_id: value, model_id: undefined });
              }}
            />
            <Select
              style={{ flex: 1 }}
              placeholder="选择模型"
              value={modelId}
              disabled={!vendorId}
              options={modelOptions}
              onChange={(value) => {
                setModelId(value);
                form.setFieldsValue({ model_id: value });
              }}
            />
          </Space.Compact>
        </Form.Item>

        {thirdParty ? (
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
            {AI_THIRD_PARTY_MODEL_NOTICE}
          </Text>
        ) : null}

        <Form.Item label="来源" name="source_type">
          <Select
            options={AI_SOURCE_TYPES.map((item) => ({
              label: item === 'text' ? '文本输入' : '需求文档',
              value: item,
            }))}
          />
        </Form.Item>

        <Form.Item
          label="需求正文"
          name="content"
          rules={[{ required: true, message: '请粘贴需求正文或上传需求文档' }]}
        >
          <Input.TextArea rows={10} placeholder="把需求正文粘贴到这里" />
        </Form.Item>

        <Form.Item hidden name="vendor_id">
          <Input />
        </Form.Item>
        <Form.Item hidden name="model_id">
          <Input />
        </Form.Item>
        <Form.Item hidden name="directory_id">
          <Input />
        </Form.Item>

        <Button
          type="primary"
          block
          htmlType="submit"
          loading={loading}
          disabled={noModel || !projectId || !directoryId}
        >
          开始生成用例
        </Button>
        {noModel || !projectId || !directoryId ? (
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
            {noModel ? '缺少可用的对话模型' : !projectId ? '请先选择项目' : '请先选择目标目录'}
          </Text>
        ) : null}
      </Form>
    </Card>
  );
};

export default DemandForm;
