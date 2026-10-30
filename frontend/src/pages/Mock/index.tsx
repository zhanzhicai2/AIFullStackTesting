import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  message,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CopyOutlined,
  ExperimentOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { listProject } from '@/services/project';
import CONFIG from '@/consts/config';
import { MOCK_METHOD_COLORS, MOCK_METHODS, MOCK_PATH_TYPE_LABELS } from '@/consts/mock';
import { MockRule, MockRuleForm } from '@/services/mock';
import RuleFormModal from './RuleFormModal';
import DebugModal from './DebugModal';
import './Mock.less';

const { Text } = Typography;

interface ProjectOption {
  id: number;
  name: string;
  app: string;
}

/**
 * Mock 配置页
 *
 * 左侧(顶部)选择项目 → 展示 mock 基地址 → 规则表格。
 * 就地指引(constitution 原则 IV):
 *  G1 未选项目 → 提示选择并给项目入口
 *  G2 项目 app 为空 → 提示补全(基地址不可用)
 *  G3 项目下无规则 → 空态展示"被测系统如何调用 mock 服务"使用引导
 *  G4 app 被多项目占用 → 提示命中最早创建的项目
 */
const MockPage: React.FC = () => {
  const {
    projectId,
    rules,
    total,
    loading,
    page,
    size,
    filters,
    fetchRules,
    changeProject,
    applyFilters,
    addRule,
    editRule,
    removeRule,
    toggleRule,
    preview,
  } = useModel('mock');

  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<MockRule | null>(null);
  const [saving, setSaving] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);

  // ---- 项目列表(含 app) ----
  useEffect(() => {
    listProject({ page: 1, size: 200 })
      .then((res: any) => {
        if (res?.code === 0) {
          const list: ProjectOption[] = (res.data || []).map((item: any) => ({
            id: item.id,
            name: item.name,
            app: item.app || '',
          }));
          setProjects(list);
        }
      })
      .catch(() => undefined);
  }, []);

  const currentProject = useMemo(
    () => projects.find((p) => p.id === projectId),
    [projects, projectId],
  );

  // ---- G4: app 重复检测 ----
  const appConflict = useMemo(() => {
    if (!currentProject || !currentProject.app) return false;
    return projects.filter((p) => p.app === currentProject.app).length > 1;
  }, [currentProject, projects]);

  // ---- mock 基地址 ----
  const mockBase = currentProject?.app ? `${CONFIG.URL}/mock/${currentProject.app}/` : '';

  const handleCopy = useCallback(() => {
    const text = `curl "${mockBase}api/user/1"`;
    // 简单文本复制(Clipboard API)
    navigator.clipboard?.writeText(text).then(
      () => message.success('示例已复制'),
      () => message.error('复制失败, 请手动复制'),
    );
  }, [mockBase]);

  const handleSubmit = async (form: MockRuleForm): Promise<string | undefined> => {
    setSaving(true);
    try {
      let warn: string | undefined;
      if (editing) {
        await editRule(form);
      } else {
        warn = await addRule(form);
      }
      message.success(warn || '操作成功');
      setFormOpen(false);
      setEditing(null);
      return warn;
    } catch (e: any) {
      message.error(e?.message || '操作失败');
      return undefined;
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (id: number, status: number) => {
    try {
      await toggleRule(id, status);
    } catch (e: any) {
      message.error(e?.message || '操作失败');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await removeRule(id);
      message.success('删除成功');
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  const columns = [
    {
      title: '方法',
      dataIndex: 'method',
      width: 90,
      render: (m: string) => <Tag color={MOCK_METHOD_COLORS[m] || 'default'}>{m}</Tag>,
    },
    {
      title: '路径',
      dataIndex: 'path',
      ellipsis: true,
      render: (p: string, r: MockRule) => (
        <Tooltip title={p}>
          <Text code>{p}</Text>
          <Tag style={{ marginLeft: 8 }}>{MOCK_PATH_TYPE_LABELS[r.path_type]}</Tag>
        </Tooltip>
      ),
    },
    { title: '规则名', dataIndex: 'name', width: 140, ellipsis: true },
    { title: '状态码', dataIndex: 'status_code', width: 80 },
    { title: '延迟(ms)', dataIndex: 'delay', width: 90 },
    { title: '优先级', dataIndex: 'priority', width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: number, r: MockRule) => (
        <Switch
          size="small"
          checked={s === 1}
          onChange={(checked) => handleToggle(r.id, checked ? 1 : 0)}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, r: MockRule) => (
        <Space size="small">
          <Button size="small" icon={<ExperimentOutlined />} onClick={() => setDebugOpen(true)}>
            调试
          </Button>
          <Button
            size="small"
            onClick={() => {
              setEditing(r);
              setFormOpen(true);
            }}
          >
            编辑
          </Button>
          <Popconfirm title="删除该规则?" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="mock-page">
      <Card
        title="Mock 配置"
        extra={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => fetchRules()}
              disabled={!projectId}
            >
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!projectId}
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              新建规则
            </Button>
          </Space>
        }
      >
        {/* G1: 项目选择 */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Text>所属项目:</Text>
          <Select
            style={{ minWidth: 220 }}
            placeholder="请先选择项目"
            value={projectId}
            onChange={changeProject}
            options={projects.map((p) => ({ label: p.name, value: p.id }))}
            showSearch
            optionFilterProp="label"
          />
          {!projectId && (
            <Text type="warning">
              请先选择项目 —— Mock 规则按项目隔离, 未选择无法配置与查看。
            </Text>
          )}
        </Space>

        {/* G2: app 为空 */}
        {currentProject && !currentProject.app && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={`项目「${currentProject.name}」未配置应用名(app)`}
            description="mock 基地址不可用, 被测系统无法访问其规则。请到项目设置中补全「项目所属应用」字段。"
          />
        )}

        {/* G4: app 冲突 */}
        {appConflict && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={`应用名 ${currentProject?.app} 被多个项目使用`}
            description="mock 基地址将命中最早创建的项目, 请确认这不是预期外的复用。"
          />
        )}

        {/* 基地址展示(FR-010) */}
        {mockBase && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="被测系统调用地址"
            description={
              <Space wrap>
                <Text copyable={{ text: mockBase }}>{mockBase}</Text>
                <Text type="secondary">例: </Text>
                <Text code>{`curl "${mockBase}api/user/1"`}</Text>
                <Button size="small" icon={<CopyOutlined />} onClick={handleCopy}>
                  复制示例
                </Button>
              </Space>
            }
          />
        )}

        {/* 筛选 */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Select
            style={{ width: 120 }}
            allowClear
            placeholder="方法"
            value={filters.method}
            onChange={(v) => applyFilters({ ...filters, method: v })}
            options={MOCK_METHODS.map((m) => ({ label: m, value: m }))}
          />
          <Input
            style={{ width: 200 }}
            allowClear
            placeholder="路径关键字"
            value={filters.path}
            onChange={(e) => applyFilters({ ...filters, path: e.target.value || undefined })}
            onPressEnter={() => fetchRules()}
          />
          <Select
            style={{ width: 120 }}
            allowClear
            placeholder="状态"
            value={filters.status}
            onChange={(v) => applyFilters({ ...filters, status: v })}
            options={[
              { label: '启用', value: 1 },
              { label: '停用', value: 0 },
            ]}
          />
        </Space>

        {/* G3: 无规则空态 */}
        {projectId && rules.length === 0 && !loading && (
          <Empty
            style={{ margin: '24px 0' }}
            description={
              <span>
                项目下还没有 Mock 规则。点击右上角「新建规则」配置第一条 —— 被测系统即可通过
                <Text code>{`${CONFIG.URL}/mock/${currentProject?.app}/**`}</Text>
                获取假数据。
              </span>
            }
          />
        )}

        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rules}
          pagination={{
            current: page,
            pageSize: size,
            total,
            showSizeChanger: true,
            onChange: (p, s) => fetchRules(p, s),
          }}
        />
      </Card>

      <RuleFormModal
        open={formOpen}
        record={editing}
        projectId={projectId}
        saving={saving}
        onCancel={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSubmit={handleSubmit}
      />

      <DebugModal
        open={debugOpen}
        projectId={projectId}
        preview={preview}
        onCancel={() => setDebugOpen(false)}
      />
    </div>
  );
};

export default MockPage;
