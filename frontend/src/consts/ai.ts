// 模型类型,与后端 app/enums/AIModelEnum.py 的 AIModelTypeEnum 保持一致
export const MODEL_TYPES = [
  { label: '对话chat', value: 'chat', color: 'blue' },
  { label: '向量embedding', value: 'embedding', color: 'purple' },
  { label: '重排序rerank', value: 'rerank', color: 'orange' },
  { label: '图像image', value: 'image', color: 'magenta' },
];

const MAP = MODEL_TYPES.reduce<Record<string, { label: string; color: string }>>(
  (acc, item) => {
    acc[item.value] = { label: item.label, color: item.color };
    return acc;
  },
  {}
);

export const modelTypeLabel = (value?: string): string => MAP[value || '']?.label || value || '未知';

export const modelTypeColor = (value?: string): string => MAP[value || '']?.color || 'default';

// 默认模型参数,齿轮弹窗的初始值
export const DEFAULT_MODEL_PARAMS = {
  temperature: 0.7,
  max_tokens: 2048,
  top_p: 0.9,
};