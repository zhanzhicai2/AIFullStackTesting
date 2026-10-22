import React, { useEffect, useRef } from 'react';
import { Avatar, Spin, Typography } from 'antd';
import { MessageOutlined, RobotOutlined } from '@ant-design/icons';
// @ts-ignore bytemd Viewer 是 .jsx 文件, 没有类型声明
import Markdown from '@/components/CodeEditor/Markdown';
import { ChatMessage } from '@/services/chat';

interface Props {
  messages: ChatMessage[];
  streaming?: boolean;
}

// Markdown 组件签名是 ({value, setValue}), setValue 在只读场景必须给个占位,
// 否则内部 onChange 被触发时会炸
const noop = () => undefined;

const MessageList: React.FC<Props> = ({ messages, streaming }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="chat-messages-empty">
        <div className="chat-empty-icon">
          <MessageOutlined />
        </div>
        <Typography.Text type="secondary">开始新的对话</Typography.Text>
      </div>
    );
  }

  return (
    <div className="chat-messages">
      {messages.map((m, idx) => {
        const isUser = m.role === 'user';
        // 占位消息(id=-1)还没有任何内容时显示 loading, 避免出现一个空气泡
        const isPending = m.id === -1 && !m.content;
        // 正在生成的最后一条 assistant 消息, 追加一个闪烁光标提示还在输出
        const isStreamingTail =
          streaming && idx === messages.length - 1 && !isUser && !isPending;
        return (
          <div className={`chat-msg-row ${isUser ? 'user' : 'assistant'}`} key={m.id}>
            {!isUser && (
              <Avatar
                size={32}
                style={{ background: '#52c41a', flex: '0 0 32px' }}
                icon={<RobotOutlined />}
              />
            )}
            <div className="chat-msg-body">
              {!isUser && <div className="chat-msg-author">AI 助手</div>}
              <div className="chat-msg-bubble">
                {isPending ? (
                  <Spin size="small" />
                ) : isUser ? (
                  <div className="chat-msg-text">{m.content}</div>
                ) : (
                  <>
                    <Markdown value={m.content} setValue={noop} />
                    {isStreamingTail && <span className="chat-cursor" />}
                  </>
                )}
              </div>
            </div>
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
};

export default MessageList;