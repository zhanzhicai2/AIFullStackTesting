import React, { useMemo, useState } from 'react';
import { Alert, Button, Col, Input, Row, Space, Tag, Typography } from 'antd';
import { useRequest } from '@umijs/max';
import { ToolLabel, ToolShell } from '@/components/Tool/ToolShell';
import { diffJson, JsonDiffItem } from '@/utils/tool';
import { diffJsonByBackend, JsonDiffResult, toolError } from '@/services/tool';

const { Text } = Typography;

const KIND_LABEL: Record<JsonDiffItem['kind'], { text: string; color: string }> = {
  missing: { text: '实际值缺少', color: 'orange' },
  extra: { text: '实际值多出', color: 'purple' },
  type: { text: '类型不同', color: 'red' },
  value: { text: '取值不同', color: 'gold' },
};

const KIND_EXPLAIN: Record<JsonDiffItem['kind'], string> = {
  missing: '期望值里有这个字段, 实际值里没有',
  extra: '实际值里有这个字段, 期望值里没有',
  type: '两边都有, 但类型不一样(如 string vs number)',
  value: '两边类型相同, 值不同',
};

/**
 * JSON 深度对比。
 *
 * 两个口径并存, 刻意都留着:
 * - **即时对比**(本地递归): 打字就出结果, 用来快速看差异在哪;
 * - **断言引擎对比**(后端 `JsonCompare`): 文案与测试报告页**完全一致**,
 *   用来确认"报告里说的差异"到底是哪一条。
 *
 * 只做本地版的话, 工具说"相同"而报告说"不同"会很难排查 —— 差异出在
 * 类型判定与数组顺序的处理上, 那些规则以引擎为准。
 */
const JsonDiff: React.FC = () => {
  const [expected, setExpected] = useState('');
  const [actual, setActual] = useState('');

  const local = useMemo(() => {
    if (!expected.trim() || !actual.trim()) return null;
    try {
      const e = JSON.parse(expected);
      const a = JSON.parse(actual);
      return { ok: true as const, items: diffJson(e, a) };
    } catch (err) {
      return { ok: false as const, error: err instanceof Error ? err.message : String(err) };
    }
  }, [expected, actual]);

  const { data, run, loading, error } = useRequest(() => diffJsonByBackend(expected, actual), {
    manual: true,
    formatResult: (res: any) => res,
  });
  const remote: JsonDiffResult | undefined = data?.code === 0 ? data.data : undefined;
  const remoteErr = toolError(data, error);

  const swap = () => {
    setExpected(actual);
    setActual(expected);
  };

  const fill = (side: 'expected' | 'actual') => {
    const sample = {
      user: { id: 1, name: 'pity', roles: ['admin', 'user'] },
      total: 3,
      ok: true,
    };
    const other = { user: { id: 1, name: 'pity', roles: ['admin'] }, total: 4, ok: 'yes' };
    if (side === 'expected') setExpected(JSON.stringify(sample, null, 2));
    else setActual(JSON.stringify(other, null, 2));
  };

  return (
    <ToolShell
      title="JSON 深度对比"
      description="左边是期望值, 右边是实际值 —— 本地即时算一遍, 需要与报告一致时再调断言引擎"
      extra={
        <Space>
          <Button size="small" onClick={() => fill('expected')}>
            填示例(期望)
          </Button>
          <Button size="small" onClick={() => fill('actual')}>
            填示例(实际)
          </Button>
          <Button size="small" onClick={swap}>
            互换
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <Row gutter={16}>
          <Col span={12}>
            <ToolLabel>期望值(报告里的预期)</ToolLabel>
            <Input.TextArea
              value={expected}
              onChange={(e) => setExpected(e.target.value)}
              rows={14}
              style={{ fontFamily: 'monospace' }}
              placeholder='{"code": 0, "data": {"id": 1}}'
              allowClear
            />
          </Col>
          <Col span={12}>
            <ToolLabel>实际值(接口返回)</ToolLabel>
            <Input.TextArea
              value={actual}
              onChange={(e) => setActual(e.target.value)}
              rows={14}
              style={{ fontFamily: 'monospace' }}
              placeholder='{"code": 0, "data": {"id": 2}}'
              allowClear
            />
          </Col>
        </Row>

        {/* ---------------- 即时对比 ---------------- */}
        <div>
          <ToolLabel>即时对比(本地计算, 打字即出结果)</ToolLabel>
          {!expected.trim() || !actual.trim() ? (
            <Text type="secondary">两边都填上才会开始对比</Text>
          ) : local && !local.ok ? (
            <Alert type="error" showIcon message="JSON 解析失败" description={local.error} />
          ) : local && local.items.length === 0 ? (
            <Alert type="success" showIcon message="两个 JSON 完全一致" />
          ) : local ? (
            <Space direction="vertical" style={{ width: '100%' }} size={6}>
              <Text type="secondary">
                共 {local.items.length} 处差异
              </Text>
              {local.items.slice(0, 200).map((it, i) => (
                <div
                  key={`${it.path}-${i}`}
                  style={{
                    padding: '6px 10px',
                    background: 'rgba(0,0,0,0.03)',
                    borderRadius: 6,
                    fontFamily: 'monospace',
                    fontSize: 13,
                    wordBreak: 'break-all',
                  }}
                >
                  <Space size={8} wrap>
                    <Tag color={KIND_LABEL[it.kind].color}>{KIND_LABEL[it.kind].text}</Tag>
                    <Text strong>{it.path}</Text>
                  </Space>
                  <div style={{ marginTop: 4 }}>
                    {it.kind !== 'extra' && it.expected !== undefined ? (
                      <Text type="secondary">期望: {it.expected} </Text>
                    ) : null}
                    {it.kind !== 'missing' && it.actual !== undefined ? (
                      <Text type="secondary">实际: {it.actual}</Text>
                    ) : null}
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {KIND_EXPLAIN[it.kind]}
                  </Text>
                </div>
              ))}
              {local.items.length > 200 ? (
                <Text type="secondary">仅显示前 200 条, 共 {local.items.length} 条</Text>
              ) : null}
            </Space>
          ) : null}
        </div>

        {/* ---------------- 断言引擎 ---------------- */}
        <div>
          <ToolLabel>断言引擎对比(后端 JsonCompare, 文案与报告页一致)</ToolLabel>
          <Space>
            <Button
              type="primary"
              loading={loading}
              disabled={!expected.trim() || !actual.trim()}
              onClick={() => run()}
            >
              用断言引擎对比
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              本地版与引擎版可能给出不同条数 —— 以引擎为准, 它才是报告里那套规则
            </Text>
          </Space>

          {remoteErr ? (
            <div style={{ marginTop: 8 }}>
              <Alert type="error" showIcon message="对比失败" description={remoteErr} />
            </div>
          ) : null}

          {remote ? (
            <div style={{ marginTop: 8 }}>
              {remote.identical ? (
                <Alert type="success" showIcon message="断言引擎判定: 两个 JSON 一致" />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }} size={4}>
                  <Text type="secondary">
                    断言引擎给出 {remote.diffs.length} 条差异(顶层类型 期望{' '}
                    {remote.expected_type} / 实际 {remote.actual_type})
                  </Text>
                  {remote.diffs.map((d, i) => (
                    <Text key={i} code style={{ display: 'block', wordBreak: 'break-all' }}>
                      {d}
                    </Text>
                  ))}
                </Space>
              )}
            </div>
          ) : null}
        </div>
      </Space>
    </ToolShell>
  );
};

export default JsonDiff;
