import React, { useMemo, useState } from 'react';
import { Alert, Checkbox, Input, Space, Tag, Typography } from 'antd';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';

const { Text, Paragraph } = Typography;

const FLAGS = [
  { key: 'g', label: 'g 全局', desc: '找出所有匹配, 而不是第一个' },
  { key: 'i', label: 'i 忽略大小写', desc: 'abc 能匹配 ABC' },
  { key: 'm', label: 'm 多行', desc: '^ 与 $ 匹配每行的开头结尾' },
  { key: 's', label: 's 单行', desc: '. 也能匹配换行符' },
  { key: 'u', label: 'u Unicode', desc: '正确处理 emoji 等代理对' },
];

/** 常用正则速查 —— 测试平台断言里出现频率最高的几条 */
const PRESETS: { label: string; pattern: string }[] = [
  { label: '整数', pattern: '^-?\\d+$' },
  { label: '正数(可带小数)', pattern: '^\\d+(\\.\\d+)?$' },
  { label: '手机号(大陆)', pattern: '^1[3-9]\\d{9}$' },
  { label: '邮箱', pattern: '^[\\w.+-]+@[\\w-]+\\.[\\w.-]+$' },
  { label: '日期 YYYY-MM-DD', pattern: '^\\d{4}-\\d{2}-\\d{2}$' },
  { label: '时间 HH:mm:ss', pattern: '^\\d{2}:\\d{2}:\\d{2}$' },
  { label: 'UUID', pattern: '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' },
  { label: '身份证(18位)', pattern: '^\\d{17}[\\dXx]$' },
  { label: 'URL', pattern: '^https?://[^\\s]+$' },
  { label: '中文字符', pattern: '[\\u4e00-\\u9fa5]+' },
  { label: 'JSON 键', pattern: '"([^"]+)"\\s*:' },
  { label: '连续空白', pattern: '\\s{2,}' },
];

/**
 * 正则测试 —— 实时给出匹配位置与捕获组。
 *
 * **ReDoS 提示**: JS 的正则不能被中断, 嵌套量词(如 `(a+)+$`)配上长文本
 * 会让页面直接卡死。所以这里限制测试文本长度, 并在 UI 上写明风险 ——
 * 不做"超时中断", 那需要 Worker, 对一个工具页不划算。
 */
const RegexTester: React.FC = () => {
  const [pattern, setPattern] = useState('\\d+');
  const [flags, setFlags] = useState<string[]>(['g']);
  const [text, setText] = useState('订单号 20261123001 已支付, 金额 99.50');
  const [showHint, setShowHint] = useState(true);

  const MAX_TEXT = 200_000;

  const regex = useMemo(() => {
    if (!pattern) return { ok: false as const, error: '请输入正则表达式' };
    try {
      return { ok: true as const, re: new RegExp(pattern, flags.join('')) };
    } catch (err) {
      return { ok: false as const, error: err instanceof Error ? err.message : String(err) };
    }
  }, [pattern, flags]);

  const matches = useMemo(() => {
    if (!regex.ok) return { list: [] as RegExpMatchArray[], error: '' };
    if (!text) return { list: [], error: '' };
    // 没开 g 时 exec 只返回第一个, 统一走 matchAll 需要 g —— 补一个副本
    const re = regex.re.flags.includes('g') ? regex.re : new RegExp(regex.re.source, `${regex.re.flags}g`);
    const list: RegExpMatchArray[] = [];
    let m: RegExpExecArray | null;
    let guard = 0;
    // 防零宽匹配死循环: lastIndex 不前进时强制推进一位
    while ((m = re.exec(text)) !== null && guard < 10_000) {
      guard += 1;
      list.push(m as unknown as RegExpMatchArray);
      if (m[0] === '') re.lastIndex += 1;
    }
    return { list, error: '' };
  }, [regex, text]);

  /** 把匹配片段高亮出来 —— 用下划线区间拼, 避免直接插 HTML */
  const highlighted = useMemo(() => {
    if (!regex.ok || !text || matches.list.length === 0) return text;
    const spans: { start: number; end: number }[] = matches.list.map((m) => ({
      start: m.index ?? 0,
      end: (m.index ?? 0) + (m[0]?.length ?? 0),
    }));
    spans.sort((a, b) => a.start - b.start);
    const out: React.ReactNode[] = [];
    let cursor = 0;
    spans.forEach((s, i) => {
      if (s.start < cursor) return; // 重叠的跳过
      if (s.start > cursor) out.push(text.slice(cursor, s.start));
      out.push(
        <mark key={`${s.start}-${i}`} style={{ background: '#ffe58f', padding: '0 1px' }}>
          {text.slice(s.start, s.end)}
        </mark>,
      );
      cursor = s.end;
    });
    if (cursor < text.length) out.push(text.slice(cursor));
    return out;
  }, [regex, text, matches.list]);

  const setFlag = (key: string, on: boolean) => {
    setFlags((prev) => (on ? [...prev, key] : prev.filter((f) => f !== key)));
  };

  return (
    <ToolShell
      title="正则测试"
      description="实时匹配, 给出位置与捕获组 —— 与用例断言里的正则同一套 JS 语义"
      extra={
        <Checkbox
          checked={showHint}
          onChange={(e) => setShowHint(e.target.checked)}
        >
          显示风险提示
        </Checkbox>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        {showHint ? (
          <Alert
            type="warning"
            showIcon
            message="小心灾难性回溯"
            description="形如 (a+)+$ 的嵌套量词配上长文本会把页面卡死 —— JS 正则无法中断。测试文本已限制在 20 万字符内, 但复杂正则仍需自行留意。"
            closable
            onClose={() => setShowHint(false)}
          />
        ) : null}

        <div>
          <ToolLabel>正则表达式</ToolLabel>
          <Space.Compact style={{ width: '100%' }}>
            <Input
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              style={{ fontFamily: 'monospace' }}
              placeholder="例如 \\d{6}"
            />
            <Input
              value={flags.join('')}
              onChange={(e) =>
                setFlags(
                  e.target.value
                    .split('')
                    .filter((c) => 'gimsuy'.includes(c))
                    .filter((c, i, a) => a.indexOf(c) === i),
                )
              }
              style={{ width: 120, fontFamily: 'monospace' }}
              placeholder="flags"
            />
          </Space.Compact>
          <Space wrap style={{ marginTop: 8 }}>
            {FLAGS.map((f) => (
              <Checkbox
                key={f.key}
                checked={flags.includes(f.key)}
                onChange={(e) => setFlag(f.key, e.target.checked)}
              >
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {f.label}
                </Text>
              </Checkbox>
            ))}
          </Space>
        </div>

        {regex.ok ? (
          <Text type="secondary" style={{ fontSize: 12 }}>
            正则: <code>/{pattern}/{flags.join('')}</code>
          </Text>
        ) : (
          <Alert type="error" showIcon message="正则不合法" description={regex.error} />
        )}

        <div>
          <ToolLabel>测试文本({text.length} / {MAX_TEXT} 字符)</ToolLabel>
          <Input.TextArea
            value={text.length > MAX_TEXT ? text.slice(0, MAX_TEXT) : text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_TEXT))}
            rows={6}
            style={{ fontFamily: 'monospace' }}
            allowClear
          />
        </div>

        <div>
          <ToolLabel>高亮匹配</ToolLabel>
          <Paragraph
            style={{
              padding: 12,
              background: 'rgba(0,0,0,0.04)',
              borderRadius: 6,
              fontFamily: 'monospace',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              marginBottom: 0,
              minHeight: 48,
            }}
          >
            {highlighted || <Text type="secondary">无匹配</Text>}
          </Paragraph>
        </div>

        <ToolLabel>
          匹配结果({matches.list.length} 个)
          {matches.list.length >= 10_000 ? ' — 已达上限, 只显示前 10000 个' : ''}
        </ToolLabel>
        <Space direction="vertical" style={{ width: '100%' }} size={6}>
          {matches.list.slice(0, 200).map((m, i) => (
            <div key={`${m.index}-${i}`} style={{ fontFamily: 'monospace', fontSize: 13 }}>
              <Tag color="blue">#{i + 1}</Tag>
              <Text code>@{m.index}</Text>{' '}
              <Text strong>{m[0] === '' ? '(空匹配)' : m[0]}</Text>
              {m.length > 1 ? (
                <Text type="secondary" style={{ marginLeft: 12 }}>
                  捕获组: {m.slice(1).map((g, gi) => `[${gi + 1}]=${g ?? 'undefined'}`).join('  ')}
                </Text>
              ) : null}
            </div>
          ))}
          {matches.list.length > 200 ? (
            <Text type="secondary">仅显示前 200 条, 共 {matches.list.length} 条</Text>
          ) : null}
          {matches.list.length === 0 && text && regex.ok ? (
            <Text type="secondary">没有匹配</Text>
          ) : null}
        </Space>

        <ToolLabel>常用正则速查(点击填入)</ToolLabel>
        <Space wrap>
          {PRESETS.map((p) => (
            <Tag
              key={p.label}
              style={{ cursor: 'pointer' }}
              onClick={() => setPattern(p.pattern)}
              color="geekblue"
            >
              {p.label}
            </Tag>
          ))}
        </Space>

        <ToolResult
          label="匹配到的全部文本"
          value={matches.list.map((m) => m[0]).join('\n')}
          emptyText="无匹配"
        />
      </Space>
    </ToolShell>
  );
};

export default RegexTester;
