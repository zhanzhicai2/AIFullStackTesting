import React, { useState } from 'react';
import { Alert, Button, Checkbox, Input, Space, Statistic, Typography } from 'antd';
import { useRequest } from '@umijs/max';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import { computeHash, HashResult, toolError } from '@/services/tool';

const { Text } = Typography;

const ALGORITHMS = [
  { value: 'md5', label: 'MD5', note: '128 位 —— 接口签名最常用, 不可用于安全场景' },
  { value: 'sha1', label: 'SHA1', note: '160 位 —— 已被攻破, 仅用于兼容旧系统' },
  { value: 'sha256', label: 'SHA256', note: '256 位 —— 当前主流' },
  { value: 'sha512', label: 'SHA512', note: '512 位 —— 长文本时比 SHA256 更快' },
];

/**
 * 摘要 / HMAC 计算。
 *
 * **走后端而不是前端** —— `crypto.subtle` 在 http 非安全上下文下不可用,
 * 而 Web Crypto 本来就没有 MD5。理由详见后端 `routers/tool/crypto.py`。
 */
const HashTool: React.FC = () => {
  const [text, setText] = useState('');
  const [key, setKey] = useState('');
  const [selected, setSelected] = useState<string[]>(['md5', 'sha256']);

  const { data, run, loading, error } = useRequest(
    () => computeHash(text, key, selected.length ? selected : undefined),
    {
      manual: true,
      formatResult: (res: any) => res,
    },
  );

  const res: HashResult | undefined = data?.code === 0 ? data.data : undefined;
  const errMsg = toolError(data, error);

  const submit = () => {
    if (!text) return;
    run();
  };

  return (
    <ToolShell
      title="Hash / HMAC 计算"
      description="MD5、SHA 系列摘要与 HMAC 签名 —— 计算在服务端完成"
      extra={
        <Space>
          <Button size="small" onClick={() => { setText(''); setKey(''); }} disabled={!text && !key}>
            清空
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <div>
          <ToolLabel>待计算文本(按 UTF-8 编码)</ToolLabel>
          <Input.TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            placeholder="粘贴要算摘要的字符串"
            style={{ fontFamily: 'monospace' }}
            allowClear
          />
        </div>

        <div>
          <ToolLabel>
            HMAC 密钥(选填 —— 填了就算 HMAC, 不填只算裸摘要)
          </ToolLabel>
          <Input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="留空则不计算 HMAC"
            style={{ width: 420, fontFamily: 'monospace' }}
            allowClear
          />
        </div>

        <div>
          <ToolLabel>算法</ToolLabel>
          <Space direction="vertical" style={{ marginTop: 4 }} size={4}>
            {ALGORITHMS.map((a) => (
              <Checkbox
                key={a.value}
                checked={selected.includes(a.value)}
                onChange={(e) =>
                  setSelected((prev) =>
                    e.target.checked ? [...prev, a.value] : prev.filter((v) => v !== a.value),
                  )
                }
              >
                <Space size={6}>
                  <Text strong>{a.label}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {a.note}
                  </Text>
                </Space>
              </Checkbox>
            ))}
          </Space>
        </div>

        <Space>
          <Button type="primary" loading={loading} onClick={submit} disabled={!text || selected.length === 0}>
            计算
          </Button>
          {selected.length === 0 ? (
            <Text type="secondary">至少选一个算法</Text>
          ) : null}
        </Space>

        {errMsg ? <Alert type="error" showIcon message="计算失败" description={errMsg} /> : null}

        {res ? (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space size={32}>
              <Statistic title="字符数" value={res.char_count} />
              <Statistic title="UTF-8 字节" value={res.bytes} />
            </Space>

            <ToolLabel>摘要</ToolLabel>
            <Space direction="vertical" style={{ width: '100%' }} size={4}>
              {Object.entries(res.digests).map(([algo, v]) => (
                <div key={algo} style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
                  <Text strong style={{ minWidth: 64 }}>
                    {algo.toUpperCase()}
                  </Text>
                  <Text code copyable style={{ wordBreak: 'break-all' }}>
                    {v}
                  </Text>
                </div>
              ))}
            </Space>

            {res.hmacs ? (
              <>
                <ToolLabel>HMAC(密钥参与)</ToolLabel>
                <Space direction="vertical" style={{ width: '100%' }} size={4}>
                  {Object.entries(res.hmacs).map(([algo, v]) => (
                    <div key={algo} style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
                      <Text strong style={{ minWidth: 64 }}>
                        HMAC-{algo.toUpperCase()}
                      </Text>
                      <Text code copyable style={{ wordBreak: 'break-all' }}>
                        {v}
                      </Text>
                    </div>
                  ))}
                </Space>
              </>
            ) : (
              <Alert
                type="info"
                showIcon
                message="填入密钥可同时得到 HMAC 签名"
                description="接口签名常用 HMAC-SHA256, 密钥参与运算后不可逆推。"
              />
            )}

            <ToolResult
              label="全部结果(一行一个)"
              value={[
                ...Object.entries(res.digests).map(([a, v]) => `${a}  ${v}`),
                ...(res.hmacs
                  ? Object.entries(res.hmacs).map(([a, v]) => `hmac-${a}  ${v}`)
                  : []),
              ].join('\n')}
            />
          </Space>
        ) : null}
      </Space>
    </ToolShell>
  );
};

export default HashTool;
