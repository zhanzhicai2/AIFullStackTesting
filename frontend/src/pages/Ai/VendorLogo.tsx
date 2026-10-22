import React from 'react';

// 各厂商配色,不依赖外部 logo 资源,避免内网环境下裂图
const BRAND: Record<string, { color: string; short: string }> = {
  siliconflow: { color: '#6C5CE7', short: 'Si' },
  deepseek: { color: '#4D6BFE', short: 'DS' },
  dashscope: { color: '#FF6A00', short: '百' },
  doubao: { color: '#F5222D', short: '豆' },
  moonshot: { color: '#2F3542', short: 'Mo' },
  minimax: { color: '#E84393', short: 'MM' },
  modelscope: { color: '#1677FF', short: 'Ms' },
  xiaomi: { color: '#FF6900', short: '米' },
  zhipu: { color: '#3859FF', short: 'GL' },
  sensenova: { color: '#1E3A8A', short: 'SN' },
  ollama: { color: '#111827', short: 'Ol' },
};

const FALLBACK = { color: '#8C8C8C', short: '' };

interface Props {
  code?: string;
  name?: string;
  size?: number;
}

const VendorLogo: React.FC<Props> = ({ code = '', name = '', size = 32 }) => {
  const brand = BRAND[code] || FALLBACK;
  // 没有内置配置时退化成中文名首字
  const text = brand.short || name.slice(0, 1) || '?';
  const fontSize = Math.max(11, Math.round(size * 0.4));

  return (
    <div
      style={{
        width: size,
        height: size,
        flex: `0 0 ${size}px`,
        borderRadius: Math.round(size * 0.22),
        background: brand.color,
        color: '#fff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize,
        fontWeight: 600,
        lineHeight: 1,
        userSelect: 'none',
        letterSpacing: -0.5,
      }}
    >
      {text}
    </div>
  );
};

export default VendorLogo;