import React, { useMemo, useState } from 'react';
import { Alert, Button, Col, Input, Row, Space, Statistic, Tag, Typography } from 'antd';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import { decodeJwt, jwtExpiry } from '@/utils/tool';

const { Text, Paragraph } = Typography;

/** 常见 claim 的中文说明 —— 平台自己的 JWT 也走这套标准字段 */
const CLAIM_HINTS: Record<string, string> = {
  sub: '主体(通常是用户 id)',
  iss: '签发者',
  aud: '受众',
  exp: '过期时间(秒级时间戳)',
  nbf: '生效时间',
  iat: '签发时间',
  jti: '令牌唯一标识',
  role: '角色(user/admin/superAdmin)',
  username: '用户名',
};

/**
 * JWT 解码 —— **只解码, 不验签**。
 *
 * 页面顶部必须写明这一点: 有人会以为"解出来了 = 这个 token 是有效的",
 * 实际上签名一段都没校验, 任何人都能改 payload 再解出一个"看起来正常"的结果。
 */
const JwtDecoder: React.FC = () => {
  const [token, setToken] = useState('');

  const parts = useMemo(() => decodeJwt(token), [token]);
  const expiry = useMemo(() => jwtExpiry(parts.payload), [parts.payload]);

  const headerJson = parts.header ? JSON.stringify(parts.header, null, 2) : '';
  const payloadJson = parts.payload ? JSON.stringify(parts.payload, null, 2) : '';

  const claimRows = useMemo(() => {
    if (!parts.payload) return [];
    return Object.entries(parts.payload).map(([k, v]) => ({
      key: k,
      value:
        typeof v === 'object' ? JSON.stringify(v) : String(v),
      hint: CLAIM_HINTS[k],
      // exp/iat/iat 这类时间戳单独标出来, 方便一眼看到过期时间
      isTime: k === 'exp' || k === 'iat' || k === 'nbf',
    }));
  }, [parts.payload]);

  const fmtTs = (v: unknown): string => {
    if (typeof v !== 'number') return '';
    const d = new Date(v * 1000);
    if (Number.isNaN(d.getTime())) return '';
    const local = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
      d.getDate(),
    ).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(
      2,
      '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
    const remain = v - Math.floor(Date.now() / 1000);
    const suffix =
      remain > 0
        ? `(${Math.floor(remain / 86400)} 天 ${Math.floor((remain % 86400) / 3600)} 小时后过期)`
        : '(已过期)';
    return `${local} ${suffix}`;
  };

  return (
    <ToolShell
      title="JWT 解码"
      description="解出 header / payload, 并算出是否过期 —— 只解码, 不验签"
      extra={
        <Space>
          <Button size="small" onClick={() => setToken('')} disabled={!token}>
            清空
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Alert
          type="warning"
          showIcon
          message="这里不做签名验证"
          description="解码结果只说明「这段 base64 能解开」, 不代表令牌是真的 —— 签名校验发生在后端每次请求时。排查 401 时请重点看下面的 exp。"
        />

        <ToolLabel>粘贴 JWT(平台的 token 存在 localStorage 的 pityToken)</ToolLabel>
        <Input.TextArea
          value={token}
          onChange={(e) => setToken(e.target.value)}
          rows={4}
          placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.xxx"
          style={{ fontFamily: 'monospace' }}
          allowClear
        />

        {token.trim() && parts.error ? (
          <Alert type="error" showIcon message="解码失败" description={parts.error} />
        ) : null}

        {parts.payload ? (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <Row gutter={16}>
              <Col span={6}>
                <Statistic
                  title="过期时间"
                  value={expiry.exp ? fmtTs(expiry.exp) : '未设置'}
                  valueStyle={{
                    fontSize: 15,
                    fontFamily: 'monospace',
                    color: expiry.expired ? '#ff4d4f' : undefined,
                  }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="签发时间"
                  value={expiry.iat ? fmtTs(expiry.iat) : '未设置'}
                  valueStyle={{ fontSize: 15, fontFamily: 'monospace' }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="剩余有效期"
                  value={
                    expiry.expiresInSec === undefined
                      ? '-'
                      : expiry.expiresInSec > 0
                        ? `${Math.floor(expiry.expiresInSec / 86400)} 天 ${Math.floor((expiry.expiresInSec % 86400) / 3600)} 小时`
                        : '已过期'
                  }
                  valueStyle={{
                    color: expiry.expired ? '#ff4d4f' : expiry.expiresInSec !== undefined && expiry.expiresInSec < 3600 ? '#faad14' : undefined,
                  }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="状态"
                  value={expiry.expired ? '已过期' : '未过期'}
                  valueStyle={{ color: expiry.expired ? '#ff4d4f' : '#52c41a' }}
                />
              </Col>
            </Row>

            <ToolLabel>payload 字段</ToolLabel>
            <Space direction="vertical" style={{ width: '100%' }} size={4}>
              {claimRows.map((r) => (
                <div key={r.key} style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
                  <Tag color="blue" style={{ minWidth: 72, textAlign: 'center' }}>
                    {r.key}
                  </Tag>
                  <Text code style={{ wordBreak: 'break-all' }}>
                    {r.isTime ? `${r.value}  →  ${fmtTs(r.value)}` : r.value}
                  </Text>
                  {r.hint ? <Text type="secondary">— {r.hint}</Text> : null}
                </div>
              ))}
            </Space>

            <Row gutter={16}>
              <Col span={12}>
                <ToolLabel>header</ToolLabel>
                <Paragraph
                  copyable={{ text: headerJson }}
                  style={{
                    padding: 12,
                    background: 'rgba(0,0,0,0.04)',
                    borderRadius: 6,
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    marginBottom: 0,
                    maxHeight: 200,
                    overflow: 'auto',
                  }}
                >
                  {headerJson}
                </Paragraph>
              </Col>
              <Col span={12}>
                <ToolLabel>payload</ToolLabel>
                <Paragraph
                  copyable={{ text: payloadJson }}
                  style={{
                    padding: 12,
                    background: 'rgba(0,0,0,0.04)',
                    borderRadius: 6,
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    marginBottom: 0,
                    maxHeight: 200,
                    overflow: 'auto',
                  }}
                >
                  {payloadJson}
                </Paragraph>
              </Col>
            </Row>

            <ToolResult
              label="签名段(无法在此验证, 需要密钥)"
              value={parts.signature || ''}
              emptyText="无"
            />
          </Space>
        ) : null}
      </Space>
    </ToolShell>
  );
};

export default JwtDecoder;
