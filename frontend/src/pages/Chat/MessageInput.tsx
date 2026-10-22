import React, { useState } from 'react';
import { Button, Input, message as antdMessage, Space, Tooltip } from 'antd';
import {
  PaperClipOutlined,
  SearchOutlined,
  SendOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';

const { TextArea } = Input;

// 优化提问: 纯前端模板版, 零延迟。接 LLM 润色可以后续再加
const OPTIMIZE_PREFIX =
  '请详细分析下面的问题, 补充我可能遗漏的关键信息, 并给出可执行的解决方案:\n\n';

interface Props {
  disabled?: boolean;
  streaming?: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
}

const MessageInput: React.FC<Props> = ({ disabled, streaming, onSend, onStop }) => {
  const [value, setValue] = useState('');

  const send = () => {
    const text = value.trim();
    if (!text) return;
    onSend(text);
    setValue('');
  };

  const onOptimize = () => {
    if (!value.trim()) {
      antdMessage.info('请先输入你的问题');
      return;
    }
    setValue(value.trim().startsWith(OPTIMIZE_PREFIX) ? value : OPTIMIZE_PREFIX + value);
  };

  return (
    <div className="chat-input">
      <TextArea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoSize={{ minRows: 2, maxRows: 8 }}
        placeholder="输入消息... (Enter 发送, Shift + Enter 换行)"
        disabled={disabled}
        onPressEnter={(e) => {
          // antd 的 rc-textarea 已处理输入法组合期(isComposing 时不触发), 这里只判 shift
          if (!e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
      />
      <div className="chat-input-toolbar">
        <Space size={4}>
          <Tooltip title="联网搜索(开发中)">
            <Button
              type="text"
              icon={<SearchOutlined />}
              onClick={() => antdMessage.info('联网搜索功能开发中')}
            />
          </Tooltip>
          <Tooltip title="优化提问">
            <Button type="text" icon={<ThunderboltOutlined />} onClick={onOptimize} disabled={disabled} />
          </Tooltip>
          <Tooltip title="添加附件(开发中)">
            <Button
              type="text"
              icon={<PaperClipOutlined />}
              onClick={() => antdMessage.info('附件功能开发中')}
            />
          </Tooltip>
        </Space>
        {streaming ? (
          <Button danger icon={<StopOutlined />} onClick={onStop}>
            停止生成
          </Button>
        ) : (
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={send}
            disabled={disabled || !value.trim()}
          >
            发送
          </Button>
        )}
      </div>
      <div className="chat-input-tip">Enter 发送, Shift + Enter 换行</div>
    </div>
  );
};

export default MessageInput;