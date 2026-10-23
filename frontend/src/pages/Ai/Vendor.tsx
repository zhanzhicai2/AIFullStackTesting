import React, { useEffect, useState } from 'react';
import { PageContainer } from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Form,
  Input,
  Popconfirm,
  Row,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  ExportOutlined,
  PlusOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useModel } from '@umijs/max';
import NoRecord from '@/components/NotFound/NoRecord';
import { modelTypeColor, modelTypeLabel } from '@/consts/ai';
import FetchModelModal from './FetchModelModal';
import ModelFormModal from './ModelFormModal';
import VendorLogo from './VendorLogo';
import { ModelSource } from '@/models/ai';
import { AIModel, AIVendorItem } from '@/services/ai';
import './index.less';

const Vendor: React.FC = () => {
  const {
    vendors,
    current,
    models,
    loading,
    saving,
    authorized,
    fetchVendors,
    selectVendor,
    saveVendor,
    saveModel,
    toggleModel,
    removeModel,
    fetchRemote,
    fetchSystemModels,
    importModels,
  } = useModel('ai');

  const [form] = Form.useForm();
  // 监听 enable,否则厂商级「已启用/未启用」文字不会跟着开关重渲染
  const enable = Form.useWatch('enable', form);

  const [systemOpen, setSystemOpen] = useState(false);
  const [fetchOpen, setFetchOpen] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [candidates, setCandidates] = useState<{ name: string; model_type: string }[]>([]);
  const [existed, setExisted] = useState<string[]>([]);
  const [importSource, setImportSource] = useState<number>(ModelSource.remote);
  const [modelModal, setModelModal] = useState<{ open: boolean; record: AIModel | null }>({
    open: false,
    record: null,
  });

  useEffect(() => {
    fetchVendors().then((list: AIVendorItem[]) => {
      if (list?.length) selectVendor(list[0]);
    });
  }, []);

  // 切换厂商时回填表单
  useEffect(() => {
    if (!current) return;
    form.setFieldsValue({
      en_name: current.en_name,
      api_key: current.api_key,
      base_url: current.base_url,
      console_url: current.console_url,
      enable: current.enable,
    });
  }, [current, form]);

  const onSave = async () => {
    if (!current) return;
    const values = await form.validateFields();
    await saveVendor({ id: current.id, ...values });
  };

  const onFetchModels = async () => {
    if (!current) return;
    setFetching(true);
    const res = await fetchRemote(current.id);
    setFetching(false);
    if (!res) return;
    setCandidates(res.models);
    setExisted(res.existed);
    setImportSource(ModelSource.remote);
    setFetchOpen(true);
  };

  const onOpenSystemModels = async () => {
    if (!current) return;
    const res = await fetchSystemModels(current.code);
    if (!res) return;
    setCandidates(res.models);
    setExisted(res.existed);
    setImportSource(ModelSource.system);
    setSystemOpen(true);
  };

  const onImport = async (names: string[], types: Record<string, string>) => {
    if (!current) return;
    const ok = await importModels(current.id, importSource, names, types);
    if (ok) {
      setFetchOpen(false);
      setSystemOpen(false);
    }
  };

  if (authorized === false) {
    return (
      <PageContainer title="模型服务商" breadcrumbRender={false}>
        <NoRecord height={400} desc="对不起，只有超级管理员可以配置模型服务商" />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title="模型服务商"
      breadcrumbRender={false}
      extra={[
        <Button
          key="system"
          icon={<SettingOutlined />}
          disabled={!current}
          onClick={onOpenSystemModels}
        >
          系统模型
        </Button>,
      ]}
    >
      <Card styles={{ body: { padding: 0 } }}>
        <Row gutter={0}>
          {/* ---------- 左:厂商列表 ---------- */}
          <Col span={6} className="ai-vendor-left">
            <Spin spinning={loading}>
              {vendors.length === 0 && !loading ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无厂商" style={{ marginTop: 60 }} />
              ) : (
                vendors.map((item) => {
                  const v = item.vendor;
                  const active = current?.id === v.id;
                  return (
                    <div
                      key={v.id}
                      className={`ai-vendor-item${active ? ' active' : ''}`}
                      onClick={() => selectVendor(item)}
                    >
                      <VendorLogo code={v.code} name={v.name} />
                      <div className="ai-vendor-meta">
                        <div className="ai-vendor-name">{v.name}</div>
                        <div className="ai-vendor-state">
                          <span
                            className={`dot ${v.enable ? 'on' : ''}`}
                          />
                          {v.enable ? '已启用' : '未启用'}
                        </div>
                      </div>
                      <Switch
                        size="small"
                        checked={v.enable}
                        onClick={(checked, e) => {
                          // 阻止冒泡,避免点开关时同时切换选中项
                          e.stopPropagation();
                          saveVendor({
                            id: v.id,
                            en_name: v.en_name,
                            api_key: v.api_key,
                            base_url: v.base_url,
                            console_url: v.console_url,
                            enable: checked,
                          });
                        }}
                      />
                    </div>
                  );
                })
              )}
            </Spin>
          </Col>

          {/* ---------- 右:厂商配置 ---------- */}
          <Col span={18} className="ai-vendor-right">
            {!current ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请在左侧选择一个模型厂商" />
            ) : (
              <>
                <div className="ai-vendor-header">
                  <div>
                    <Typography.Title level={4} style={{ margin: 0 }}>
                      {current.name}
                    </Typography.Title>
                    <Typography.Text type="secondary">{current.en_name || ' '}</Typography.Text>
                  </div>
                  <Space size={12}>
                    <Typography.Text type={enable ? 'success' : 'secondary'}>
                      {enable ? '已启用' : '未启用'}
                    </Typography.Text>
                    <Form.Item name="enable" valuePropName="checked" noStyle>
                      <Switch />
                    </Form.Item>
                    <Button
                      type="primary"
                      icon={<SettingOutlined />}
                      loading={saving}
                      onClick={onSave}
                    >
                      保存配置
                    </Button>
                  </Space>
                </div>

                <Form form={form} layout="vertical" className="ai-vendor-form">
                  <Form.Item name="api_key" label="API Key">
                    <Input
                      placeholder={current.has_key ? '请输入新的 API Key' : '请输入 API Key'}
                    />
                    {current.console_url && (
                      <div className="ai-form-extra">
                        获取地址:{' '}
                        <a href={current.console_url} target="_blank" rel="noreferrer noopener">
                          {current.console_url} <ExportOutlined />
                        </a>
                      </div>
                    )}
                  </Form.Item>
                  <Form.Item name="base_url" label="Base URL">
                    <Input placeholder="https://api.deepseek.com/v1" />
                  </Form.Item>
                </Form>

                <Divider />

                {/* ---------- 模型列表 ---------- */}
                <div className="ai-model-toolbar">
                  <Space>
                    <Typography.Text strong>模型列表</Typography.Text>
                    <Typography.Text type="secondary">共 {models.length} 个</Typography.Text>
                  </Space>
                  <Space>
                    <Button
                      icon={<ThunderboltOutlined />}
                      loading={fetching}
                      onClick={onFetchModels}
                      disabled={!current.has_key}
                    >
                      获取系统模型
                    </Button>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setModelModal({ open: true, record: null })}
                    >
                      自定义
                    </Button>
                  </Space>
                </div>

                {!current.has_key && (
                  <Alert
                    type="info"
                    showIcon
                    banner
                    style={{ marginBottom: 12 }}
                    message="请先填写 API Key 并保存配置，才能从厂商接口拉取模型列表。你仍可使用「自定义」手动添加模型。"
                  />
                )}

                <Spin spinning={loading}>
                  {models.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="还没有添加模型，点击右上角获取或自定义"
                      style={{ marginTop: 40 }}
                    />
                  ) : (
                    models.map((m) => (
                      <div className="ai-model-item" key={m.id}>
                        <div className="ai-model-name">
                          <Typography.Text ellipsis={{ tooltip: m.name }} copyable>
                            {m.name}
                          </Typography.Text>
                          <Tag color={modelTypeColor(m.model_type)} style={{ marginLeft: 8 }}>
                            {modelTypeLabel(m.model_type)}
                          </Tag>
                        </div>
                        <Space size={8}>
                          <Typography.Text
                            type={m.enable ? 'success' : 'secondary'}
                            style={{ fontSize: 12 }}
                          >
                            {m.enable ? '已启用' : '已禁用'}
                          </Typography.Text>
                          <Switch
                            size="small"
                            checked={m.enable}
                            onChange={(checked) => toggleModel(m, checked)}
                          />
                          <Button
                            type="text"
                            size="small"
                            icon={<SettingOutlined />}
                            title="模型参数设置"
                            onClick={() => setModelModal({ open: true, record: m })}
                          />
                          <Popconfirm
                            title={`确定要删除模型 ${m.name} 吗?`}
                            onConfirm={() => removeModel(m.id)}
                          >
                            <Button
                              type="text"
                              size="small"
                              icon={<DeleteOutlined />}
                              title="删除模型"
                            />
                          </Popconfirm>
                        </Space>
                      </div>
                    ))
                  )}
                </Spin>
              </>
            )}
          </Col>
        </Row>
      </Card>

      <FetchModelModal
        open={fetchOpen}
        loading={fetching}
        models={candidates}
        existed={existed}
        title="从厂商接口获取模型"
        onCancel={() => setFetchOpen(false)}
        onOk={onImport}
      />
      <FetchModelModal
        open={systemOpen}
        models={candidates}
        existed={existed}
        title="选择系统预置模型"
        onCancel={() => setSystemOpen(false)}
        onOk={onImport}
      />
      <ModelFormModal
        open={modelModal.open}
        record={modelModal.record}
        onCancel={() => setModelModal({ open: false, record: null })}
        onOk={async (payload) => {
          const ok = await saveModel(payload);
          if (ok) setModelModal({ open: false, record: null });
        }}
      />
    </PageContainer>
  );
};

export default Vendor;