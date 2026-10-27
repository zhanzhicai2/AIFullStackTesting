import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tree,
  message,
} from 'antd';
import { FolderAddOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { listProject } from '@/services/project';
import { insertTestcaseDirectory, listTestcaseTree } from '@/services/testcase';
import { UiCase } from '@/services/uiTest';
import CaseEditor from './CaseEditor';
import '../UiTest.less';

interface Option {
  label: string;
  value: number;
}

const PRIORITY_TAGS: Record<string, string> = {
  P0: 'red',
  P1: 'orange',
  P2: 'blue',
  P3: 'default',
  P4: 'default',
};

/**
 * UI 用例管理
 *
 * 目录树与接口用例**共用**既有的 `pity_testcase_directory` —— 测试计划可以同时选两类用例,
 * 报告统计也统一。左侧是目录, 右边是该目录下的 UI 用例。
 */
const UiCaseManage: React.FC = () => {
  const { cases, loading, saving, fetchCases, removeCase } = useModel('uiTest');

  const [projectId, setProjectId] = useState<number | undefined>();
  const [projectOptions, setProjectOptions] = useState<Option[]>([]);
  const [directoryId, setDirectoryId] = useState<number | undefined>();
  const [directoryTree, setDirectoryTree] = useState<any[]>([]);
  const [dirModalOpen, setDirModalOpen] = useState(false);
  const [dirForm] = Form.useForm();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingCaseId, setEditingCaseId] = useState<number | undefined>();

  useEffect(() => {
    listProject({ page: 1, size: 100 })
      .then((res: any) => {
        if (res?.code === 0) {
          const options = (res.data || []).map((p: any) => ({ label: p.name, value: p.id }));
          setProjectOptions(options);
          if (options.length > 0) setProjectId(options[0].value);
        }
      })
      .catch(() => undefined);
  }, []);

  const loadDirectories = useCallback((pid: number) => {
    listTestcaseTree({ project_id: pid })
      .then((res: any) => {
        if (res?.code === 0) setDirectoryTree(res.data || []);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!projectId) return;
    loadDirectories(projectId);
    setDirectoryId(undefined);
  }, [projectId, loadDirectories]);

  useEffect(() => {
    if (!projectId) return;
    fetchCases({ project_id: projectId, directory_id: directoryId });
  }, [projectId, directoryId, fetchCases]);

  const directoryOptions = useMemo(() => {
    const options: Option[] = [];
    const walk = (nodes: any[]) => {
      nodes.forEach((n) => {
        options.push({ label: n.title, value: n.key });
        if (n.children?.length) walk(n.children);
      });
    };
    walk(directoryTree);
    return options;
  }, [directoryTree]);

  const onCreateDirectory = async (values: any) => {
    const res = await insertTestcaseDirectory({
      name: values.name,
      project_id: projectId,
      parent: values.parent || null,
    });
    if (res?.code === 0) {
      message.success('目录创建成功');
      setDirModalOpen(false);
      dirForm.resetFields();
      if (projectId) loadDirectories(projectId);
    } else {
      message.error(res?.msg || '目录创建失败');
    }
  };

  const columns = [
    { title: '编号', dataIndex: 'id', key: 'id', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '所属模块',
      dataIndex: 'directory_id',
      key: 'directory_id',
      width: 160,
      render: (value: number) =>
        directoryOptions.find((o) => o.value === value)?.label || '-',
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 90,
      render: (value: string) => <Tag color={PRIORITY_TAGS[value]}>{value}</Tag>,
    },
    { title: '类型', key: 'type', width: 90, render: () => <Tag color="purple">Web UI</Tag> },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (value: number) => (
        <Tag color={value === 3 ? 'green' : value === 1 ? 'blue' : 'default'}>
          {value === 3 ? '正常运作' : value === 1 ? '调试中' : '暂时关闭'}
        </Tag>
      ),
    },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170 },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_: unknown, record: UiCase) => (
        <Space>
          <a
            onClick={() => {
              setEditingCaseId(record.id);
              setEditorOpen(true);
            }}
          >
            编辑
          </a>
          <a
            onClick={() =>
              Modal.confirm({
                title: `确定删除用例「${record.name}」吗?`,
                content: '删除后该用例的执行记录仍会保留',
                onOk: () => removeCase(record.id),
              })
            }
          >
            删除
          </a>
        </Space>
      ),
    },
  ];

  return (
    <div className="ui-page">
      <Row gutter={12}>
        <Col span={6}>
          <Card
            bordered={false}
            title="目录"
            extra={
              <Space>
                <Button
                  size="small"
                  type="text"
                  icon={<ReloadOutlined />}
                  onClick={() => projectId && loadDirectories(projectId)}
                />
                <Button
                  size="small"
                  type="text"
                  icon={<FolderAddOutlined />}
                  disabled={!projectId}
                  onClick={() => {
                    dirForm.resetFields();
                    setDirModalOpen(true);
                  }}
                />
              </Space>
            }
          >
            <Select
              style={{ width: '100%', marginBottom: 8 }}
              placeholder="选择项目"
              value={projectId}
              options={projectOptions}
              onChange={(value) => setProjectId(value)}
            />
            {/* U3: 项目下没有目录时, 在目录选择器旁就地给「新建目录」入口 */}
            {directoryOptions.length === 0 ? (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="该项目下还没有目录"
                description={
                  <a onClick={() => setDirModalOpen(true)}>新建目录</a>
                }
              />
            ) : null}
            {directoryOptions.length === 0 ? null : (
              <Tree
                treeData={directoryTree}
                selectedKeys={directoryId ? [directoryId] : []}
                onSelect={(keys) =>
                  setDirectoryId(keys.length ? (keys[0] as number) : undefined)
                }
              />
            )}
          </Card>
        </Col>
        <Col span={18}>
          <Card
            bordered={false}
            title="UI 用例"
            extra={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                disabled={!projectId}
                onClick={() => {
                  setEditingCaseId(undefined);
                  setEditorOpen(true);
                }}
              >
                新建用例
              </Button>
            }
          >
            {directoryOptions.length === 0 ? (
              <div className="ui-empty-hint">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    <span>
                      先建一个目录, 用例要挂在目录下
                      <br />
                      <a onClick={() => setDirModalOpen(true)}>新建目录</a>
                    </span>
                  }
                />
              </div>
            ) : (
              <Table
                rowKey="id"
                size="small"
                loading={loading}
                columns={columns as any}
                dataSource={cases}
                pagination={false}
                scroll={{ y: 480 }}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        open={dirModalOpen}
        title="新建目录"
        onCancel={() => setDirModalOpen(false)}
        onOk={() => dirForm.submit()}
        destroyOnClose
      >
        <Form form={dirForm} layout="vertical" onFinish={onCreateDirectory} preserve={false}>
          <Form.Item name="name" label="目录名" rules={[{ required: true, message: '请输入目录名' }]}>
            <Input placeholder="例如 登录流程" maxLength={18} />
          </Form.Item>
          <Form.Item name="parent" label="上级目录">
            <Select
              allowClear
              placeholder="不选就是顶级目录"
              options={directoryOptions.map((o) => ({ label: o.label, value: o.value }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {editorOpen ? (
        <CaseEditor
          open={editorOpen}
          caseId={editingCaseId}
          projectId={projectId}
          directoryId={directoryId}
          directoryOptions={directoryOptions}
          saving={saving}
          onCancel={() => {
            setEditorOpen(false);
            setEditingCaseId(undefined);
          }}
          onSaved={() => {
            if (projectId) fetchCases({ project_id: projectId, directory_id: directoryId });
          }}
          onDirectoriesChanged={() => {
            if (projectId) loadDirectories(projectId);
          }}
        />
      ) : null}
    </div>
  );
};

export default UiCaseManage;
