import React, { useEffect, useState } from 'react';
import { Alert, Button, Input, Modal, Select, Space, Spin, Typography } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { listChatModels } from '@/services/chat';
import { AiParseResult, DataFactoryColumn } from '@/services/datafactory';

const { TextArea } = Input;

interface Props {
  open: boolean;
  onCancel: () => void;
  onConfirm: (columns: DataFactoryColumn[], count: number) => void;
}

interface VendorOption {
  vendor_id: number;
  vendor_name: string;
  models: { model_id: number; model_name: string }[];
}

/**
 * 自然语言 -> 字段规则。
 * AI 只负责把口语需求翻译成规则, 真正的数据生成仍然由后端的确定性内核完成。
 */
const AiParseModal: React.FC<Props> = ({ open, onCancel, onConfirm }) => {
  const { aiParse, parsing } = useModel('datafactory');
  const [prompt, setPrompt] = useState('');
  const [vendors, setVendors] = useState<VendorOption[]>([]);
  const [vendorId, setVendorId] = useState<number | undefined>();
  const [modelId, setModelId] = useState<number | undefined>();
  const [result, setResult] = useState<AiParseResult | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) {
      setPrompt('');
      setResult(null);
      setError('');
      return;
    }
    listChatModels()
      .then((res: any) => {
        if (res?.code !== 0) {
          setError(res?.msg || '加载可用模型失败');
          return;
        }
        const list = (res.data || []) as VendorOption[];
        setVendors(list);
        if (list.length > 0) {
          setVendorId(list[0].vendor_id);
          setModelId(list[0].models?.[0]?.model_id);
        } else {
          setError('还没有可用的对话模型, 请先到「模型服务商」里配置并启用');
        }
      })
      .catch(() => setError('加载可用模型失败'));
  }, [open]);

  const currentVendor = vendors.find((v) => v.vendor_id === vendorId);

  const onParse = async () => {
    if (!prompt.trim()) {
      setError('请先描述你要生成的数据');
      return;
    }
    if (!vendorId || !modelId) {
      setError('请先选择模型');
      return;
    }
    setError('');
    const data = await aiParse({ prompt, vendor_id: vendorId, model_id: modelId });
    if (data) {
      setResult(data);
    }
  };

  const apply = () => {
    if (result) {
      onConfirm(result.rules.columns, result.rules.count);
    }
  };

  return (
    <Modal
      open={open}
      title="AI 生成字段规则"
      width={720}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          取消
        </Button>,
        <Button key="parse" onClick={onParse} loading={parsing}>
          <ThunderboltOutlined /> 解析
        </Button>,
        <Button key="apply" type="primary" disabled={!result || result.rules.columns.length === 0} onClick={apply}>
          应用到字段规则
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Alert
          type="info"
          showIcon
          message="AI 只把自然语言翻译成字段规则, 数据本身由后端的确定性内核生成, 同样的规则永远得到同样的数据"
        />
        <Space>
          <span style={{ width: 40 }}>模型</span>
          <Select
            style={{ width: 200 }}
            placeholder="厂商"
            value={vendorId}
            onChange={(v) => {
              setVendorId(v);
              const vendor = vendors.find((x) => x.vendor_id === v);
              setModelId(vendor?.models?.[0]?.model_id);
            }}
            options={vendors.map((v) => ({ label: v.vendor_name, value: v.vendor_id }))}
          />
          <Select
            style={{ width: 260 }}
            placeholder="模型"
            value={modelId}
            onChange={setModelId}
            options={(currentVendor?.models || []).map((m) => ({
              label: m.model_name,
              value: m.model_id,
            }))}
          />
        </Space>
        <TextArea
          rows={4}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="例如: 生成 100 个测试用户, 手机号 138 开头, 邮箱是 qq 域名, 昵称随机中文名"
        />
        {error && <Typography.Text type="danger">{error}</Typography.Text>}
        {parsing && (
          <Space>
            <Spin size="small" />
            <span>AI 正在翻译规则...</span>
          </Space>
        )}
        {result && (
          <div>
            {result.warnings?.length > 0 && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 8 }}
                message="部分字段被忽略"
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {result.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                }
              />
            )}
            <Alert
              type="success"
              showIcon
              message={`解析出 ${result.rules.columns.length} 个字段, 默认生成 ${result.rules.count} 条`}
            />
          </div>
        )}
      </Space>
    </Modal>
  );
};

export default AiParseModal;
