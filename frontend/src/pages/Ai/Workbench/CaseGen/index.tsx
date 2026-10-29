import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Col, Modal, Row, Space, Spin, Typography, Form, Input, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useModel, useSearchParams } from '@umijs/max';
import { listProject } from '@/services/project';
import { insertTestcaseDirectory, listTestcaseTree } from '@/services/testcase';
import { listUiElements } from '@/services/uiTest';
import { AiDraftSummary } from '@/services/aiWorkbench';
import DemandForm, { DemandFormValues, Option } from './DemandForm';
import DocumentUpload from './DocumentUpload';
import DraftTable from './DraftTable';
import DraftDrawer from './DraftDrawer';
import '../AiWorkbench.less';

const { Text } = Typography;

interface TreeNode {
  id: number;
  name: string;
  parent?: number | null;
  children?: TreeNode[];
}

/**
 * 用例生成工作台
 *
 * 左边是需求输入(表单 + 文档上传), 右边是草稿审核表。
 * 生成出来的永远是**草稿**, 人工审核采纳后才进正式用例库。
 */
const CaseGenPage: React.FC = () => {
  const { models, generating, generate, fetchDrafts, saveDraft, acceptDrafts, rejectDrafts, fetchModels } =
    useModel('aiWorkbench');
  const [searchParams] = useSearchParams();

  const [projectOptions, setProjectOptions] = useState<Option[]>([]);
  const [projectId, setProjectId] = useState<number | undefined>();
  const [directoryOptions, setDirectoryOptions] = useState<Option[]>([]);
  const [directoryId, setDirectoryId] = useState<number | undefined>();
  const [elementCount, setElementCount] = useState<number>(0);

  const [drafts, setDrafts] = useState<AiDraftSummary[]>([]);
  const [draftTotal, setDraftTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState<number | undefined>();
  const [batchId, setBatchId] = useState<number | undefined>();
  const [failed, setFailed] = useState<Array<{ id: number; reason: string }>>([]);
  const [error, setError] = useState('');
  const [lastValues, setLastValues] = useState<DemandFormValues | null>(null);

  const [current, setCurrent] = useState<AiDraftSummary | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  // 文档解析出来的正文 —— nonce 变化时填进表单
  const [fillContent, setFillContent] = useState<{ content: string; nonce: number } | null>(null);

  // 从 Bug 分析的「用此生成用例」跳过来时, URL 带 prompt(复现步骤)
  const promptFromBug = searchParams.get('prompt');
  useEffect(() => {
    if (promptFromBug) {
      setFillContent({ content: promptFromBug, nonce: Date.now() });
    }
  }, [promptFromBug]);

  const [dirModalOpen, setDirModalOpen] = useState(false);
  const [dirForm] = Form.useForm();

  // ---- 项目 ----
  useEffect(() => {
    listProject({ page: 1, size: 200 })
      .then((res: any) => {
        if (res?.code === 0) {
          const options = (res.data || []).map((item: any) => ({
            label: item.name,
            value: item.id,
          }));
          setProjectOptions(options);
          if (options.length > 0) setProjectId(options[0].value);
        }
      })
      .catch(() => undefined);
  }, []);

  // ---- 目录树 ----
  const loadDirectories = useCallback((pid: number) => {
    listTestcaseTree({ project_id: pid })
      .then((res: any) => {
        if (res?.code === 0) {
          const tree = (res.data || []) as TreeNode[];
          const flat: Option[] = [];
          const walk = (nodes: TreeNode[]) => {
            nodes.forEach((node) => {
              flat.push({ label: node.name, value: node.id });
              if (node.children) walk(node.children);
            });
          };
          walk(tree);
          setDirectoryOptions(flat);
          if (flat.length === 0) setDirectoryId(undefined);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (projectId) loadDirectories(projectId);
  }, [projectId, loadDirectories]);

  // ---- 元素库数量(G4) ----
  useEffect(() => {
    if (!projectId) return;
    listUiElements({ project_id: projectId, status: 1 })
      .then((res: any) => {
        if (res?.code === 0) setElementCount((res.data || []).length);
      })
      .catch(() => undefined);
  }, [projectId]);

  // ---- 可用模型(G1) ----
  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  const loadDrafts = useCallback(
    async (id: number, status?: number) => {
      const list = await fetchDrafts(id, status, 1, 100);
      if (list) {
        setDrafts(list as AiDraftSummary[]);
        setDraftTotal(list.length);
      }
    },
    [fetchDrafts],
  );

  const handleGenerate = async (values: DemandFormValues) => {
    if (!projectId || !directoryId) {
      message.warning('请先选择项目与目标目录');
      return;
    }
    setError('');
    setFailed([]);
    setLastValues(values);
    try {
      const result: any = await generate({
        project_id: projectId,
        directory_id: directoryId,
        title: values.title,
        test_type: values.test_type || 'api',
        vendor_id: values.vendor_id as number,
        model_id: values.model_id as number,
        source_type: values.source_type || 'text',
        source_name: values.source_name,
        content: values.content,
      });
      if (result) {
        setBatchId(result.batch_id);
        setDrafts(result.cases || []);
        setDraftTotal(result.case_count || 0);
        message.success(`生成完成, 共 ${result.case_count} 条草稿`);
        if ((result.warnings || []).length > 0) {
          message.warning(`有 ${result.warnings.length} 条校验告警, 详见草稿列表`);
        }
      }
    } catch (e: any) {
      // **G5** —— 失败要给出可操作的原因, 并提供重试
      setError(e?.msg || e?.message || '模型调用失败, 请重试');
    }
  };

  const handleAccept = async (ids: number[]) => {
    setFailed([]);
    const res: any = await acceptDrafts(ids);
    if (res?.code === 0) {
      const data = res.data || {};
      message.success(res.msg || '采纳完成');
      if ((data.failed || []).length > 0) {
        setFailed(data.failed);
        message.error(`${data.failed.length} 条未通过采纳前校验`);
      }
      if (batchId) loadDrafts(batchId, statusFilter);
    }
  };

  const handleReject = async (ids: number[]) => {
    setFailed([]);
    const res: any = await rejectDrafts(ids);
    if (res?.code === 0) {
      message.success(res.msg || '驳回完成');
      if (batchId) loadDrafts(batchId, statusFilter);
    }
  };

  const handleSave = async (content: Record<string, unknown>) => {
    if (!current) return null;
    setSaving(true);
    try {
      const warn = await saveDraft({ draft_id: current.id, content });
      if (warn && batchId) loadDrafts(batchId, statusFilter);
      return warn;
    } finally {
      setSaving(false);
    }
  };

  const handleCreateDirectory = async () => {
    if (!projectId) {
      message.warning('请先选择项目');
      return;
    }
    dirForm.resetFields();
    setDirModalOpen(true);
  };

  const submitDirectory = async () => {
    const values = await dirForm.validateFields();
    const res: any = await insertTestcaseDirectory({
      name: values.name,
      project_id: projectId,
      parent: null,
    });
    if (res?.code === 0) {
      message.success('目录创建成功');
      setDirModalOpen(false);
      loadDirectories(projectId as number);
      if (res.data?.id) setDirectoryId(res.data.id);
    }
  };

  return (
    <div className="ai-workbench-page">
      <Row gutter={12}>
        <Col xs={24} xl={9}>
          <DemandForm
            projectOptions={projectOptions}
            projectId={projectId}
            directoryOptions={directoryOptions}
            directoryId={directoryId}
            models={models}
            elementCount={elementCount}
            fillContent={fillContent}
            loading={generating}
            onProjectChange={(value) => setProjectId(value)}
            onDirectoryChange={(value) => setDirectoryId(value)}
            onCreateDirectory={handleCreateDirectory}
            onSubmit={handleGenerate}
          />
          <div style={{ marginTop: 12 }}>
            <DocumentUpload
              disabled={generating}
              onParsed={(content, filename, warnings) => {
                // 解析出来的正文直接填进表单的「需求正文」
                message.info(`已把《${filename}》的正文填入需求正文${warnings.length ? '(有解析告警)' : ''}`);
                setFillContent({ content, nonce: Date.now() });
              }}
              onError={(reason) => setError(reason)}
            />
          </div>
        </Col>
        <Col xs={24} xl={15}>
          {error ? (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message="生成失败"
              description={
                <Space direction="vertical" size={4}>
                  <Text>{error}</Text>
                  <Space>
                    <Button
                      size="small"
                      icon={<ReloadOutlined />}
                      onClick={() => lastValues && handleGenerate(lastValues)}
                    >
                      重试
                    </Button>
                  </Space>
                </Space>
              }
            />
          ) : null}
          <Spin spinning={generating}>
            <DraftTable
              drafts={drafts}
              total={draftTotal}
              loading={generating}
              failed={failed}
              onAccept={handleAccept}
              onReject={handleReject}
              onView={(draft) => {
                setCurrent(draft);
                setDrawerOpen(true);
              }}
              onStatusFilter={(status) => {
                setStatusFilter(status);
                if (batchId) loadDrafts(batchId, status);
              }}
            />
          </Spin>
        </Col>
      </Row>

      <DraftDrawer
        open={drawerOpen}
        draft={current}
        content={(current as any)?.content}
        saving={saving}
        onClose={() => setDrawerOpen(false)}
        onSave={handleSave}
      />

      <Modal
        title="新建目录"
        open={dirModalOpen}
        onCancel={() => setDirModalOpen(false)}
        onOk={submitDirectory}
        okText="创建"
      >
        <Form form={dirForm} layout="vertical">
          <Form.Item
            label="目录名"
            name="name"
            rules={[{ required: true, message: '请填写目录名' }, { max: 18, message: '不超过 18 个字符' }]}
          >
            <Input placeholder="目录名" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default CaseGenPage;
