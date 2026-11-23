import React, { useMemo, useState } from 'react';
import { Alert, Button, Input, Radio, Select, Space, Typography } from 'antd';
import { useRequest } from '@umijs/max';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import {
  CryptoAction,
  CryptoAlgorithm,
  CryptoEncoding,
  CryptoResult,
  runSymmetricCrypto,
  toolError,
} from '@/services/tool';

const { Text } = Typography;

/** 各算法的密钥/IV 字节数要求 —— 与后端 `_BLOCK` 保持一致 */
const SPEC: Record<CryptoAlgorithm, { key: string; iv: string; block: string; defaultKey: string }> = {
  aes: {
    key: '16 / 24 / 32 字节',
    iv: '16 字节',
    block: '16 字节 (CBC)',
    // 恰好 16 字节 —— 填错长度后端会拒绝, 所以默认值必须自己是对的
    defaultKey: 'pity-aes-key-001',
  },
  des: {
    key: '8 字节',
    iv: '8 字节(留空 = 用 key)',
    block: '8 字节 (CBC)',
    defaultKey: 'pitykey!',
  },
};

/**
 * DES / AES 对称加解密。
 *
 * 密钥长度**不会被自动补齐或截断** —— 后端会明确报错并告诉你当前是多少字节。
 * 静默补零会让两边各自以为 key 一致, 密文永远解不开, 这类问题最难查。
 */
const CryptoTool: React.FC = () => {
  const [action, setAction] = useState<CryptoAction>('encrypt');
  const [algorithm, setAlgorithm] = useState<CryptoAlgorithm>('aes');
  const [encoding, setEncoding] = useState<CryptoEncoding>('hex');
  const [text, setText] = useState('');
  const [key, setKey] = useState(SPEC.aes.defaultKey);
  const [iv, setIv] = useState('');

  const spec = SPEC[algorithm];

  // key 字节数实时提示 —— 让用户在点按钮之前就知道长度对不对
  const keyBytes = useMemo(() => new TextEncoder().encode(key).length, [key]);
  const ivBytes = useMemo(() => new TextEncoder().encode(iv).length, [iv]);
  const keyOk = useMemo(() => {
    const allowed = algorithm === 'aes' ? [16, 24, 32] : [8];
    return allowed.includes(keyBytes);
  }, [algorithm, keyBytes]);
  const ivOk = iv === '' || (algorithm === 'aes' ? ivBytes === 16 : ivBytes === 8);

  const { data, run, loading, error } = useRequest(
    () => runSymmetricCrypto({ action, text, algorithm, key, iv: iv || null, encoding }),
    { manual: true, formatResult: (res: any) => res },
  );
  const res: CryptoResult | undefined = data?.code === 0 ? data.data : undefined;
  const errMsg = toolError(data, error);

  const submit = () => {
    if (!text || !key) return;
    run();
  };

  const switchAlgorithm = (a: CryptoAlgorithm) => {
    setAlgorithm(a);
    setKey(SPEC[a].defaultKey);
    setIv('');
  };

  return (
    <ToolShell
      title="DES / AES 加解密"
      description="CBC 模式, 密钥与 IV 由你指定 —— 长度不符会明确报错, 不做静默补齐"
      extra={
        <Space wrap>
          <Radio.Group
            size="small"
            value={algorithm}
            onChange={(e) => switchAlgorithm(e.target.value)}
            optionType="button"
            options={[
              { label: 'AES', value: 'aes' },
              { label: 'DES', value: 'des' },
            ]}
          />
          <Radio.Group
            size="small"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            optionType="button"
            options={[
              { label: '加密', value: 'encrypt' },
              { label: '解密', value: 'decrypt' },
            ]}
          />
          <Select
            size="small"
            value={encoding}
            onChange={(v) => setEncoding(v)}
            style={{ width: 110 }}
            options={[
              { label: 'hex 输出', value: 'hex' },
              { label: 'base64 输出', value: 'base64' },
            ]}
          />
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Alert
          type="info"
          showIcon
          message={`${algorithm.toUpperCase()} · ${spec.block}`}
          description={`密钥 ${spec.key};IV ${spec.iv}。留空 IV 时 ${algorithm === 'des' ? '直接用密钥当 IV(与平台既有 DES 密文兼容)' : '取密钥前 16 字节'}。`}
        />

        <Space size={16} align="start" wrap>
          <div>
            <ToolLabel>
              密钥({spec.key})—— 当前 <Text type={keyOk ? 'success' : 'danger'}>{keyBytes} 字节</Text>
            </ToolLabel>
            <Input
              value={key}
              onChange={(e) => setKey(e.target.value)}
              style={{ width: 320, fontFamily: 'monospace' }}
              placeholder={spec.defaultKey}
              allowClear
            />
          </div>
          <div>
            <ToolLabel>
              IV(选填)—— 当前 <Text type={ivOk ? 'success' : 'danger'}>{ivBytes} 字节</Text>
            </ToolLabel>
            <Input
              value={iv}
              onChange={(e) => setIv(e.target.value)}
              style={{ width: 320, fontFamily: 'monospace' }}
              placeholder="留空则按算法派生"
              allowClear
            />
          </div>
        </Space>

        {!keyOk ? (
          <Alert
            type="warning"
            showIcon
            message={`密钥长度不对 —— ${algorithm.toUpperCase()} 需要 ${spec.key}, 当前 ${keyBytes} 字节`}
            description="密钥按 UTF-8 编码计字节, 含中文或全角字符会占 3 字节。长度不符后端会拒绝, 不会自动补齐。"
          />
        ) : null}
        {!ivOk ? (
          <Alert type="warning" showIcon message={`IV 长度不对 —— 需要 ${spec.iv}, 当前 ${ivBytes} 字节`} />
        ) : null}

        <div>
          <ToolLabel>{action === 'encrypt' ? '待加密的明文' : `待解密的 ${encoding} 密文`}</ToolLabel>
          <Input.TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            style={{ fontFamily: 'monospace' }}
            placeholder={action === 'encrypt' ? '明文字符串' : '粘贴密文'}
            allowClear
          />
        </div>

        <Space>
          <Button
            type="primary"
            loading={loading}
            onClick={submit}
            disabled={!text || !key || !keyOk || !ivOk}
          >
            {action === 'encrypt' ? '加密' : '解密'}
          </Button>
          <Button
            onClick={() => {
              if (res?.result) {
                setText(res.result);
                setAction(action === 'encrypt' ? 'decrypt' : 'encrypt');
              }
            }}
            disabled={!res?.result}
          >
            结果回填并反转方向
          </Button>
          <Button onClick={() => setText('')} disabled={!text}>
            清空
          </Button>
        </Space>

        {errMsg ? (
          <Alert type="error" showIcon message={`${algorithm.toUpperCase()} ${action}失败`} description={errMsg} />
        ) : null}

        <ToolResult
          label={action === 'encrypt' ? '密文' : '明文'}
          value={res?.result || ''}
          emptyText="点击按钮执行"
          notice={
            res
              ? { type: 'success', text: `${algorithm.toUpperCase()} ${action === 'encrypt' ? '加密' : '解密'}成功 · ${encoding} · ${res.result.length} 字符` }
              : null
          }
        />

        <Text type="secondary" style={{ fontSize: 12 }}>
          这里是 CBC 模式, 与平台邮箱 token 使用的 DES-CBC 行为一致。需要 ECB / GCM 等其他模式时请另说。
        </Text>
      </Space>
    </ToolShell>
  );
};

export default CryptoTool;
