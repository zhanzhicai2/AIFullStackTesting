import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Select,
  Space,
  Table,
  Tag,
  message,
} from 'antd';
import { ImportOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { history } from '@umijs/max';
import { listProject } from '@/services/project';
import { listTestcaseTree } from '@/services/testcase';
import { UiStep } from '@/services/uiTest';

interface Option {
  label: string;
  value: number;
}

interface ImportResult {
  import_log_id: number;
  parsed_lines: number;
  skipped_lines: number;
  pages_created: number;
  elements_created: number;
  elements_reused: number;
  case_id: number;
  warnings: string[];
  steps: UiStep[];
}

/**
 * 录制导入
 *
 * 录制在**用户本地**完成(`npx playwright codegen --target python`), 把脚本粘回来,
 * 平台只做静态解析并自动建页面/元素/用例草稿。
 *
 * **平台不执行录制脚本里的任何内容** —— 脚本里的 `page.evaluate(...)` 这类行会被跳过并说明。
 */
const UiRecordImport: React.FC = () => {
  const { importRecord, saving } = useModel('uiTest');
  const [projectId, setProjectId] = useState<number | undefined>();
  const [projectOptions, setProjectOptions] = useState<Option[]>([]);
  const [directoryId, setDirectoryId] = useState<number | undefined>();
  const [directoryOptions, setDirectoryOptions] = useState<Option[]>([]);
  const [script, setScript] = useState('');
  const [result, setResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);

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

  useEffect(() => {
    if (!projectId) return;
    listTestcaseTree({ project_id: projectId })
      .then((res: any) => {
        if (res?.code !== 0) return;
        const options: Option[] = [];
        const walk = (nodes: any[]) => {
          nodes.forEach((n) => {
            options.push({ label: n.title, value: n.key });
            if (n.children?.length) walk(n.children);
          });
        };
        walk(res.data || []);
        setDirectoryOptions(options);
      })
      .catch(() => undefined);
  }, [projectId]);

  const onImport = useCallback(async () => {
    if (!projectId) {
      message.info('请先选择项目');
      return;
    }
    if (!script.trim()) {
      message.info('请先粘贴录制脚本');
      return;
    }
    setImporting(true);
    try {
      const data = await importRecord({
        project_id: projectId,
        source: 'codegen',
        script,
        directory_id: directoryId,
      } as any);
      if (data) setResult(data as ImportResult);
    } finally {
      setImporting(false);
    }
  }, [projectId, script, directoryId, importRecord]);

  const stepColumns = useMemo(
    () => [
      { title: '#', key: 'index', width: 50, render: (_: unknown, __: unknown, index: number) => index + 1 },
      { title: '动作', dataIndex: 'action', key: 'action', width: 140 },
      {
        title: '目标',
        key: 'target',
        render: (_: unknown, record: UiStep) =>
          record.element || record.by ? `${record.element || ''} ${record.value || ''}` : record.url || '-',
      },
    ],
    []
  );

  return (
    <div className="ui-page">
      <Row gutter={12}>
        <Col span={14}>
          <Card bordered={false} title="录制脚本">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Alert
                type="info"
                showIcon
                message="在本地录制后把脚本粘回来"
                description={
                  <span>
                    本地执行 <code>npx playwright codegen --target python</code>, 录完把脚本粘到下面。
                    <br />
                    平台**只做静态解析**, 不执行脚本里的任何内容 —— 自由代码的行会被跳过并说明。
                  </span>
                }
              />
              <Row gutter={8}>
                <Col span={8}>
                  <Select
                    style={{ width: '100%' }}
                    placeholder="选择项目"
                    value={projectId}
                    options={projectOptions}
                    onChange={(value) => setProjectId(value)}
                  />
                </Col>
                <Col span={8}>
                  <Select
                    style={{ width: '100%' }}
                    placeholder="选择目录(可留空)"
                    value={directoryId}
                    options={directoryOptions}
                    onChange={(value) => setDirectoryId(value)}
                    allowClear
                    notFoundContent="项目下还没有目录, 可以先不选"
                  />
                </Col>
              </Row>
              {/* U5: 没粘贴脚本时就地提示, 而不是只报一个错误码 */}
              {script.trim() ? null : (
                <Alert
                  type="warning"
                  showIcon
                  message="还没有粘贴录制脚本"
                  description="粘贴录制脚本, 或改用手工新建用例"
                  action={
                    <Button size="small" onClick={() => history.push('/uiTest/case')}>
                      手工新建
                    </Button>
                  }
                />
              )}
              <Input.TextArea
                rows={18}
                value={script}
                onChange={(e) => setScript(e.target.value)}
                placeholder={'from playwright.sync_api import Playwright, sync_playwright\n\ndef run(playwright: Playwright) -> None:\n    ...'}
              />
              <Button
                type="primary"
                icon={<ImportOutlined />}
                loading={importing || saving}
                onClick={onImport}
              >
                导入
              </Button>
            </Space>
          </Card>
        </Col>
        <Col span={10}>
          <Card bordered={false} title="导入结果">
            {!result ? (
              <div className="ui-empty-hint">
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有导入过" />
              </div>
            ) : (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color="green">解析 {result.parsed_lines} 行</Tag>
                  <Tag color={result.skipped_lines ? 'orange' : 'default'}>
                    跳过 {result.skipped_lines} 行
                  </Tag>
                  <Tag color="blue">新建页面 {result.pages_created} 个</Tag>
                  <Tag color="blue">新建元素 {result.elements_created} 个</Tag>
                  <Tag>复用元素 {result.elements_reused} 个</Tag>
                </Space>
                {result.warnings?.length ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={`有 ${result.warnings.length} 行没解析出来`}
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {result.warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    }
                  />
                ) : null}
                <Table
                  rowKey={(_: unknown, index?: number) => String(index)}
                  size="small"
                  columns={stepColumns as any}
                  dataSource={result.steps || []}
                  pagination={false}
                  scroll={{ y: 320 }}
                />
                <Alert
                  type="success"
                  showIcon
                  message="用例已创建, 状态是「调试中」"
                  description="核对步骤无误后把状态改成「正常运行」即视为采纳"
                  action={
                    <Button
                      size="small"
                      icon={<ThunderboltOutlined />}
                      onClick={() => history.push('/uiTest/case')}
                    >
                      去用例管理
                    </Button>
                  }
                />
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default UiRecordImport;
