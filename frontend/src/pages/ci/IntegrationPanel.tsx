import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { CopyOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { history } from 'umi';
import { useModel } from '@umijs/max';
import {
  CiIntegration,
  CiIntegrationForm,
  deleteCiIntegration,
  insertCiIntegration,
  switchCiIntegration,
} from '@/services/ci';
import { CI_INTEGRATION_NAME_MAX_LEN } from '@/consts/ci';

const { Text, Paragraph } = Typography;

type ExpireMode = 'default' | 'never' | 'custom';

/**
 * 集成配置面板 —— 凭据的签发 / 启停 / 删除(spec US1)
 *
 * **明文只出现一次(FR-002 / SC-007)**: 签发成功后把 token 交给 model 的
 * `justIssuedToken`, 弹窗关闭即 `discardIssuedToken()` 清空; 列表接口的响应里
 * 本来就没有明文, 所以刷新也拿不回来。
 *
 * **G2 / G3 就地指引**: 项目下没有集成配置 → 给「新建集成」; 没有测试计划 →
 * 给「去创建测试计划」入口(没有计划即使签了凭据也无从触发, 故 G3 排在 G2 前面)。
 */
const IntegrationPanel: React.FC<{ onIssued?: () => void }> = ({ onIssued }) => {
  const {
    projectId,
    integrations,
    integrationTotal,
    integrationLoading,
    page,
    size,
    fetchIntegrations,
    plans,
    justIssuedToken,
    justIssuedId,
    rememberIssuedToken,
    discardIssuedToken,
  } = useModel('ci');

  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [expireMode, setExpireMode] = useState<ExpireMode>('default');
  const [form] = Form.useForm<CiIntegrationForm & { expires_mode?: ExpireMode;
    custom_expires?: string }>();

  useEffect(() => {
    if (projectId) fetchIntegrations(projectId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const reload = useCallback(() => {
    if (projectId) fetchIntegrations(projectId);
  }, [projectId, fetchIntegrations]);

  const openCreate = () => {
    form.resetFields();
    setExpireMode('default');
    setCreateOpen(true);
  };

  const submitCreate = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      const payload: CiIntegrationForm = {
        project_id: projectId as number,
        name: values.name,
        plan_id: values.plan_id ?? null,
        callback_url: values.callback_url || null,
      };
      // **三态(决定 Q4)** —— pydantic 下「不传」与「传 null」都落成 None,
      // 后端靠 `__fields_set__` 区分, 所以这里必须真的不带这个键
      if (expireMode === 'never') {
        payload.expires_at = null;
      } else if (expireMode === 'custom') {
        payload.expires_at = values.custom_expires || null;
      }
      const res: any = await insertCiIntegration(payload);
      if (res?.code === 0) {
        message.success('凭据已签发，请立即复制（关闭后无法再查看）');
        setCreateOpen(false);
        rememberIssuedToken(res.data?.token ?? '', res.data?.id ?? 0);
        reload();
        onIssued?.();
      } else {
        message.error(res?.msg || '签发失败');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const toggleEnabled = async (record: CiIntegration, enabled: boolean) => {
    const res: any = await switchCiIntegration(record.id, enabled);
    if (res?.code === 0) {
      message.success(enabled ? '已启用' : '已停用，该凭据立即失效');
      reload();
    } else {
      message.error(res?.msg || '操作失败');
    }
  };

  const remove = async (record: CiIntegration) => {
    const res: any = await deleteCiIntegration(record.id);
    if (res?.code === 0) {
      message.success('已删除');
      reload();
    } else {
      message.error(res?.msg || '删除失败');
    }
  };

  const copyToken = async () => {
    if (!justIssuedToken) return;
    try {
      await navigator.clipboard.writeText(justIssuedToken);
      message.success('凭据已复制到剪贴板');
    } catch {
      message.warning('复制失败，请手动选中上方文本复制');
    }
  };

  const columns = [
    {
      title: '集成名',
      dataIndex: 'name',
      key: 'name',
      render: (v: string, r: CiIntegration) => (
        <Space>
          <Text strong>{v}</Text>
          {r.enabled ? <Tag color="green">启用</Tag> : <Tag>已停用</Tag>}
        </Space>
      ),
    },
    {
      title: '凭据前缀',
      dataIndex: 'token_prefix',
      key: 'token_prefix',
      render: (v: string) => <Text code>{v}…</Text>,
    },
    {
      title: '默认计划',
      dataIndex: 'plan_id',
      key: 'plan_id',
      render: (v: number | null) => {
        if (!v) return <Text type="secondary">未绑定（触发时须显式指定）</Text>;
        const hit = plans.find((p) => p.id === v);
        return hit ? hit.name : `#${v}`;
      },
    },
    {
      title: '有效期',
      dataIndex: 'expires_at',
      key: 'expires_at',
      render: (v: string | null) =>
        v ? v : <Tag color="blue">长期有效</Tag>,
    },
    {
      title: '最后使用',
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      render: (v: string | null) =>
        v ? v : <Text type="secondary">从未使用</Text>,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: CiIntegration) => (
        <Space>
          <Switch
            size="small"
            checked={record.enabled}
            onChange={(checked) => toggleEnabled(record, checked)}
          />
          <Popconfirm
            title="删除该凭据？"
            description="删除后外部流水线会立即无法调用；已有的触发记录会保留。"
            onConfirm={() => remove(record)}
          >
            <Button type="link" danger size="small">
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* G3 是硬前置 —— 没有计划即使签了凭据也无从触发, 所以排在 G2 前面 */}
      {plans.length === 0 && (
        <Alert
          showIcon
          type="warning"
          style={{ marginBottom: 16 }}
          message="本项目还没有测试计划"
          description={
            <span>
              接入 CI 必须有可触发的测试计划。请先
              <Button
                type="link"
                size="small"
                onClick={() => history.push('/apiTest/testplan')}
              >
                去创建测试计划
              </Button>
              再回来签发凭据。
            </span>
          }
        />
      )}

      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建集成
        </Button>
        <Button icon={<ReloadOutlined />} onClick={reload}>
          刷新
        </Button>
        <Text type="secondary">
          凭据明文只在签发成功时展示一次，列表里只有前缀。
        </Text>
      </Space>

      {integrations.length === 0 && !integrationLoading && (
        <Alert
          showIcon
          type="info"
          style={{ marginBottom: 16 }}
          message="本项目还没有接入凭据"
          description="点击「新建集成」生成一条长期凭据，再复制接入示例到你的流水线里即可开始触发测试。"
        />
      )}

      <Table<CiIntegration>
        rowKey="id"
        size="middle"
        loading={integrationLoading}
        columns={columns}
        dataSource={integrations}
        pagination={{
          current: page,
          pageSize: size,
          total: integrationTotal,
          showSizeChanger: true,
          onChange: (p, s) => fetchIntegrations(projectId, p, s),
        }}
      />

      {/* 签发表单 */}
      <Modal
        title="新建集成（签发凭据）"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={submitCreate}
        confirmLoading={submitting}
        okText="签发"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="集成名"
            rules={[
              { required: true, message: '请填写集成名' },
              {
                max: CI_INTEGRATION_NAME_MAX_LEN,
                message: `不能超过 ${CI_INTEGRATION_NAME_MAX_LEN} 个字符`,
              },
            ]}
          >
            <Input placeholder="例如 Jenkins-main" />
          </Form.Item>

          <Form.Item name="plan_id" label="绑定默认计划（可选）">
            <Select
              allowClear
              placeholder="绑定后，触发时可省略 plan_id"
              options={plans.map((p) => ({ label: p.name, value: p.id }))}
              disabled={plans.length === 0}
            />
          </Form.Item>

          <Form.Item name="expire_mode" label="有效期" initialValue="default">
            <Select
              value={expireMode}
              onChange={(v: ExpireMode) => setExpireMode(v)}
              options={[
                { label: '默认 1 年', value: 'default' },
                { label: '长期有效（永不过期）', value: 'never' },
                { label: '自定义', value: 'custom' },
              ]}
            />
          </Form.Item>

          {expireMode === 'custom' && (
            <Form.Item
              name="custom_expires"
              label="到期时间"
              rules={[{ required: true, message: '请填写到期时间' }]}
            >
              <Input placeholder="2027-11-23 18:00:00" />
            </Form.Item>
          )}

          <Form.Item
            name="callback_url"
            label="回调地址（一期只保存，不会发送）"
            extra="结果目前通过「等待返回」或「轮询」获取；主动回调在二期提供。"
          >
            <Input placeholder="https://jenkins.example.com/..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* 一次性明文 —— 关闭即丢弃 */}
      <Modal
        title="请立即复制凭据"
        open={!!justIssuedToken}
        onCancel={discardIssuedToken}
        onOk={discardIssuedToken}
        okText="我已复制，关闭"
        cancelButtonProps={{ style: { display: 'none' } }}
        width={640}
      >
        <Alert
          showIcon
          type="warning"
          message="这是唯一一次能看到完整凭据的机会"
          description="关闭本弹窗后，平台只会显示前缀，无法再查看明文。请把它存进流水线的凭据管理（Jenkins Credentials / GitHub Secrets），不要提交进代码仓库。"
          style={{ marginBottom: 12 }}
        />
        <div className="ci-token-box">
          <Paragraph copyable={{ text: justIssuedToken || '' }} style={{ marginBottom: 0 }}>
            {justIssuedToken}
          </Paragraph>
        </div>
        <Button type="primary" icon={<CopyOutlined />} block onClick={copyToken}>
          复制凭据
        </Button>
        {justIssuedId ? (
          <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
            集成 ID：{justIssuedId}
          </Text>
        ) : null}
      </Modal>
    </div>
  );
};

export default IntegrationPanel;
