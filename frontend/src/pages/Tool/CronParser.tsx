import React, { useMemo, useState } from 'react';
import { Alert, Button, Input, Space, Tag, Typography } from 'antd';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import { CRON_PRESETS, describeField, parseCron } from '@/utils/cron';

const { Text } = Typography;

/**
 * Cron 表达式解析 —— 展开每个字段的可取值, 并列出接下来 5 次触发时间。
 *
 * **日 / 周是 OR 语义(POSIX)**, 而平台的定时任务跑在 APScheduler 上,
 * 它的 `day` + `day_of_week` 组合是 AND —— 这个差异写在页面上,
 * 否则用户会拿这里的结论去猜 APScheduler 的行为。
 */
const CronParser: React.FC = () => {
  const [expr, setExpr] = useState('0 9 * * 1-5');

  const parsed = useMemo(() => parseCron(expr, 5), [expr]);

  return (
    <ToolShell
      title="Cron 表达式解析"
      description="支持 5 段(分 时 日 月 周)与 6 段(秒起头), 展开字段并推算下次触发"
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Space.Compact style={{ width: '100%', maxWidth: 520 }}>
          <Input
            value={expr}
            onChange={(e) => setExpr(e.target.value)}
            style={{ fontFamily: 'monospace' }}
            placeholder="0 9 * * 1-5"
          />
          <Button onClick={() => setExpr('')} disabled={!expr}>
            清空
          </Button>
        </Space.Compact>

        <div>
          <ToolLabel>常用表达式(点击填入)</ToolLabel>
          <Space wrap style={{ marginTop: 4 }}>
            {CRON_PRESETS.map((p) => (
              <Tag key={p.label} color="geekblue" style={{ cursor: 'pointer' }} onClick={() => setExpr(p.expr)}>
                {p.label} · {p.expr}
              </Tag>
            ))}
          </Space>
        </div>

        {!parsed.ok ? (
          <Alert type="error" showIcon message="表达式不合法" description={parsed.error} />
        ) : null}

        {parsed.ok && parsed.fields ? (
          <>
            <ToolLabel>字段展开</ToolLabel>
            <Space direction="vertical" style={{ width: '100%' }} size={6}>
              {parsed.fields.map((f) => (
                <div
                  key={f.name}
                  style={{
                    display: 'flex',
                    gap: 16,
                    alignItems: 'baseline',
                    padding: '6px 10px',
                    background: 'rgba(0,0,0,0.03)',
                    borderRadius: 6,
                  }}
                >
                  <Tag style={{ minWidth: 44, textAlign: 'center' }}>{f.name}</Tag>
                  <Text code style={{ minWidth: 72 }}>
                    {f.raw}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {describeField(f)}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
                    {f.values.length} 个取值
                  </Text>
                </div>
              ))}
            </Space>

            <ToolLabel>接下来 5 次触发(本地时间)</ToolLabel>
            {parsed.next && parsed.next.length > 0 ? (
              <Space direction="vertical" style={{ width: '100%' }} size={4}>
                {parsed.next.map((d) => (
                  <Text key={d.getTime()} code style={{ display: 'block' }}>
                    {`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}  周${['日', '一', '二', '三', '四', '五', '六'][d.getDay()]}`}
                  </Text>
                ))}
              </Space>
            ) : (
              <Alert
                type="warning"
                showIcon
                message="未来 5 年内不会触发"
                description="常见于日与月的组合不存在(如 0 0 31 2 *), 表达式合法但永远不会命中。"
              />
            )}

            <ToolResult
              label="表达式"
              value={expr}
              emptyText="无"
            />
          </>
        ) : null}

        <Alert
          type="info"
          showIcon
          message="日 / 周的 OR 语义"
          description="标准 cron 里日与周都有限制时, 满足任一即触发(POSIX)。平台的定时任务跑在 APScheduler 上, 它的 day + day_of_week 是 AND —— 两者不同, 拿这里的结果推断调度行为时要注意。"
        />
      </Space>
    </ToolShell>
  );
};

export default CronParser;
