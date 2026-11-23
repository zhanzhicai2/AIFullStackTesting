import React, { useMemo, useState } from 'react';
import { Alert, Button, Radio, Space, Typography } from 'antd';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import {
  base64ToUtf8,
  htmlEscape,
  htmlUnescape,
  urlDecode,
  urlEncode,
  utf8ToBase64,
} from '@/utils/tool';

const { Text } = Typography;

type Kind = 'base64' | 'url' | 'html' | 'js' | 'sql';
type Direction = 'encode' | 'decode';

const KINDS: { value: Kind; label: string; hint: string }[] = [
  { value: 'base64', label: 'Base64', hint: '按 UTF-8 处理, 中文不会乱码(直接用 btoa 会抛异常)' },
  { value: 'url', label: 'URL 编码', hint: 'encodeURIComponent / decodeURIComponent 语义, `+` 也会被解成空格' },
  { value: 'html', label: 'HTML 实体', hint: '转义 < > & " \' —— 拼 HTML 字符串时用' },
  { value: 'js', label: 'JS 字符串', hint: '按 JSON 字符串规则转义, 可直接塞进双引号字符串里' },
  { value: 'sql', label: 'SQL 字符串', hint: '单引号翻倍 + 反斜杠转义(MySQL 默认 NO_BACKSLASH_ESCAPES 关闭时有效)' },
];

/** SQL 转义 —— 只处理引号与反斜杠, 参数化查询才是正解 */
const sqlEncode = (s: string) => s.replace(/\\/g, '\\\\').replace(/'/g, "''");
const sqlDecode = (s: string) => s.replace(/''/g, "'").replace(/\\\\/g, '\\');

function transform(kind: Kind, dir: Direction, input: string): { ok: true; value: string } | { ok: false; error: string } {
  if (!input) return { ok: true, value: '' };
  try {
    switch (kind) {
      case 'base64':
        return { ok: true, value: dir === 'encode' ? utf8ToBase64(input) : base64ToUtf8(input) };
      case 'url':
        return { ok: true, value: dir === 'encode' ? urlEncode(input) : urlDecode(input) };
      case 'html':
        return { ok: true, value: dir === 'encode' ? htmlEscape(input) : htmlUnescape(input) };
      case 'js':
        if (dir === 'encode') return { ok: true, value: JSON.stringify(input).slice(1, -1) };
        // 解码: 补回引号后交给 JSON.parse, 它认得 \n \uXXXX 等全部转义
        return { ok: true, value: JSON.parse(`"${input.replace(/"/g, '\\"')}"`) as string };
      case 'sql':
        return { ok: true, value: dir === 'encode' ? sqlEncode(input) : sqlDecode(input) };
      default:
        return { ok: false, error: '未知类型' };
    }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

/**
 * 编解码工具 —— Base64 / URL / HTML / JS 字符串 / SQL 字符串。
 *
 * 五种都是「粘一段进来转一下」的高频操作, 放在一个页面里用单选切换,
 * 比拆成五个菜单项更省事: 它们的交互形态完全一样。
 */
const Codec: React.FC = () => {
  const [kind, setKind] = useState<Kind>('base64');
  const [dir, setDir] = useState<Direction>('encode');
  const [input, setInput] = useState('');

  const result = useMemo(() => transform(kind, dir, input), [kind, dir, input]);
  const hint = KINDS.find((k) => k.value === kind)?.hint;

  const swap = () => {
    if (result.ok && result.value) {
      setInput(result.value);
      setDir(dir === 'encode' ? 'decode' : 'encode');
    }
  };

  return (
    <ToolShell
      title="编解码"
      description="Base64 / URL / HTML 实体 / JS 与 SQL 字符串转义"
      extra={
        <Radio.Group
          size="small"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          optionType="button"
          options={KINDS.map((k) => ({ label: k.label, value: k.value }))}
        />
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Space wrap>
          <Radio.Group
            value={dir}
            onChange={(e) => setDir(e.target.value)}
            optionType="button"
            options={[
              { label: dir === 'encode' ? '编码 →' : '← 编码', value: 'encode' },
              { label: dir === 'encode' ? '← 解码' : '解码 →', value: 'decode' },
            ]}
          />
          <Button onClick={swap} disabled={!result.ok || !result.value}>
            结果回填输入框并反转方向
          </Button>
          <Button onClick={() => setInput('')} disabled={!input}>
            清空
          </Button>
        </Space>

        {hint ? (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {hint}
          </Text>
        ) : null}

        <ToolLabel>{dir === 'encode' ? '待编码' : '待解码'}</ToolLabel>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          rows={8}
          placeholder={dir === 'encode' ? '粘贴原文' : '粘贴编码结果'}
          style={{
            width: '100%',
            padding: 12,
            borderRadius: 6,
            border: '1px solid #d9d9d9',
            fontFamily: 'monospace',
            fontSize: 13,
            resize: 'vertical',
          }}
        />

        {input && !result.ok ? (
          <Alert type="error" showIcon message="转换失败" description={result.error} />
        ) : null}

        <ToolResult
          label={dir === 'encode' ? '编码结果' : '解码结果'}
          value={result.ok ? result.value : ''}
          emptyText="等待输入"
        />
      </Space>
    </ToolShell>
  );
};

export default Codec;
