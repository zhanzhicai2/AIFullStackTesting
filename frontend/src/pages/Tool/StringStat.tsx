import React, { useMemo, useState } from 'react';
import { Button, Col, Input, Row, Space, Statistic, Typography } from 'antd';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';

const { Text } = Typography;

/** 文本统计 —— 看日志、对报文、数字段时最常要的几个数 */
const StringStat: React.FC = () => {
  const [text, setText] = useState('');

  const stats = useMemo(() => {
    if (!text) return null;
    const lines = text.split('\n');
    const bytes = new TextEncoder().encode(text).length;
    const nonEmpty = lines.filter((l) => l.trim() !== '');
    // 中文 / CJK 统一表意文字 + 全角标点大致范围
    const cjk = (text.match(/[一-鿿㐀-䶿]/g) || []).length;
    const words = (text.match(/[\p{L}\p{N}]+/gu) || []).length;
    const digits = (text.match(/\d/g) || []).length;
    const letters = (text.match(/[a-zA-Z]/g) || []).length;
    const spaces = (text.match(/ /g) || []).length;
    const tabs = (text.match(/\t/g) || []).length;
    const maxLine = lines.reduce((m, l) => Math.max(m, l.length), 0);
    return {
      chars: text.length,
      charsNoSpace: text.replace(/\s/g, '').length,
      bytes,
      lines: lines.length,
      nonEmpty: nonEmpty.length,
      words,
      cjk,
      digits,
      letters,
      spaces,
      tabs,
      maxLine,
    };
  }, [text]);

  const ops: { label: string; fn: (s: string) => string }[] = [
    { label: '去首尾空白', fn: (s) => s.trim() },
    { label: '删空行', fn: (s) => s.split('\n').filter((l) => l.trim() !== '').join('\n') },
    { label: '去重行(保序)', fn: (s) => [...new Set(s.split('\n'))].join('\n') },
    {
      label: '去重行并排序',
      fn: (s) =>
        [...new Set(s.split('\n'))]
          .sort((a, b) => a.localeCompare(b, 'zh-CN'))
          .join('\n'),
    },
    { label: '每行去首尾空白', fn: (s) => s.split('\n').map((l) => l.trim()).join('\n') },
    { label: '行反转', fn: (s) => s.split('\n').reverse().join('\n') },
    { label: '全部转小写', fn: (s) => s.toLowerCase() },
    { label: '全部转大写', fn: (s) => s.toUpperCase() },
    { label: '合并多余空格', fn: (s) => s.replace(/[ \t]+/g, ' ') },
    { label: 'CRLF → LF', fn: (s) => s.replace(/\r\n/g, '\n') },
    { label: 'LF → CRLF', fn: (s) => s.replace(/\n/g, '\r\n') },
    { label: '反转整段', fn: (s) => [...s].reverse().join('') },
  ];

  const apply = (fn: (s: string) => string) => setText(fn(text));

  return (
    <ToolShell
      title="字符串统计"
      description="字节 / 字符 / 行 / 词数统计, 附带常用的文本整理操作"
      extra={
        <Button size="small" onClick={() => setText('')} disabled={!text}>
          清空
        </Button>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <div>
          <ToolLabel>输入文本</ToolLabel>
          <Input.TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder="粘贴日志、报文或任意文本"
            style={{ fontFamily: 'monospace' }}
            allowClear
          />
        </div>

        {stats ? (
          <Row gutter={[16, 16]}>
            <Col span={3}>
              <Statistic title="字符数" value={stats.chars} />
            </Col>
            <Col span={3}>
              <Statistic title="去空白后" value={stats.charsNoSpace} />
            </Col>
            <Col span={3}>
              <Statistic title="UTF-8 字节" value={stats.bytes} />
            </Col>
            <Col span={3}>
              <Statistic title="行数" value={stats.lines} />
            </Col>
            <Col span={3}>
              <Statistic title="非空行" value={stats.nonEmpty} />
            </Col>
            <Col span={3}>
              <Statistic title="最长行" value={stats.maxLine} />
            </Col>
            <Col span={3}>
              <Statistic title="词数" value={stats.words} />
            </Col>
            <Col span={3}>
              <Statistic title="中文字符" value={stats.cjk} />
            </Col>
            <Col span={3}>
              <Statistic title="字母" value={stats.letters} />
            </Col>
            <Col span={3}>
              <Statistic title="数字" value={stats.digits} />
            </Col>
            <Col span={3}>
              <Statistic title="空格" value={stats.spaces} />
            </Col>
            <Col span={3}>
              <Statistic title="制表符" value={stats.tabs} />
            </Col>
          </Row>
        ) : (
          <Text type="secondary">粘贴文本后显示统计</Text>
        )}

        <div>
          <ToolLabel>整理操作(直接改写上方输入框)</ToolLabel>
          <Space wrap style={{ marginTop: 6 }}>
            {ops.map((o) => (
              <Button key={o.label} size="small" disabled={!text} onClick={() => apply(o.fn)}>
                {o.label}
              </Button>
            ))}
          </Space>
        </div>

        <ToolResult
          label="整理结果(即上方输入框当前内容)"
          value={text}
          emptyText="等待输入"
        />
      </Space>
    </ToolShell>
  );
};

export default StringStat;
