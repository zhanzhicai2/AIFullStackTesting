import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Col, DatePicker, Input, Row, Space, Statistic, Tag, Typography } from 'antd';
import moment, { Moment } from 'moment';
import { ToolLabel, ToolResult, ToolShell } from '@/components/Tool/ToolShell';
import { formatInTimeZone, localTimeZone, timeZoneOffset } from '@/utils/tool';

const { Text } = Typography;

/**
 * 时间戳转换 —— 秒/毫秒/日期互转, 顺带给出各时区的墙上时间。
 *
 * 秒与毫秒**自动识别**(10 位按秒、13 位按毫秒), 识别结果会写在页面上 ——
 * 搞错单位是最常见的踩坑: 10 位按毫秒解读会落到 1970 年。
 *
 * 时区用浏览器原生 `Intl` 而不是 `moment.tz` —— 仓库只装了 `moment`,
 * 没有 `moment-timezone`, 调 `.tz()` 会直接 undefined。
 */
const Timestamp: React.FC = () => {
  const [now, setNow] = useState(moment());
  const [input, setInput] = useState('');
  const [datePick, setDatePick] = useState<Moment | null>(null);

  // 每秒刷新「当前时间」—— 这是这个页面最常被瞟一眼的地方
  useEffect(() => {
    const timer = setInterval(() => setNow(moment()), 1000);
    return () => clearInterval(timer);
  }, []);

  const parsed = useMemo(() => {
    const raw = input.trim();
    if (!raw) return null;
    if (/^-?\d+$/.test(raw)) {
      const n = Number(raw);
      if (!Number.isFinite(n)) return { ok: false as const, error: '数值超出安全范围' };
      // 10 位 = 秒, 13 位 = 毫秒 —— 1e11 是两者的分界
      const isSeconds = Math.abs(n) < 1e11;
      const m = isSeconds ? moment.unix(n) : moment(n);
      if (!m.isValid()) return { ok: false as const, error: '无法解析为时间' };
      return {
        ok: true as const,
        unit: isSeconds ? '秒' : '毫秒',
        moment: m,
        unix: m.unix(),
        ms: m.valueOf(),
      };
    }
    const m = moment(raw);
    if (!m.isValid()) {
      return {
        ok: false as const,
        error: '既不是纯数字时间戳, 也不是可识别的日期字符串(试试 2026-11-23 10:00:00)',
      };
    }
    return { ok: true as const, unit: '日期字符串', moment: m, unix: m.unix(), ms: m.valueOf() };
  }, [input]);

  const currentSec = now.unix();
  const currentMs = now.valueOf();

  const zoneRows = useMemo(() => {
    if (!parsed?.ok) return [];
    const date = parsed.moment.toDate();
    return [
      { label: '本机', tz: localTimeZone() },
      { label: 'UTC', tz: 'UTC' },
      { label: '北京时间', tz: 'Asia/Shanghai' },
      { label: '美西', tz: 'America/Los_Angeles' },
      { label: '日本', tz: 'Asia/Tokyo' },
    ].map((z) => ({
      label: z.label,
      tz: z.tz,
      text: formatInTimeZone(date, z.tz),
      offset: timeZoneOffset(date, z.tz),
    }));
  }, [parsed]);

  const copy = (v: string) => navigator.clipboard?.writeText(v);

  const onPick = (m: Moment | null) => {
    setDatePick(m);
    if (m) setInput(String(m.unix()));
  };

  return (
    <ToolShell
      title="时间戳转换"
      description="秒 / 毫秒 / 日期互转, 自动识别单位并标出识别结果"
    >
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <Row gutter={24}>
          <Col span={8}>
            <Statistic
              title="当前时间戳(秒)"
              value={currentSec}
              valueStyle={{ fontFamily: 'monospace' }}
            />
            <Button size="small" type="link" style={{ padding: 0 }} onClick={() => copy(String(currentSec))}>
              复制
            </Button>
          </Col>
          <Col span={8}>
            <Statistic
              title="当前时间戳(毫秒)"
              value={currentMs}
              valueStyle={{ fontFamily: 'monospace' }}
            />
            <Button size="small" type="link" style={{ padding: 0 }} onClick={() => copy(String(currentMs))}>
              复制
            </Button>
          </Col>
          <Col span={8}>
            <Statistic title="当前时间(本地)" value={now.format('YYYY-MM-DD HH:mm:ss')} />
          </Col>
        </Row>

        <Space size={12} align="start" wrap>
          <div>
            <ToolLabel>时间戳或日期字符串</ToolLabel>
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="1763865600  /  1763865600000  /  2026-11-23 10:00:00"
              style={{ width: 340, fontFamily: 'monospace' }}
              allowClear
            />
          </div>
          <div>
            <ToolLabel>或直接选一个时间</ToolLabel>
            <DatePicker
              showTime
              value={datePick}
              onChange={onPick}
              style={{ width: 240 }}
              allowClear
            />
          </div>
          <div>
            <ToolLabel>&nbsp;</ToolLabel>
            <Space wrap>
              <Button size="small" onClick={() => setInput(String(currentSec))}>
                填入当前秒
              </Button>
              <Button size="small" onClick={() => setInput(String(currentMs))}>
                填入当前毫秒
              </Button>
              <Button size="small" onClick={() => { setInput(''); setDatePick(null); }}>
                清空
              </Button>
            </Space>
          </div>
        </Space>

        {input.trim() && parsed && !parsed.ok ? (
          <Alert type="error" showIcon message="无法解析" description={parsed.error} />
        ) : null}

        {parsed?.ok ? (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space>
              <Text type="secondary">识别为</Text>
              <Tag color="blue">{parsed.unit}</Tag>
              {parsed.unit === '日期字符串' ? <Text type="secondary">按本地时区解析</Text> : null}
            </Space>

            <Row gutter={16}>
              <Col span={6}>
                <Statistic title="秒" value={parsed.unix} valueStyle={{ fontFamily: 'monospace' }} />
              </Col>
              <Col span={6}>
                <Statistic title="毫秒" value={parsed.ms} valueStyle={{ fontFamily: 'monospace' }} />
              </Col>
              <Col span={6}>
                <Statistic
                  title="ISO 8601"
                  value={parsed.moment.clone().format()}
                  valueStyle={{ fontFamily: 'monospace', fontSize: 15 }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="UTC"
                  value={parsed.moment.clone().utc().format('YYYY-MM-DD HH:mm:ss')}
                  valueStyle={{ fontFamily: 'monospace', fontSize: 15 }}
                />
              </Col>
            </Row>

            <ToolLabel>各时区的墙上时间</ToolLabel>
            <Space direction="vertical" style={{ width: '100%' }} size={4}>
              {zoneRows.map((r) => (
                <Text key={r.tz} code style={{ display: 'block' }}>
                  {`${r.label}  ${r.text}  ${r.offset}`.trim()}
                </Text>
              ))}
            </Space>

            <ToolResult
              label="常用格式"
              value={[
                `秒      ${parsed.unix}`,
                `毫秒    ${parsed.ms}`,
                `本地    ${parsed.moment.format('YYYY-MM-DD HH:mm:ss')}`,
                `ISO     ${parsed.moment.clone().format()}`,
                `UTC     ${parsed.moment.clone().utc().format('YYYY-MM-DD HH:mm:ss')}`,
                `Date    ${parsed.moment.toDate().toString()}`,
              ].join('\n')}
            />
          </Space>
        ) : null}
      </Space>
    </ToolShell>
  );
};

export default Timestamp;
