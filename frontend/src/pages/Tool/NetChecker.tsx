import React, { useState } from 'react';
import { Alert, Button, Input, Space, Table, Tag, Typography } from 'antd';
import { useRequest } from '@umijs/max';
import { ToolLabel, ToolShell } from '@/components/Tool/ToolShell';
import { checkNetTarget, NetCheckResult, toolError } from '@/services/tool';

const { Text } = Typography;

const SAMPLES = [
  '127.0.0.1',
  '192.168.1.1',
  '169.254.169.254',
  '10.0.0.8',
  'example.com',
  'https://api.example.com/v1/users',
  '::1',
];

/**
 * 内网地址判断 —— 复用 UI 自动化出网边界的同一套 SSRF 网段规则。
 *
 * 典型用途: 排查「这个回调地址能不能从平台访问」「这个被测域名是不是指向内网」。
 * 判定结果与执行器一致, 不会出现「工具说可以、执行时被拦」。
 */
const NetChecker: React.FC = () => {
  const [target, setTarget] = useState('');

  const { data, run, loading, error } = useRequest(() => checkNetTarget(target), {
    manual: true,
    formatResult: (res: any) => res,
  });

  const res: NetCheckResult | undefined = data?.code === 0 ? data.data : undefined;
  const errMsg = toolError(data, error);

  const columns = [
    {
      title: 'IP 地址',
      dataIndex: 'ip',
      key: 'ip',
      render: (v: string) => <Text code>{v}</Text>,
    },
    {
      title: '判定',
      dataIndex: 'blocked',
      key: 'blocked',
      width: 140,
      render: (blocked: boolean) =>
        blocked ? <Tag color="red">内网 / 会被拦截</Tag> : <Tag color="green">公网</Tag>,
    },
    {
      title: '命中的网段',
      dataIndex: 'network',
      key: 'network',
      render: (net: string | null, r: { label: string }) => (
        <Space size={8}>
          {net ? <Text code>{net}</Text> : null}
          <Text type="secondary">{r.label}</Text>
        </Space>
      ),
    },
  ];

  const submit = () => {
    if (!target.trim()) return;
    run();
  };

  return (
    <ToolShell
      title="网络地址判断"
      description="解析 IP / 域名 / URL, 判定是否落在内网与保留网段 —— 与 UI 自动化的出网拦截同源"
      extra={
        <Space>
          <Button size="small" onClick={() => setTarget('')} disabled={!target}>
            清空
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Alert
          type="info"
          showIcon
          message="判定规则与 SSRF 拦截完全一致"
          description="这里的网段表就是 UI 自动化执行时用的那一份 —— 工具说「公网」而执行被拦的情况不会出现。域名会做真实 DNS 解析(只发 DNS 查询, 不发 HTTP 请求)。"
        />

        <Space.Compact style={{ width: '100%', maxWidth: 640 }}>
          <Input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            onPressEnter={submit}
            placeholder="IP / 域名 / 完整 URL, 例如 192.168.1.1 或 https://api.example.com/v1"
            style={{ fontFamily: 'monospace' }}
            allowClear
          />
          <Button type="primary" loading={loading} onClick={submit} disabled={!target.trim()}>
            判断
          </Button>
        </Space.Compact>

        <div>
          <ToolLabel>点一下试试</ToolLabel>
          <Space wrap style={{ marginTop: 4 }}>
            {SAMPLES.map((s) => (
              <Tag key={s} color="geekblue" style={{ cursor: 'pointer' }} onClick={() => setTarget(s)}>
                {s}
              </Tag>
            ))}
          </Space>
        </div>

        {errMsg ? <Alert type="error" showIcon message="判断失败" description={errMsg} /> : null}

        {res ? (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space size={16} wrap>
              <Text type="secondary">
                输入: <Text code>{res.target}</Text>
              </Text>
              <Text type="secondary">
                主机: <Text code>{res.host}</Text>
              </Text>
              <Text type="secondary">解析到 {res.total} 个地址</Text>
              {res.blocked ? (
                <Tag color="red">存在内网地址, 平台出网会被拦截</Tag>
              ) : (
                <Tag color="green">全部是公网地址</Tag>
              )}
            </Space>

            {res.blocked ? (
              <Alert
                type="warning"
                showIcon
                message={`被拦截的地址: ${res.blocked_ips.join(', ')}`}
                description="这些地址落在私网 / 环回 / 链路本地 / 保留网段内 —— 云厂商元数据地址 169.254.169.254 尤其危险。"
              />
            ) : null}

            <Table
              rowKey="ip"
              size="small"
              pagination={false}
              dataSource={res.ips}
              columns={columns as any}
            />
          </Space>
        ) : null}
      </Space>
    </ToolShell>
  );
};

export default NetChecker;
