import React from 'react';
import { Avatar, Button, Empty, Input, Popconfirm, Typography } from 'antd';
import { DeleteOutlined, MessageOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import moment from 'moment';
import { ChatSession } from '@/services/chat';

interface Props {
  sessions: ChatSession[];
  currentId: number | null;
  keyword: string;
  onKeywordChange: (v: string) => void;
  onSelect: (id: number) => void;
  onCreate: () => void;
  onDelete: (id: number) => void;
}

const ChatList: React.FC<Props> = ({
  sessions,
  currentId,
  keyword,
  onKeywordChange,
  onSelect,
  onCreate,
  onDelete,
}) => {
  return (
    <div className="chat-list">
      <div className="chat-list-header">
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: 'rgba(0,0,0,0.25)' }} />}
          placeholder="搜索对话"
          value={keyword}
          onChange={(e) => onKeywordChange(e.target.value)}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate} block>
          新建对话
        </Button>
      </div>

      <div className="chat-list-body">
        {sessions.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={keyword ? '没有匹配的会话' : '还没有会话'}
            style={{ marginTop: 40 }}
          />
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`chat-list-item${s.id === currentId ? ' active' : ''}`}
              onClick={() => onSelect(s.id)}
            >
              <Avatar
                size={32}
                style={{ background: '#e6f4ff', color: '#1677ff', flex: '0 0 32px' }}
                icon={<MessageOutlined />}
              />
              <div className="chat-list-meta">
                <div className="chat-list-title">
                  <Typography.Text ellipsis style={{ maxWidth: 150 }}>
                    {s.title}
                  </Typography.Text>
                </div>
                <div className="chat-list-sub">
                  <Typography.Text type="secondary" ellipsis style={{ maxWidth: 175 }}>
                    {s.preview || '暂无消息'}
                  </Typography.Text>
                  <Typography.Text type="secondary" className="chat-list-time">
                    {s.updated_at ? moment(s.updated_at).fromNow() : ''}
                  </Typography.Text>
                </div>
              </div>
              {/* 确认浮层渲染在 body 上, 不会冒泡到外层; 这里只需阻止删除按钮本身触发选中 */}
              <Popconfirm
                title="确定要删除这个会话吗?"
                okText="删除"
                cancelText="取消"
                onConfirm={() => onDelete(s.id)}
              >
                <Button
                  type="text"
                  size="small"
                  icon={<DeleteOutlined style={{ color: '#ff4d4f' }} />}
                  onClick={(e) => e.stopPropagation()}
                />
              </Popconfirm>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default ChatList;