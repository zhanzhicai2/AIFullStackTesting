import React, { useCallback, useState } from 'react';
import { Alert, Button, InputNumber, Radio, Space, Statistic, Typography } from 'antd';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import { RANDOM_CHARSETS, RandomCharsetName, randomInt, randomString, uuidV4 } from '@/utils/tool';

const { Text } = Typography;

type Mode = 'uuid' | 'string' | 'int';

const MAX_BATCH = 500;

/**
 * 随机生成 —— UUID / 随机字符串 / 随机整数。
 *
 * 全部走 `crypto.getRandomValues`(拒绝采样消除取模偏差), 不用 `Math.random`。
 * 批量上限 500: 再多对"复制去用"这个场景没有意义, 只会让按钮点不动。
 */
const RandomGen: React.FC = () => {
  const [mode, setMode] = useState<Mode>('uuid');
  const [count, setCount] = useState(5);
  const [length, setLength] = useState(16);
  const [charset, setCharset] = useState<RandomCharsetName>('alphaNum');
  const [min, setMin] = useState(1);
  const [max, setMax] = useState(100);
  const [result, setResult] = useState('');

  const generate = useCallback(() => {
    const n = Math.min(Math.max(1, count), MAX_BATCH);
    const lines: string[] = [];
    for (let i = 0; i < n; i += 1) {
      if (mode === 'uuid') lines.push(uuidV4());
      else if (mode === 'string') lines.push(randomString(length, RANDOM_CHARSETS[charset]));
      else lines.push(String(randomInt(min, max)));
    }
    setResult(lines.join('\n'));
  }, [mode, count, length, charset, min, max]);

  return (
    <ToolShell
      title="随机生成"
      description="UUID v4 / 随机字符串 / 随机整数 —— 用 CSPRNG, 不是 Math.random"
      extra={
        <Radio.Group
          size="small"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          optionType="button"
          options={[
            { label: 'UUID', value: 'uuid' },
            { label: '随机字符串', value: 'string' },
            { label: '随机整数', value: 'int' },
          ]}
        />
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <Space size={24} align="end" wrap>
          <div>
            <ToolLabel>生成条数(1-{MAX_BATCH})</ToolLabel>
            <InputNumber
              min={1}
              max={MAX_BATCH}
              value={count}
              onChange={(v) => setCount(v ?? 1)}
              style={{ width: 120 }}
            />
          </div>

          {mode === 'string' ? (
            <>
              <div>
                <ToolLabel>每条长度</ToolLabel>
                <InputNumber
                  min={1}
                  max={4096}
                  value={length}
                  onChange={(v) => setLength(v ?? 16)}
                  style={{ width: 120 }}
                />
              </div>
              <div>
                <ToolLabel>字符集</ToolLabel>
                <Radio.Group
                  size="small"
                  value={charset}
                  onChange={(e) => setCharset(e.target.value)}
                  optionType="button"
                  options={[
                    { label: '字母+数字', value: 'alphaNum' },
                    { label: '纯数字', value: 'number' },
                    { label: '小写', value: 'lower' },
                    { label: '大写', value: 'upper' },
                    { label: '十六进制', value: 'hex' },
                    { label: '含符号', value: 'symbol' },
                  ]}
                />
              </div>
            </>
          ) : null}

          {mode === 'int' ? (
            <>
              <div>
                <ToolLabel>最小值</ToolLabel>
                <InputNumber value={min} onChange={(v) => setMin(v ?? 0)} style={{ width: 140 }} />
              </div>
              <div>
                <ToolLabel>最大值</ToolLabel>
                <InputNumber value={max} onChange={(v) => setMax(v ?? 100)} style={{ width: 140 }} />
              </div>
            </>
          ) : null}

          <Button type="primary" onClick={generate}>
            生成
          </Button>
          <Button onClick={() => setResult('')} disabled={!result}>
            清空
          </Button>
        </Space>

        {mode === 'int' && max < min ? (
          <Alert type="warning" showIcon message="最大值小于最小值, 会自动交换后生成" />
        ) : null}

        {result ? (
          <Statistic
            title="已生成"
            value={result.split('\n').length}
            suffix="条"
            valueStyle={{ fontSize: 18 }}
          />
        ) : null}

        <ToolResult label="生成结果" value={result} emptyText="点击「生成」开始" />

        <Text type="secondary" style={{ fontSize: 12 }}>
          UUID 的 v4 版本位与变体位已按 RFC 4122 置位; 字符串按拒绝采样抽取, 不会有取模偏差。
        </Text>
      </Space>
    </ToolShell>
  );
};

export default RandomGen;
