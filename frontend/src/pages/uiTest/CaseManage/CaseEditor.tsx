import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Table,
  Tag,
  message,
} from 'antd';
import {
  DeleteOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { history, useModel } from '@umijs/max';
import { listEnvironment } from '@/services/configure';
import { listGConfig } from '@/services/configure';
import { insertTestcaseDirectory } from '@/services/testcase';
import { UiStep, UiStepResult } from '@/services/uiTest';
import {
  UI_ACTION_GROUPS,
  UI_ACTION_MAP,
  UI_ERROR_REASONS,
  UI_STRATEGY_OPTIONS,
  UI_WAIT_STATES,
  uiStrategyLabel,
} from '@/consts/uiTest';
import DomainModal from './DomainModal';

interface Option {
  label: string;
  value: number;
}

interface CaseEditorProps {
  open: boolean;
  caseId?: number;
  projectId?: number;
  directoryId?: number;
  directoryOptions: Option[];
  saving?: boolean;
  onCancel: () => void;
  onSaved?: () => void;
  /** 新建目录后通知父级刷新目录树 */
  onDirectoriesChanged?: () => void;
}

// pity_testcase.name 是 String(32) —— 超长按既有列长度截断并回显告警(FR-035)
const MAX_CASE_NAME = 32;

const emptyStep = (): UiStep => ({
  action: 'click',
  element: undefined,
  by: undefined,
  value: undefined,
  name: undefined,
  text: undefined,
  url: undefined,
  state: undefined,
  timeout: undefined,
});

/**
 * UI 用例编辑器
 *
 * 步骤引用的是**元素库**里的元素(「页面名.元素名」), 而不是内联 locator ——
 * 页面改版时只改元素库一处。步骤 DSL 的动作白名单与定位策略以
 * `src/consts/uiTest.ts` 为准(后端 `app/core/ui_executor.py` 是权威定义),
 * 前端只做**提前提示**, 最终判定在后端。
 */
const CaseEditor: React.FC<CaseEditorProps> = (props) => {
  const { open, caseId, projectId, directoryId, directoryOptions, saving, onCancel, onSaved, onDirectoriesChanged } = props;
  const { loadCase, saveCase, executeCase, pages, elements, fetchPages, fetchElements, fetchDomains, domains, fetchNodes, running } =
    useModel('uiTest');

  const [form] = Form.useForm();
  // 提前声明 —— 下面的 effect 要拿它当依赖
  const nameValue = Form.useWatch('name', form);
  const baseUrlValue = Form.useWatch('base_url', form);
  const [envOptions, setEnvOptions] = useState<Option[]>([]);
  const [env, setEnv] = useState<number | undefined>();
  const [steps, setSteps] = useState<UiStep[]>([]);
  const [runResult, setRunResult] = useState<any>(null);
  const [runOpen, setRunOpen] = useState(false);
  const [domainOpen, setDomainOpen] = useState(false);
  const [globalVarMissing, setGlobalVarMissing] = useState(false);
  const [savedCaseId, setSavedCaseId] = useState<number | undefined>(caseId);
  const [nodeCount, setNodeCount] = useState(0);
  const [dirModalOpen, setDirModalOpen] = useState(false);
  const [dirForm] = Form.useForm();

  useEffect(() => {
    listEnvironment({ page: 1, size: 100 })
      .then((res: any) => {
        if (res?.code === 0) {
          const options = (res.data || []).map((e: any) => ({ label: e.name, value: e.id }));
          setEnvOptions(options);
          if (options.length > 0) setEnv(options[0].value);
        }
      })
      .catch(() => undefined);
  }, []);

  // 元素库: 页面 + 元素, 组成步骤可选的引用列表
  useEffect(() => {
    if (!open || !projectId) return;
    fetchPages(projectId);
    fetchElements({ project_id: projectId });
    fetchDomains(projectId, env);
  }, [open, projectId, env, fetchPages, fetchElements, fetchDomains]);

  // U6: 执行节点 —— 没有在线节点时不能执行
  useEffect(() => {
    if (!open) return;
    fetchNodes().then((list) => setNodeCount((list || []).filter((n) => n.status === 1).length));
  }, [open, fetchNodes]);

  // 编辑态: 载入已有用例
  useEffect(() => {
    if (!open || !caseId) return;
    loadCase(caseId).then((detail) => {
      if (!detail) return;
      form.setFieldsValue({
        name: detail.name,
        directory_id: detail.directory_id,
        priority: detail.priority,
        base_url: detail.base_url,
        viewport: detail.viewport,
        locale: detail.locale || 'en-US',
        timeout: detail.timeout,
      });
      setSteps((detail.steps || []).map((s) => ({ ...emptyStep(), ...s })));
      setSavedCaseId(caseId);
    });
  }, [open, caseId, loadCase, form]);

  // 新建态: 用例名空, 步骤给一条空的
  useEffect(() => {
    if (!open || caseId) return;
    form.setFieldsValue({
      name: '',
      directory_id: directoryId,
      priority: 'P1',
      base_url: '',
      viewport: '1280x720',
      locale: 'en-US',
      timeout: 30,
    });
    setSteps([emptyStep()]);
    setSavedCaseId(undefined);
  }, [open, caseId, directoryId, form]);

  // U2: ${ui_base_url} 全局变量没配 —— 提示并给出跳转入口
  useEffect(() => {
    if (!open) return;
    if (!baseUrlValue?.includes('${ui_base_url}') || !env) {
      setGlobalVarMissing(false);
      return;
    }
    listGConfig({ page: 1, size: 50, env, key: 'ui_base_url' })
      .then((res: any) => {
        const list = res?.code === 0 ? res.data || [] : [];
        setGlobalVarMissing(list.length === 0);
      })
      .catch(() => setGlobalVarMissing(false));
  }, [open, env, baseUrlValue]);

  /** 元素库里的有效引用(启用状态), 「页面名.元素名」 */
  const elementOptions = useMemo(() => {
    const pageMap = new Map<number, string>();
    pages.forEach((p) => pageMap.set(p.id, p.name));
    return elements
      .filter((e) => e.status === 1)
      .map((e) => {
        const pageName = pageMap.get(e.page_id) || '';
        return {
          value: `${pageName}.${e.name}`,
          label: `${pageName}.${e.name}`,
          element: e,
        };
      });
  }, [pages, elements]);

  const validReferences = useMemo(
    () => new Set(elementOptions.map((o) => o.value)),
    [elementOptions]
  );

  // FR-035: 用例名超长 —— 给出建议的截断结果, 而不是只报错
  const nameTooLong = (nameValue || '').length > MAX_CASE_NAME;
  const truncatedName = (nameValue || '').slice(0, MAX_CASE_NAME);

  // U1: 白名单为空 —— 该项目的 UI 用例不可执行
  const whitelistEmpty = domains.length === 0;
  // U6: 没有在线的执行节点 —— 同样不可执行
  const noNode = nodeCount === 0;

  // FR-010: 全部用内联定位 —— 提示建议纳入元素库
  const targetSteps = steps.filter((s) => UI_ACTION_MAP[s.action]?.target);
  const allInline =
    targetSteps.length > 0 && targetSteps.every((s) => !s.element && !!s.by);

  const updateStep = (index: number, patch: Partial<UiStep>) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const removeStep = (index: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== index));
  };

  const buildPayload = (values: any) => ({
    id: savedCaseId,
    project_id: projectId,
    directory_id: values.directory_id,
    name: values.name,
    priority: values.priority || 'P1',
    base_url: values.base_url,
    viewport: values.viewport || '1280x720',
    locale: values.locale || 'en-US',
    timeout: values.timeout || 30,
    steps: steps.map((s) => {
      const out: any = { action: s.action };
      if (s.element) out.element = s.element;
      if (s.by) out.by = s.by;
      if (s.value !== undefined && s.value !== null && s.value !== '') out.value = s.value;
      if (s.name) out.name = s.name;
      if (s.text) out.text = s.text;
      if (s.url) out.url = s.url;
      if (s.state) out.state = s.state;
      if (s.timeout !== undefined && s.timeout !== null) out.timeout = s.timeout;
      return out;
    }),
  });

  const onSubmit = async (values: any) => {
    const result = await saveCase(buildPayload(values));
    if (!result) return;
    setSavedCaseId(result.case_id);
    onSaved?.();
    message.success(
      result.warnings && result.warnings.length > 0
        ? `保存成功, 但有 ${result.warnings.length} 条提示`
        : '保存成功'
    );
  };

  const onDebug = async () => {
    let values: any;
    try {
      values = await form.validateFields();
    } catch (e) {
      return;
    }
    if (!savedCaseId) {
      const result = await saveCase(buildPayload(values));
      if (!result) return;
      setSavedCaseId(result.case_id);
      onSaved?.();
    }
    const res = await executeCase({ case_id: savedCaseId as number, env });
    if (res) setRunResult(res);
    setRunOpen(true);
  };

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
      // 建完即选中(U3)
      const created = (res.data || {}) as any;
      if (created?.id) {
        form.setFieldValue('directory_id', created.id);
      }
      onDirectoriesChanged?.();
    } else {
      message.error(res?.msg || '目录创建失败');
    }
  };

  const renderStepFields = (step: UiStep, index: number) => {
    const spec = UI_ACTION_MAP[step.action];
    if (!spec) return null;
    const canInline = spec.value === 'locator';
    const referenceMissing = !!step.element && !validReferences.has(step.element);
    return (
      <Card
        key={index}
        size="small"
        className={`ui-step-row${referenceMissing ? ' ui-step-invalid' : ''}`}
        title={
          <Space>
            <span>步骤 {index + 1}</span>
            <Tag>{UI_ACTION_MAP[step.action]?.label || step.action}</Tag>
            {referenceMissing ? (
              <Tag color="error">引用的元素已失效</Tag>
            ) : null}
          </Space>
        }
        extra={
          <Button
            size="small"
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => removeStep(index)}
          />
        }
      >
        <Row gutter={8}>
          <Col span={6}>
            <Select
              style={{ width: '100%' }}
              value={step.action}
              onChange={(value) => updateStep(index, { action: value })}
              options={Object.keys(UI_ACTION_GROUPS).map((group) => ({
                label: group,
                options: UI_ACTION_GROUPS[group].map((a) => ({ label: a.label, value: a.name })),
              }))}
            />
          </Col>
          {spec.target ? (
            <Col span={18}>
              {canInline ? (
                <Radio.Group
                  size="small"
                  value={step.element ? 'element' : 'inline'}
                  onChange={(e) =>
                    updateStep(index, e.target.value === 'element' ? { by: undefined, value: undefined } : { element: undefined })
                  }
                  style={{ marginBottom: 8 }}
                >
                  <Radio.Button value="element">引用元素库</Radio.Button>
                  <Radio.Button value="inline">内联定位</Radio.Button>
                </Radio.Group>
              ) : null}
              {step.element || !canInline ? (
                <>
                  <Select
                    style={{ width: '100%' }}
                    placeholder="选择元素(页面名.元素名)"
                    value={step.element}
                    showSearch
                    optionFilterProp="label"
                    onChange={(value) => updateStep(index, { element: value })}
                    options={elementOptions.map((o) => ({ label: o.label, value: o.value }))}
                    notFoundContent={
                      <span>元素库为空, 先去元素库沉淀页面与元素</span>
                    }
                  />
                  {referenceMissing ? (
                    <Alert
                      style={{ marginTop: 8 }}
                      type="error"
                      showIcon
                      message={`引用的元素「${step.element}」不存在或已停用, 保存时该步骤会被丢弃`}
                      action={
                        <Button size="small" onClick={() => message.info('请到「元素管理」页面处理')}>
                          去元素库
                        </Button>
                      }
                    />
                  ) : null}
                </>
              ) : (
                <Space.Compact style={{ width: '100%' }}>
                  <Select
                    style={{ width: 160 }}
                    placeholder="定位策略"
                    value={step.by}
                    onChange={(value) => updateStep(index, { by: value, name: undefined })}
                    options={UI_STRATEGY_OPTIONS}
                  />
                  <Input
                    placeholder="定位值"
                    value={step.value}
                    onChange={(e) => updateStep(index, { value: e.target.value })}
                  />
                  {step.by === 'role' ? (
                    <Input
                      style={{ width: 160 }}
                      placeholder="可访问名称(选填)"
                      value={step.name}
                      onChange={(e) => updateStep(index, { name: e.target.value })}
                    />
                  ) : null}
                </Space.Compact>
              )}
            </Col>
          ) : null}
        </Row>

        {/* 各动作自己的参数 */}
        <Row gutter={8} style={{ marginTop: 8 }}>
          {step.action === 'goto' ? (
            <Col span={8}>
              <Input
                addonBefore="地址"
                placeholder="相对路径(如 /login)或白名单内的绝对地址"
                value={step.url}
                onChange={(e) => updateStep(index, { url: e.target.value })}
              />
            </Col>
          ) : null}
          {step.action === 'fill' || step.action === 'press' ? (
            <Col span={8}>
              <Input
                addonBefore={step.action === 'fill' ? '文本' : '按键'}
                placeholder={step.action === 'fill' ? '要输入的文本' : '例如 Enter'}
                value={step.text}
                onChange={(e) => updateStep(index, { text: e.target.value })}
              />
            </Col>
          ) : null}
          {step.action === 'wait_for' ? (
            <Col span={8}>
              <Select
                style={{ width: '100%' }}
                placeholder="等待状态"
                value={step.state}
                onChange={(value) => updateStep(index, { state: value })}
                options={UI_WAIT_STATES}
              />
            </Col>
          ) : null}
          {step.action === 'wait_timeout' ? (
            <Col span={8}>
              <InputNumber
                style={{ width: '100%' }}
                addonBefore="毫秒"
                min={0}
                value={step.timeout}
                onChange={(v) => updateStep(index, { timeout: v ?? undefined })}
              />
            </Col>
          ) : null}
          {step.action === 'upload' ? (
            <Col span={8}>
              <Input
                addonBefore="文件"
                placeholder="文件路径, 多个用逗号分隔"
                value={step.files?.join(',')}
                onChange={(e) =>
                  updateStep(index, {
                    files: e.target.value
                      ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
                      : undefined,
                  })
                }
              />
            </Col>
          ) : null}
          {['select', 'expect_text', 'expect_value', 'expect_count', 'expect_url', 'set_viewport'].includes(
            step.action
          ) ? (
            <Col span={8}>
              <Input
                addonBefore={
                  step.action === 'set_viewport'
                    ? '视口'
                    : step.action === 'expect_count'
                    ? '数量'
                    : '期望值'
                }
                placeholder={step.action === 'set_viewport' ? '1280x720' : undefined}
                value={step.value}
                onChange={(e) => updateStep(index, { value: e.target.value })}
              />
            </Col>
          ) : null}
          {step.action !== 'wait_timeout' ? (
            <Col span={6}>
              <InputNumber
                style={{ width: '100%' }}
                addonBefore="超时(秒)"
                min={1}
                value={step.timeout}
                onChange={(v) => updateStep(index, { timeout: v ?? undefined })}
              />
            </Col>
          ) : null}
        </Row>
      </Card>
    );
  };

  const runStepColumns = [
    { title: '#', dataIndex: 'index', key: 'index', width: 50 },
    { title: '动作', dataIndex: 'action', key: 'action', width: 120 },
    {
      title: '目标',
      dataIndex: 'target',
      key: 'target',
      render: (value: string, record: UiStepResult) => (
        <span className="ui-step-target">
          {value || '-'}
          {record.strategy ? (
            <Tag style={{ marginLeft: 6 }}>{uiStrategyLabel(record.strategy)}</Tag>
          ) : null}
          {record.locator && record.locator !== value ? (
            <span style={{ color: '#999', marginLeft: 6 }}>{record.locator}</span>
          ) : null}
        </span>
      ),
    },
    {
      title: '结果',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (value: string) => (
        <Badge status={value === 'ok' ? 'success' : 'error'} text={value === 'ok' ? '成功' : '失败'} />
      ),
    },
    { title: '耗时', dataIndex: 'cost', key: 'cost', width: 90, render: (v: number) => `${v}s` },
    {
      title: '错误',
      dataIndex: 'error',
      key: 'error',
      render: (value?: string, record?: UiStepResult) => (
        <span>
          {value || '-'}
          {record?.reason ? (
            <Tag color="orange" style={{ marginLeft: 6 }}>
              {UI_ERROR_REASONS[record.reason] || record.reason}
            </Tag>
          ) : null}
        </span>
      ),
    },
  ];

  return (
    <Drawer
      open={open}
      width="86%"
      onClose={onCancel}
      destroyOnHidden
      title={caseId ? '编辑 UI 用例' : '新建 UI 用例'}
      extra={
        <Space>
          <Button onClick={onCancel}>取消</Button>
          {/* U1 / U6: 白名单为空或没有可用节点时不可执行 —— 按钮禁用, 旁边有就地指引 */}
          <Button
            onClick={onDebug}
            loading={running}
            disabled={whitelistEmpty || noNode}
            icon={<PlayCircleOutlined />}
          >
            保存并调试
          </Button>
          <Button type="primary" onClick={() => form.submit()} loading={saving}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" onFinish={onSubmit} preserve={false}>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="name"
              label="用例名"
              rules={[{ required: true, message: '请输入用例名' }]}
              extra={
                nameTooLong ? (
                  <span style={{ color: '#faad14' }}>
                    用例名最长 {MAX_CASE_NAME} 个字符, 保存时会截断为「{truncatedName}」
                  </span>
                ) : (
                  `最长 ${MAX_CASE_NAME} 个字符`
                )
              }
            >
              <Input placeholder="例如 登录页-正常登录" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name="directory_id"
              label="所属目录"
              rules={[{ required: true, message: '请选择目录' }]}
              extra={
                // U3: 项目下没目录时, 目录选择器旁就地给「新建目录」入口, 建完即选中
                <a onClick={() => setDirModalOpen(true)}>
                  <PlusOutlined /> 新建目录
                </a>
              }
            >
              <Select
                placeholder="选择目录"
                options={directoryOptions.map((o) => ({ label: o.label, value: o.value }))}
                notFoundContent={
                  <span>
                    项目下还没有目录, 点上面的「新建目录」就地建一个
                  </span>
                }
              />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="priority" label="优先级">
              <Select
                options={['P0', 'P1', 'P2', 'P3', 'P4'].map((p) => ({ label: p, value: p }))}
              />
            </Form.Item>
          </Col>
          <Col span={6}>
            {/* 执行环境只影响调试执行与全局变量查询, 不进表单 —— 用例本身与环境无关 */}
            <Form.Item label="执行环境">
              <Select
                value={env}
                onChange={setEnv}
                options={envOptions}
                placeholder="选择环境"
                allowClear
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          name="base_url"
          label="起始地址"
          rules={[{ required: true, message: '请输入起始地址' }]}
          extra={
            <Space direction="vertical" size={4}>
              {whitelistEmpty ? (
                <Alert
                  type="warning"
                  showIcon
                  message="本项目尚未配置允许访问的域名, 用例无法执行"
                  action={
                    <Button size="small" icon={<SettingOutlined />} onClick={() => setDomainOpen(true)}>
                      去配置
                    </Button>
                  }
                />
              ) : null}
              {globalVarMissing ? (
                <Alert
                  type="warning"
                  showIcon
                  message="站点地址未配置, 可在环境全局变量里配 ui_base_url"
                  action={
                    <Button size="small" onClick={() => history.push('/config/gconfig')}>
                      去配置
                    </Button>
                  }
                />
              ) : null}
              {noNode ? (
                <Alert
                  type="warning"
                  showIcon
                  message="没有可用的执行节点"
                  action={
                    <Button size="small" onClick={() => history.push('/uiTest/node')}>
                      去节点页
                    </Button>
                  }
                />
              ) : null}
              {baseUrlValue && !baseUrlValue.includes('${') ? (
                <span>{'支持 ${变量} 渲染, 例如 ${ui_base_url}'}</span>
              ) : null}
            </Space>
          }
        >
          <Input placeholder="https://example.com 或 ${ui_base_url}" />
        </Form.Item>

        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="viewport" label="视口">
              <Input placeholder="1280x720" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="locale"
              label="浏览器区域"
              extra="同一个地址在不同语言下内容不同, 固定区域才能保证结果可复现"
            >
              <Input placeholder="en-US / zh-CN" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="timeout" label="单步超时(秒)">
              <InputNumber style={{ width: '100%' }} min={1} />
            </Form.Item>
          </Col>
        </Row>
      </Form>

      <Divider orientation="left">步骤编排</Divider>

      {elementOptions.length === 0 ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="元素库为空, 先沉淀页面与元素"
          description="步骤引用的是元素库里的元素(「页面名.元素名」), 现在只能写内联定位"
          action={
            // U4: 元素选择处要给跳转元素库的入口
            <Button size="small" onClick={() => history.push('/uiTest/element')}>
              去元素库
            </Button>
          }
        />
      ) : null}

      {allInline ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="当前步骤全部使用内联定位"
          description="建议把这些定位纳入元素库 —— 页面改版时只改元素库一处, 不用逐条改步骤"
        />
      ) : null}

      {steps.map((step, index) => renderStepFields(step, index))}

      <Button
        type="dashed"
        block
        icon={<PlusOutlined />}
        onClick={() => setSteps((prev) => [...prev, emptyStep()])}
      >
        添加步骤
      </Button>

      <Modal open={runOpen} title="调试结果" onCancel={() => setRunOpen(false)} footer={null} width={900}>
        {runResult ? (
          <>
            <Space style={{ marginBottom: 12 }}>
              <Tag color={runResult.status === 0 ? 'green' : runResult.status === 1 ? 'red' : 'orange'}>
                {runResult.status_label}
              </Tag>
              <span>耗时 {runResult.cost}s</span>
              {runResult.error ? <span style={{ color: '#ff4d4f' }}>{runResult.error}</span> : null}
              {runResult.screenshot_url ? (
                <a href={runResult.screenshot_url} target="_blank" rel="noreferrer">
                  查看失败截图
                </a>
              ) : null}
            </Space>
            <Table
              rowKey="index"
              size="small"
              columns={runStepColumns as any}
              dataSource={runResult.steps || []}
              pagination={false}
              locale={{ emptyText: '没有执行步骤' }}
            />
          </>
        ) : (
          <Empty />
        )}
      </Modal>

      <DomainModal
        open={domainOpen}
        projectId={projectId}
        env={env}
        onCancel={() => setDomainOpen(false)}
        onChanged={() => projectId && fetchDomains(projectId, env)}
      />

      {/* U3: 就地新建目录, 建完即选中 */}
      <Modal
        open={dirModalOpen}
        title="新建目录"
        onCancel={() => setDirModalOpen(false)}
        onOk={() => dirForm.submit()}
        destroyOnHidden
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
    </Drawer>
  );
};

export default CaseEditor;
