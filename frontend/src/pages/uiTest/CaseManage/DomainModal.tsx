import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Input, Modal, Space, Table, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { UiAllowedDomain } from '@/services/uiTest';

interface DomainModalProps {
  open: boolean;
  projectId?: number;
  env?: number;
  onCancel: () => void;
  onChanged?: () => void;
}

/**
 * 允许域名(SSRF 白名单)的就地配置
 *
 * **白名单为空 = 该项目的 UI 用例不可执行**(不是「允许全部」)——
 * 这是刻意选的失败方向, 宁可跑不了, 也不能让平台裸奔到内网。
 *
 * 增删需要 ADMIN 权限, 普通用户会拿到 403 —— 这里如实提示, 不假装成功。
 */
const DomainModal: React.FC<DomainModalProps> = (props) => {
  const { open, projectId, env, onCancel, onChanged } = props;
  const { domains, fetchDomains, saveDomain, removeDomain, saving } = useModel('uiTest');
  const [input, setInput] = useState('');

  useEffect(() => {
    if (!open || !projectId) return;
    fetchDomains(projectId, env);
  }, [open, projectId, env, fetchDomains]);

  const onAdd = useCallback(async () => {
    const value = input.trim();
    if (!value) {
      message.info('请输入域名');
      return;
    }
    const ok = await saveDomain({ project_id: projectId, domain: value, env: env ?? null });
    if (ok) {
      setInput('');
      fetchDomains(projectId as number, env);
      onChanged?.();
    }
  }, [input, projectId, env, saveDomain, fetchDomains, onChanged]);

  const columns = [
    { title: '域名', dataIndex: 'domain', key: 'domain' },
    {
      title: '生效环境',
      dataIndex: 'env',
      key: 'env',
      width: 120,
      render: (value?: number) => (value === null || value === undefined ? '所有环境' : String(value)),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, record: UiAllowedDomain) => (
        <a
          onClick={async () => {
            const ok = await removeDomain(record.id);
            if (ok) fetchDomains(projectId as number, env);
          }}
        >
          删除
        </a>
      ),
    },
  ];

  return (
    <Modal open={open} title="允许访问的域名" onCancel={onCancel} footer={null} width={680}>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        message="这是 UI 用例的出网边界"
        description={
          <span>
            只有白名单里的域名才能被访问, 且域名解析到的地址不能是内网 / 环回 / 链路本地地址。
            <br />
            白名单为空时, 本项目的 UI 用例**不可执行**(不是「允许全部」)。
            <br />
            域名只填裸域名(如 example.com), 支持 *.example.com 形式的子域通配。
          </span>
        }
      />
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input
          placeholder="example.com"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={onAdd}
        />
        <Button type="primary" icon={<PlusOutlined />} loading={saving} onClick={onAdd}>
          添加
        </Button>
      </Space.Compact>
      <Table
        rowKey="id"
        size="small"
        columns={columns as any}
        dataSource={domains}
        pagination={false}
        locale={{ emptyText: '还没有配置任何域名' }}
      />
    </Modal>
  );
};

export default DomainModal;
