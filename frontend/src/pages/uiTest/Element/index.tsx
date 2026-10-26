import React, { useEffect, useMemo, useState } from 'react';
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
  Switch,
  Table,
  Tag,
  Tree,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { listProject } from '@/services/project';
import { uiStrategyLabel } from '@/consts/uiTest';
import { UiElement, UiPage } from '@/services/uiTest';
import ElementModal from './ElementModal';
import '../UiTest.less';

interface Option {
  label: string;
  value: number;
}

/**
 * 元素库
 *
 * 左树右表: 左边是页面树(元素归属哪个页面), 右边是该页面下的元素。
 * 步骤引用的是「页面名.元素名」, 所以页面是元素的命名空间。
 */
const UiElementPage: React.FC = () => {
  const { pages, elements, loading, saving, fetchPages, savePage, removePage, fetchElements, saveElement, removeElement, toggleElementStatus } =
    useModel('uiTest');

  const [projectId, setProjectId] = useState<number | undefined>();
  const [projectOptions, setProjectOptions] = useState<Option[]>([]);
  const [selectedPageId, setSelectedPageId] = useState<number | undefined>();
  const [pageModalOpen, setPageModalOpen] = useState(false);
  const [editingPage, setEditingPage] = useState<UiPage | null>(null);
  const [elementModalOpen, setElementModalOpen] = useState(false);
  const [editingElement, setEditingElement] = useState<UiElement | null>(null);
  const [pageForm] = Form.useForm();

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

  // 页面树跟着项目走
  useEffect(() => {
    if (!projectId) return;
    fetchPages(projectId);
  }, [projectId, fetchPages]);

  // 元素列表跟着选中的页面走
  useEffect(() => {
    if (!projectId) return;
    fetchElements({ project_id: projectId, page_id: selectedPageId });
  }, [projectId, selectedPageId, fetchElements]);

  const treeData = useMemo(() => {
    const nodes = new Map<number, any>();
    pages.forEach((p) => {
      nodes.set(p.id, { key: p.id, title: p.name, children: [] });
    });
    const roots: any[] = [];
    pages.forEach((p) => {
      const node = nodes.get(p.id);
      const parent = p.parent ? nodes.get(p.parent) : undefined;
      if (parent) parent.children.push(node);
      else roots.push(node);
    });
    return roots;
  }, [pages]);

  const currentPage = useMemo(
    () => pages.find((p) => p.id === selectedPageId),
    [pages, selectedPageId]
  );

  const onSavePage = async (values: any) => {
    const ok = await savePage({
      id: editingPage?.id,
      project_id: projectId,
      name: values.name,
      url: values.url,
      parent: values.parent || null,
      description: values.description || '',
    });
    if (ok) {
      setPageModalOpen(false);
      pageForm.resetFields();
    }
  };

  const onRemovePage = (page: UiPage) => {
    Modal.confirm({
      title: `确定删除页面「${page.name}」吗?`,
      content: '页面下的元素不会删除, 会转为停用, 引用它们的用例仍会保留步骤',
      onOk: async () => {
        const ok = await removePage(page.id, projectId as number);
        if (ok && selectedPageId === page.id) setSelectedPageId(undefined);
      },
    });
  };

  const onSaveElement = async (values: any) => {
    const ok = await saveElement({
      id: editingElement?.id,
      project_id: projectId,
      page_id: selectedPageId,
      name: values.name,
      strategy: values.strategy,
      locator: values.locator,
      name_attr: values.name_attr || null,
      description: values.description || '',
    });
    if (ok) {
      setElementModalOpen(false);
      setEditingElement(null);
    }
  };

  const columns = [
    { title: '元素名', dataIndex: 'name', key: 'name' },
    {
      title: '定位策略',
      dataIndex: 'strategy',
      key: 'strategy',
      width: 120,
      render: (value: string) => <Tag>{uiStrategyLabel(value)}</Tag>,
    },
    { title: '定位值', dataIndex: 'locator', key: 'locator', ellipsis: true },
    {
      title: '可访问名称',
      dataIndex: 'name_attr',
      key: 'name_attr',
      width: 140,
      render: (value?: string) => value || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (value: number, record: UiElement) => (
        <Switch
          checked={value === 1}
          checkedChildren="启用"
          unCheckedChildren="停用"
          onChange={(checked) => toggleElementStatus(record.id, projectId as number, checked ? 1 : 0)}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, record: UiElement) => (
        <Space>
          <a
            onClick={() => {
              setEditingElement(record);
              setElementModalOpen(true);
            }}
          >
            编辑
          </a>
          <a
            onClick={() =>
              Modal.confirm({
                title: `确定删除元素「${record.name}」吗?`,
                content: '删除后引用它的步骤会在执行时报「元素不存在或已停用」',
                onOk: () => removeElement(record.id, projectId as number),
              })
            }
          >
            删除
          </a>
        </Space>
      ),
    },
  ];

  // 元素库为空 —— 就地指引(U4), 而不是只甩一个错误码
  const emptyLibrary = pages.length === 0 || elements.length === 0;

  return (
    <div className="ui-page">
      <Row gutter={12}>
        <Col span={6}>
          <Card
            bordered={false}
            title="页面"
            extra={
              <Space>
                <Button
                  size="small"
                  type="text"
                  icon={<ReloadOutlined />}
                  onClick={() => projectId && fetchPages(projectId)}
                />
                <Button
                  size="small"
                  type="text"
                  icon={<PlusOutlined />}
                  disabled={!projectId}
                  onClick={() => {
                    setEditingPage(null);
                    pageForm.resetFields();
                    setPageModalOpen(true);
                  }}
                />
              </Space>
            }
          >
            <Select
              style={{ width: '100%', marginBottom: 12 }}
              placeholder="选择项目"
              value={projectId}
              options={projectOptions}
              onChange={(value) => {
                setProjectId(value);
                setSelectedPageId(undefined);
              }}
            />
            {pages.length === 0 ? (
              <div className="ui-empty-hint">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    <span>
                      还没有页面
                      <br />
                      <a onClick={() => setPageModalOpen(true)}>新建第一个页面</a>
                    </span>
                  }
                />
              </div>
            ) : (
              <Tree
                treeData={treeData}
                selectedKeys={selectedPageId ? [selectedPageId] : []}
                onSelect={(keys) => setSelectedPageId(keys.length ? (keys[0] as number) : undefined)}
                titleRender={(node: any) => {
                  const page = pages.find((p) => p.id === node.key);
                  return (
                    <span>
                      {node.title}
                      {node.children?.length ? ` (${node.children.length})` : ''}
                      {page ? (
                        <Space size={4} style={{ marginLeft: 6 }}>
                          <a
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditingPage(page);
                              pageForm.setFieldsValue({
                                name: page.name,
                                url: page.url,
                                parent: page.parent,
                                description: page.description,
                              });
                              setPageModalOpen(true);
                            }}
                          >
                            编辑
                          </a>
                          <a
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemovePage(page);
                            }}
                          >
                            删除
                          </a>
                        </Space>
                      ) : null}
                    </span>
                  );
                }}
              />
            )}
          </Card>
        </Col>
        <Col span={18}>
          <Card
            bordered={false}
            title={currentPage ? `元素 · ${currentPage.name}` : '元素'}
            extra={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                disabled={!selectedPageId}
                onClick={() => {
                  setEditingElement(null);
                  setElementModalOpen(true);
                }}
              >
                新建元素
              </Button>
            }
          >
            {!selectedPageId ? (
              <div className="ui-empty-hint">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="先在左边选一个页面, 元素归属于页面"
                />
              </div>
            ) : emptyLibrary ? (
              <Alert
                type="info"
                showIcon
                message="元素库为空"
                description={
                  <span>
                    元素库为空, 先沉淀页面与元素。
                    <br />
                    用例步骤引用的是「页面名.元素名」, 没有元素就没法写可维护的步骤。
                  </span>
                }
                action={
                  <Button size="small" type="primary" onClick={() => setElementModalOpen(true)}>
                    新建元素
                  </Button>
                }
              />
            ) : (
              <Table
                rowKey="id"
                size="small"
                loading={loading}
                columns={columns as any}
                dataSource={elements}
                pagination={false}
                scroll={{ y: 480 }}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        open={pageModalOpen}
        title={editingPage?.id ? '编辑页面' : '新建页面'}
        onCancel={() => setPageModalOpen(false)}
        onOk={() => pageForm.submit()}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={pageForm} layout="vertical" onFinish={onSavePage} preserve={false}>
          <Form.Item name="name" label="页面名" rules={[{ required: true, message: '请输入页面名' }]}>
            <Input placeholder="例如 登录页" maxLength={64} />
          </Form.Item>
          <Form.Item name="url" label="页面地址">
            <Input placeholder="例如 https://example.com/login" />
          </Form.Item>
          <Form.Item name="parent" label="上级页面">
            <Select
              allowClear
              placeholder="不选就是顶级页面"
              options={pages
                .filter((p) => p.id !== editingPage?.id)
                .map((p) => ({ label: p.name, value: p.id }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={255} />
          </Form.Item>
        </Form>
      </Modal>

      <ElementModal
        open={elementModalOpen}
        element={editingElement}
        saving={saving}
        onCancel={() => {
          setElementModalOpen(false);
          setEditingElement(null);
        }}
        onSubmit={onSaveElement}
      />
    </div>
  );
};

export default UiElementPage;
