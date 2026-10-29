import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Input,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { AiDraftSummary } from '@/services/aiWorkbench';
import { AI_ASSERT_TYPES, AI_DRAFT_STATUS, AI_DRAFT_STATUS_LABEL } from '@/consts/aiWorkbench';

const { Text, Paragraph } = Typography;

export interface DraftDrawerProps {
  open: boolean;
  draft: AiDraftSummary | null;
  /** 草稿的完整 DSL(后端返回) */
  content?: Record<string, unknown> | null;
  saving?: boolean;
  onClose: () => void;
  onSave: (content: Record<string, unknown>) => Promise<string[] | null> | void;
}

/**
 * 单条草稿详情 —— 可视化 + 编辑
 *
 * 前端**只做提前告知**, 不代替后端裁决(契约 dsl.md §8):
 * 保存后由后端重新过一遍 14 条校验规则, 告警逐条回显。
 */
const DraftDrawer: React.FC<DraftDrawerProps> = ({
  open,
  draft,
  content,
  saving,
  onClose,
  onSave,
}) => {
  const [text, setText] = useState('');
  const [warn, setWarn] = useState<string[]>([]);
  const [jsonError, setJsonError] = useState('');

  useEffect(() => {
    if (open && content) {
      setText(JSON.stringify(content, null, 2));
      setJsonError('');
      setWarn(draft?.warn || []);
    }
  }, [open, content, draft]);

  if (!draft) return null;

  const caseItem = ((content as any)?.cases || [])[0] || {};
  const request = caseItem.request || {};
  const ui = caseItem.ui || {};

  const handleSave = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text);
    } catch (e: any) {
      setJsonError(`JSON 格式不正确: ${e?.message}`);
      return;
    }
    setJsonError('');
    const result = await onSave(parsed);
    if (Array.isArray(result)) {
      setWarn(result);
      message.success(result.length ? '已保存, 但仍有校验告警' : '已保存');
    }
  };

  return (
    <Drawer
      title={`草稿详情 · ${draft.title}`}
      width={720}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onClose}>关闭</Button>
          <Button type="primary" loading={saving} onClick={handleSave}>
            保存
          </Button>
        </Space>
      }
    >
      <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="编码">{draft.code}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag>{AI_DRAFT_STATUS_LABEL[draft.status] || draft.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="优先级">{draft.priority}</Descriptions.Item>
        <Descriptions.Item label="类别">{draft.category}</Descriptions.Item>
        <Descriptions.Item label="步骤数">{draft.steps}</Descriptions.Item>
        <Descriptions.Item label="正式用例">
          {draft.case_id ? `已采纳 (#${draft.case_id})` : '未采纳'}
        </Descriptions.Item>
      </Descriptions>

      {warn.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="校验告警 —— 采纳前必须处理"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {warn.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          }
        />
      ) : null}

      {draft.status !== AI_DRAFT_STATUS.PENDING ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="该草稿已采纳或已驳回, 内容已冻结, 不可修改"
        />
      ) : null}

      <Tabs
        items={[
          {
            key: 'view',
            label: '用例内容',
            children: (
              <div>
                {caseItem.ui ? (
                  <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
                    <Descriptions.Item label="起始地址">{ui.base_url}</Descriptions.Item>
                    <Descriptions.Item label="视口">{ui.viewport || '1280x720'}</Descriptions.Item>
                    <Descriptions.Item label="单步超时">{(ui.timeout || 30) + ' 秒'}</Descriptions.Item>
                    <Descriptions.Item label="步骤数">{(ui.steps || []).length}</Descriptions.Item>
                  </Descriptions>
                ) : (
                  <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
                    <Descriptions.Item label="请求方法">{request.method}</Descriptions.Item>
                    <Descriptions.Item label="请求地址">{request.url}</Descriptions.Item>
                    <Descriptions.Item label="请求体类型">{request.body_type}</Descriptions.Item>
                    <Descriptions.Item label="请求头">
                      <Text code>{request.headers ? JSON.stringify(request.headers) : '-'}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="请求体">
                      <Text code>{request.body ? JSON.stringify(request.body) : '-'}</Text>
                    </Descriptions.Item>
                  </Descriptions>
                )}

                <Paragraph strong>出参</Paragraph>
                {(caseItem.out_parameters || []).length === 0 ? (
                  <Text type="secondary">无</Text>
                ) : (
                  <ul>
                    {(caseItem.out_parameters || []).map((item: any) => (
                      <li key={item.name}>
                        <Text code>{item.name}</Text> ← {item.expression || '-'} (source={item.source})
                      </li>
                    ))}
                  </ul>
                )}

                <Paragraph strong>断言</Paragraph>
                {(caseItem.asserts || []).length === 0 ? (
                  <Text type="secondary">无</Text>
                ) : (
                  <ul>
                    {(caseItem.asserts || []).map((item: any) => (
                      <li key={item.name}>
                        {item.name}: {AI_ASSERT_TYPES[item.assert_type] || item.assert_type} — 预期{' '}
                        <Text code>{item.expected}</Text>, 实际 <Text code>{item.actually}</Text>
                      </li>
                    ))}
                  </ul>
                )}

                {(caseItem.pre_conditions || []).length +
                  (caseItem.post_conditions || []).length >
                0 ? (
                  <>
                    <Paragraph strong>前后置步骤</Paragraph>
                    <ul>
                      {(caseItem.pre_conditions || []).map((item: any, index: number) => (
                        <li key={`pre-${index}`}>前置: {item.name}</li>
                      ))}
                      {(caseItem.post_conditions || []).map((item: any, index: number) => (
                        <li key={`post-${index}`}>后置: {item.name}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            ),
          },
          {
            key: 'dsl',
            label: 'DSL 编辑',
            children: (
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  这是用例 DSL 的完整 JSON —— 也是草稿的存储格式。保存时后端会重新过一遍 14 条
                  校验规则, 不合规的字段会被丢弃并回显告警。
                </Text>
                <Input.TextArea
                  rows={22}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  style={{ marginTop: 8, fontFamily: 'monospace' }}
                  disabled={draft.status !== AI_DRAFT_STATUS.PENDING}
                />
                {jsonError ? (
                  <Alert type="error" showIcon style={{ marginTop: 8 }} message={jsonError} />
                ) : null}
              </div>
            ),
          },
        ]}
      />
    </Drawer>
  );
};

export default DraftDrawer;
