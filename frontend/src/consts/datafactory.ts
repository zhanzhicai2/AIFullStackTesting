// 数据工厂类型与常量, 与后端 app/core/data_factory/generator.py 的 DATA_FACTORY_KINDS
// / FAKER_PROVIDERS / 类型白名单保持一致
export const RULE_KINDS = [
  { label: '固定值', value: 'fixed', params: ['value'] },
  { label: '随机区间', value: 'random', params: ['min', 'max', 'decimals'] },
  { label: '枚举轮转', value: 'enum', params: ['values'] },
  { label: '序列递增', value: 'sequence', params: ['start', 'step'] },
  { label: 'UUID', value: 'uuid', params: ['prefix'] },
  {
    label: '字符模板',
    value: 'template',
    params: ['template'],
    hint: '# 数字 · ? 字母 · * 数字或字母, 可用 ${字段名} 引用其他字段',
  },
  { label: '正则生成', value: 'regex', params: ['pattern'] },
  { label: '引用字段', value: 'reference', params: ['from'] },
  { label: '随机真实数据', value: 'faker', params: ['provider'] },
  {
    label: '内置函数',
    value: 'func',
    params: ['expr'],
    hint: '可用: ${now()} ${uuid()} ${random_int(1,100)} 等',
  },
  { label: '随机日期', value: 'date', params: ['start', 'end', 'format'] },
];

export const COLUMN_TYPES = [
  { label: '字符串', value: 'string' },
  { label: '整数', value: 'int' },
  { label: '浮点数', value: 'float' },
  { label: '布尔', value: 'bool' },
];

// 与后端 FAKER_PROVIDERS 白名单一致
export const FAKER_PROVIDERS = [
  'name', 'first_name', 'last_name', 'user_name', 'phone_number', 'email', 'company',
  'job', 'ssn', 'address', 'city', 'country', 'street_name', 'building_number',
  'password', 'word', 'sentence', 'text', 'paragraph', 'uuid4', 'url', 'uri', 'domain_name',
  'ipv4', 'ipv6', 'mac_address', 'user_agent', 'mime_type', 'file_name', 'file_path',
  'boolean', 'date_between', 'date_this_year', 'future_date', 'past_date', 'timezone',
  'credit_card_number', 'credit_card_expire', 'currency_name', 'currency_code', 'ean',
  'isbn13', 'hex_color', 'color_name', 'rgb_color', 'language_code', 'sha1', 'md5',
];

const KIND_MAP = RULE_KINDS.reduce<Record<string, { label: string; hint?: string }>>(
  (acc, item) => {
    acc[item.value] = { label: item.label, hint: item.hint };
    return acc;
  },
  {}
);

export const ruleKindLabel = (value?: string): string =>
  KIND_MAP[value || '']?.label || value || '未知';

export const ruleKindHint = (value?: string): string => KIND_MAP[value || '']?.hint || '';

export const ruleKindParams = (value?: string): string[] =>
  RULE_KINDS.find((k) => k.value === value)?.params || [];

export const columnTypeLabel = (value?: string): string =>
  COLUMN_TYPES.find((t) => t.value === value)?.label || value || '未知';
