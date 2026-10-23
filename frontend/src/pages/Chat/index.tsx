import React, { useEffect, useMemo, useState } from 'react';
import { PageContainer } from '@ant-design/pro-components';
import { Empty, Select, Space, Typography } from 'antd';
import { useModel } from '@umijs/max';
import ChatList from './ChatList';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import VendorLogo from '@/pages/Ai/VendorLogo';
import './index.less';

const Chat: React.FC = () => {
  const {
    sessions,
    currentId,
    messages,
    vendors,
    streaming,
    fetchSessions,
    selectSession,
    createSession,
    removeSession,
    switchModel,
    fetchModels,
    sendMessage,
    stopStream,
  } = useModel('chat');

  const [keyword, setKeyword] = useState('');

  useEffect(() => {
    fetchSessions();
    fetchModels();
  }, []);

  // 会话量不大, 直接全量拉回来在前端过滤, 不走分页接口
  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return sessions;
    return sessions.filter((s) => (s.title || '').toLowerCase().includes(kw));
  }, [sessions, keyword]);

  const current = useMemo(() => sessions.find((s) => s.id === currentId), [sessions, currentId]);

  // 会话表存的是 model_name, Select 需要 id, 所以要按名称反查一次
  const modelKey = useMemo(() => {
    if (!current?.vendor_id || !current?.model_name) return undefined;
    const vendor = vendors.find((v) => v.vendor_id === current.vendor_id);
    const model = vendor?.models.find((m) => m.model_name === current.model_name);
    return model ? `${current.vendor_id}:${model.model_id}` : undefined;
  }, [current, vendors]);

  const modelOptions = useMemo(
    () =>
      vendors.map((v) => ({
        label: v.vendor_name,
        options: v.models.map((m) => ({
          value: `${v.vendor_id}:${m.model_id}`,
          // label 是 ReactNode 时 optionFilterProp="label" 会失效(内部 String() 得到
          // [object Object]), 必须额外给个字符串字段并把 optionFilterProp 指过去
          searchText: `${v.vendor_name} ${m.model_name}`,
          label: (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <VendorLogo code={v.vendor_code} name={v.vendor_name} size={16} />
              {m.model_name}
            </span>
          ),
        })),
      })),
    [vendors]
  );

  const selectedVendorId = useMemo(() => {
    if (!modelKey) return undefined;
    return Number(modelKey.split(':')[0]);
  }, [modelKey]);

  const selectedModelId = useMemo(() => {
    if (!modelKey) return undefined;
    return Number(modelKey.split(':')[1]);
  }, [modelKey]);

  return (
    <PageContainer
      title={false}
      breadcrumbRender={false}
      childrenContentStyle={{ padding: 12, height: 'calc(100vh - 128px)' }}
    >
      <div className="chat-container">
        {/* ---------- 左:会话列表 ---------- */}
        <ChatList
          sessions={filtered}
          currentId={currentId}
          keyword={keyword}
          onKeywordChange={setKeyword}
          onSelect={selectSession}
          onCreate={async () => {
            // 新会话默认带上当前选中的模型, 省得每次都要重选
            const created = await createSession(selectedVendorId, selectedModelId);
            if (created) setKeyword('');
          }}
          onDelete={removeSession}
        />

        {/* ---------- 右:对话区 ---------- */}
        <div className="chat-main">
          <div className="chat-header">
            <Typography.Text strong ellipsis style={{ maxWidth: 320 }}>
              {current?.title || '新会话'}
            </Typography.Text>
            <Space size={12}>
              <Typography.Text type="secondary">模型选择</Typography.Text>
              <Select
                style={{ width: 260 }}
                placeholder="选择模型"
                showSearch
                disabled={!currentId}
                options={modelOptions}
                optionFilterProp="searchText"
                value={modelKey}
                notFoundContent="还没有已启用的对话模型, 请联系管理员在「模型服务商」里启用"
                onChange={(v) => {
                  const [vendorId, modelId] = v.split(':').map(Number);
                  switchModel(currentId as number, vendorId, modelId);
                }}
              />
            </Space>
          </div>

          <div className="chat-body">
            {currentId ? (
              <MessageList messages={messages} streaming={streaming} />
            ) : (
              <div className="chat-messages-empty">
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="先新建一个会话开始提问吧" />
              </div>
            )}
          </div>

          <MessageInput
            disabled={!currentId}
            streaming={streaming}
            onStop={stopStream}
            onSend={(content) => sendMessage(content, selectedVendorId, selectedModelId)}
          />
        </div>
      </div>
    </PageContainer>
  );
};

export default Chat;