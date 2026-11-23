import React, { useMemo, useState } from 'react';
import { Alert, Button, Col, Input, Radio, Row, Space, Statistic, Typography } from 'antd';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import { formatJson, jsonType, minifyJson } from '@/utils/tool';

const { Text } = Typography;

/** 递归算深度与键数 —— 页面要告诉用户"这个 JSON 有多大、多深" */
function inspect(value: unknown): { depth: number; keys: number; arrays: number; leaves: number } {
  let keys = 0;
  let arrays = 0;
  let leaves = 0;
  const walk = (v: unknown, d: number): number => {
    const t = jsonType(v);
    if (t === 'object') {
      const o = v as Record<string, unknown>;
      keys += Object.keys(o).length;
      return 1 + Math.max(0, ...Object.values(o).map((x) => walk(x, d + 1)));
    }
    if (t === 'array') {
      arrays += 1;
      const a = v as unknown[];
      return 1 + Math.max(0, ...a.map((x) => walk(x, d + 1)));
    }
    leaves += 1;
    return 0;
  };
  const depth = walk(value, 0);
  return { depth, keys, arrays, leaves };
}

/**
 * JSON 工具 —— 格式化 / 压缩 / 校验 / 结构统计。
 *
 * 全程本地计算: 粘贴的 body 可能含业务数据, 不必为了格式化发一次请求。
 * 需要「和断言引擎口径一致的差异」时去 `/tool/diff`。
 */
const JsonTool: React.FC = () => {
  const [text, setText] = useState('');
  const [indent, setIndent] = useState<number>(2);

  const parsed = useMemo(() => {
    if (!text.trim()) return { ok: false as const, error: '' };
    try {
      return { ok: true as const, value: JSON.parse(text) };
    } catch (err) {
      return { ok: false as const, error: err instanceof Error ? err.message : String(err) };
    }
  }, [text]);

  const stats = useMemo(
    () => (parsed.ok ? inspect(parsed.value) : null),
    [parsed],
  );

  const apply = (mode: 'format' | 'minify') => {
    if (!text.trim()) return;
    const r = mode === 'format' ? formatJson(text, indent) : minifyJson(text);
    if (r.ok) setText(r.text);
  };

  const byteLen = useMemo(() => new TextEncoder().encode(text).length, [text]);

  return (
    <ToolShell
      title="JSON 工具"
      description="格式化、压缩、校验与结构统计 —— 全部在本地完成, 不会把内容发给服务器"
      extra={
        <Space>
          <Radio.Group
            size="small"
            value={indent}
            onChange={(e) => setIndent(e.target.value)}
            optionType="button"
            options={[
              { label: '2 空格', value: 2 },
              { label: '4 空格', value: 4 },
              { label: 'Tab', value: 0 },
            ]}
          />
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <ToolLabel>输入 JSON</ToolLabel>
        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={12}
          placeholder={'{\n  "name": "pity",\n  "tags": ["api", "test"]\n}'}
          style={{ fontFamily: 'monospace' }}
          allowClear
        />

        <Space wrap>
          <Button type="primary" onClick={() => apply('format')} disabled={!text.trim()}>
            格式化
          </Button>
          <Button onClick={() => apply('minify')} disabled={!text.trim()}>
            压缩成一行
          </Button>
          <Button onClick={() => setText('')} disabled={!text.trim()}>
            清空
          </Button>
        </Space>

        {text.trim() && !parsed.ok ? (
          <Alert
            type="error"
            showIcon
            message="JSON 解析失败"
            description={
              <Space direction="vertical" size={4}>
                <Text code>{parsed.error}</Text>
                <Text type="secondary">
                  常见原因: 末尾多了逗号、用了单引号、键没加引号、或粘贴时截断了
                </Text>
              </Space>
            }
          />
        ) : null}

        {parsed.ok && stats ? (
          <Row gutter={16}>
            <Col span={4}>
              <Statistic title="字节" value={byteLen} />
            </Col>
            <Col span={4}>
              <Statistic title="顶层类型" value={jsonType(parsed.value)} />
            </Col>
            <Col span={4}>
              <Statistic title="嵌套深度" value={stats.depth} />
            </Col>
            <Col span={4}>
              <Statistic title="键数量" value={stats.keys} />
            </Col>
            <Col span={4}>
              <Statistic title="数组" value={stats.arrays} />
            </Col>
            <Col span={4}>
              <Statistic title="叶子值" value={stats.leaves} />
            </Col>
          </Row>
        ) : null}

        <ToolResult
          label="格式化结果(可直接覆盖上方输入框)"
          value={parsed.ok ? JSON.stringify(parsed.value, null, indent === 0 ? '\t' : indent) : ''}
          emptyText="粘贴 JSON 后自动预览"
        />
      </Space>
    </ToolShell>
  );
};

export default JsonTool;
